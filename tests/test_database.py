import pytest
import sqlite3
import os
import time
from datetime import datetime

# Redirect database path for testing
os.environ['TEST_MODE'] = '1'

from core import database

@pytest.fixture(autouse=True)
def setup_teardown(tmp_path, monkeypatch):
    """Setup clean database before each test and remove after."""
    test_db = str(tmp_path / "test_downtime.db")
    monkeypatch.setattr(database, "DB_PATH", test_db, raising=False)
    if os.path.exists(test_db):
        os.remove(test_db)

    database._init_db()

    yield

    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except Exception:
            pass

def test_database_init():
    """Test schema creation."""
    assert os.path.exists(database.DB_PATH)
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in c.fetchall()]
        assert 'incidents' in tables
        assert 'metrics' in tables
        assert 'audit_log' in tables

def test_log_incident_down_and_up():
    """Test mencatat downtime dan recovery."""
    host = "192.168.1.10"
    
    # 1. Log DOWN
    incident_id = database.log_incident_down(host, "Server Down", "snapshot", "server")
    assert incident_id is not None
    
    history_down = database.get_recent_history(1)
    assert len(history_down) == 1
    assert history_down[0]['host'] == host
    assert history_down[0]['waktu_up'] is None
    
    # Simulate time passing
    time.sleep(1)
    
    # 2. Log UP
    database.log_incident_up(host)
    
    history_up = database.get_recent_history(1)
    assert len(history_up) == 1
    assert history_up[0]['host'] == host
    assert history_up[0]['waktu_up'] is not None
    assert history_up[0]['durasi_detik'] > 0


def test_log_incident_up_can_use_custom_closed_reason():
    host = "192.168.1.20"
    database.log_incident_down(host, "Server Down", "snapshot", "server")

    closed = database.log_incident_up(host, closed_reason="reconciled")
    assert closed == 1

    history = database.get_recent_history(1)
    assert history[0]["host"] == host
    assert history[0]["closed_reason"] == "reconciled"


def test_log_incident_up_closes_multiple_open_rows_for_same_host():
    host = "192.168.1.21"
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            (host, "dup1", "2026-01-01T00:00:00", "server")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            (host, "dup2", "2026-01-01T00:01:00", "server")
        )
        conn.commit()

    closed = database.log_incident_up(host, closed_reason="reconciled")
    assert closed == 2

    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM incidents WHERE host = ? AND waktu_up IS NULL", (host,))
        assert c.fetchone()[0] == 0


def test_log_incident_down_reuses_existing_open_incident():
    host = "192.168.1.22"
    first = database.log_incident_down(host, "Server Down", "snapshot", "server")
    second = database.log_incident_down(host, "Server Down", "snapshot", "server")

    assert first == second
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM incidents WHERE host = ? AND waktu_up IS NULL", (host,))
        assert c.fetchone()[0] == 1


def test_dedupe_open_incidents_keeps_latest_only():
    host = "192.168.1.23"
    database.log_incident_down(host, "Server Down", "snapshot", "server")
    database.log_incident_up(host, "reconciled")
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            (host, "dup1", "2026-01-01T00:00:00", "server")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            (host, "dup2", "2026-01-01T00:01:00", "server")
        )
        conn.commit()

    deduped = database.dedupe_open_incidents(host)
    assert deduped == 1

    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM incidents WHERE host = ? AND waktu_up IS NULL", (host,))
        assert c.fetchone()[0] == 1


def test_close_open_incidents_by_tag_closes_all_matching_rows():
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            ("vpn-hq", "vpn down", "2026-01-01T00:00:00", "vpn")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            ("vpn-branch", "vpn down", "2026-01-01T00:01:00", "vpn")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            ("server-a", "server down", "2026-01-01T00:02:00", "server")
        )
        conn.commit()

    closed = database.close_open_incidents_by_tag("vpn", "monitor-disabled")
    assert closed == 2

    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM incidents WHERE tag = 'vpn' AND waktu_up IS NULL")
        assert c.fetchone()[0] == 0
        c.execute("SELECT COUNT(*) FROM incidents WHERE tag = 'server' AND waktu_up IS NULL")
        assert c.fetchone()[0] == 1

def test_metrics_recording():
    """Test pencatatan metric cpu dan ram."""
    database.record_metric('cpu_usage', 45.5)
    database.record_metric('cpu_usage', 50.0)
    
    metrics = database.get_metrics('cpu_usage', hours=1)
    assert len(metrics) == 2
    
    summary = database.get_metrics_summary('cpu_usage', days=1)
    assert summary['count'] == 2
    assert summary['min'] == 45.5
    assert summary['max'] == 50.0


def test_get_metrics_limit_prefers_latest_rows():
    """Limit harus mengambil row terbaru dalam rentang waktu."""
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO metrics (timestamp, metric_name, metric_value, metadata) VALUES (?, ?, ?, ?)",
            ("2026-01-01T00:00:00", "cpu_usage", 10, None)
        )
        c.execute(
            "INSERT INTO metrics (timestamp, metric_name, metric_value, metadata) VALUES (?, ?, ?, ?)",
            ("2026-01-01T00:01:00", "cpu_usage", 20, None)
        )
        c.execute(
            "INSERT INTO metrics (timestamp, metric_name, metric_value, metadata) VALUES (?, ?, ?, ?)",
            ("2026-01-01T00:02:00", "cpu_usage", 30, None)
        )
        conn.commit()

    rows = database.get_metrics("cpu_usage", hours=999999, limit=2)
    assert len(rows) == 2
    # Tetap urut ASC untuk konsumsi chart, tapi berasal dari 2 data TERBARU.
    assert rows[0]["value"] == 20
    assert rows[1]["value"] == 30

def test_audit_logging():
    """Test pencatatan audit log."""
    database.audit_log(12345, "admin1", "/reboot", "", "berhasil")
    
    logs = database.get_audit_log(5)
    assert len(logs) == 1
    assert logs[0]['username'] == "admin1"
    assert logs[0]['command'] == "/reboot"

def test_auto_tagging():
    """Test auto-tag logic."""
    assert database._auto_tag("CORE DOWN", "192.168.1.1") == "core"
    assert database._auto_tag("SERVER ISSUE", "192.168.1.10") == "server"
    assert database._auto_tag("WIFI PARTIAL", "AP 1") == "wifi"
    assert database._auto_tag("WAN GATEWAY DOWN", "1.1.1.1") == "wan"


def test_count_all_incidents():
    """Test count total insiden."""
    # Database starts empty
    assert database.count_all_incidents() == 0

    # Add 2 incidents
    database.log_incident_down("host1", "DOWN", "snap", "server")
    database.log_incident_down("host2", "DOWN", "snap", "ap")

    assert database.count_all_incidents() == 2


def test_close_stale_incidents():
    """Test close stale incidents > max_hours."""
    host = "192.168.1.99"

    # Create incident
    database.log_incident_down(host, "DOWN", "snap", "server")

    # Verify it's open
    history = database.get_recent_history(1)
    assert history[0]['waktu_up'] is None

    # Manually backdate the incident to make it stale
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE incidents SET waktu_down = '2020-01-01T00:00:00' WHERE host = ?",
            (host,)
        )
        conn.commit()

    # Close stale incidents (> 24h)
    closed = database.close_stale_incidents(max_hours=24)
    assert closed == 1

    # Verify it's now closed
    history = database.get_recent_history(1)
    assert history[0]['waktu_up'] is not None
    assert history[0]['durasi_detik'] is not None
    assert history[0]['durasi_detik'] > 0
    assert history[0]['closed_reason'] == 'auto-close'


def test_get_recent_history_with_offset():
    """Test pagination offset."""
    # Add 3 incidents
    database.log_incident_down("host1", "DOWN1", "snap", "server")
    database.log_incident_down("host2", "DOWN2", "snap", "ap")
    database.log_incident_down("host3", "DOWN3", "snap", "wan")

    # Get first page (limit 2)
    page1 = database.get_recent_history(limit=2, offset=0)
    assert len(page1) == 2

    # Get second page (limit 2, offset 2)
    page2 = database.get_recent_history(limit=2, offset=2)
    assert len(page2) == 1  # Only 1 remaining

    # Ensure no overlap
    page1_hosts = {h['host'] for h in page1}
    page2_hosts = {h['host'] for h in page2}
    assert page1_hosts.isdisjoint(page2_hosts)


def test_log_incident_down_auto_tags_when_tag_empty():
    host = "dns.google"
    incident_id = database.log_incident_down(host, "Internet Down", "snap", "")
    assert incident_id is not None
    history = database.get_recent_history(1)
    assert history[0]["tag"] == "internet"


def test_log_incident_up_returns_zero_when_host_missing():
    assert database.log_incident_up("missing-host") == 0


def test_dedupe_open_incidents_returns_zero_when_empty():
    assert database.dedupe_open_incidents() == 0


def test_log_incident_up_handles_invalid_waktu_down():
    host = "192.168.1.55"
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            (host, "invalid", "bad-ts", "server")
        )
        conn.commit()

    closed = database.log_incident_up(host)
    assert closed == 1
    history = database.get_recent_history(1)
    assert history[0]["durasi_detik"] == 0


def test_dedupe_open_incidents_host_handles_invalid_timestamp():
    host = "192.168.1.56"
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            (host, "dup-old", "bad-ts", "server")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            (host, "dup-new", datetime.now().isoformat(), "server")
        )
        conn.commit()

    closed = database.dedupe_open_incidents(host)
    assert closed == 1
    history = database.get_recent_history(2)
    closed_rows = [row for row in history if row["host"] == host and row["waktu_up"] is not None]
    assert closed_rows[0]["durasi_detik"] == 0


def test_get_recent_history_can_filter_by_tag():
    database.log_incident_down("host-server", "Server Down", "snap", "server")
    database.log_incident_down("host-wifi", "Wifi Down", "snap", "wifi")

    history = database.get_recent_history(limit=10, tag_filter="wifi")
    assert len(history) == 1
    assert history[0]["host"] == "host-wifi"


def test_dedupe_open_incidents_all_hosts_variant():
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)", ("a", "down", "2026-01-01T00:00:00", "server"))
        c.execute("INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)", ("a", "down", "2026-01-01T00:01:00", "server"))
        c.execute("INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)", ("b", "down", "2026-01-01T00:02:00", "server"))
        c.execute("INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)", ("b", "down", "bad-ts", "server"))
        conn.commit()

    deduped = database.dedupe_open_incidents()
    assert deduped == 2
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT host, COUNT(*) FROM incidents WHERE waktu_up IS NULL GROUP BY host")
        rows = dict(c.fetchall())
        assert rows == {"a": 1, "b": 1}


def test_close_open_incidents_by_tag_returns_zero_when_empty():
    assert database.close_open_incidents_by_tag("vpn") == 0


def test_close_open_incidents_by_tag_handles_invalid_time():
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            ("vpn-hq", "vpn down", "bad-ts", "vpn")
        )
        conn.commit()

    closed = database.close_open_incidents_by_tag("vpn")
    assert closed == 1
    history = database.get_recent_history(1)
    assert history[0]["durasi_detik"] == 0


def test_get_stats_today_counts_today_rows():
    today = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)", ("today-host", "down", today, "server"))
        c.execute("INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)", ("old-host", "down", "2020-01-01T00:00:00", "server"))
        conn.commit()

    assert database.get_stats_today() == 1
    assert database.count_incidents_today() == 1


def test_cleanup_old_data_removes_closed_incidents_metrics_and_old_audit():
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, waktu_up, durasi_detik, tag) VALUES (?, ?, ?, ?, ?, ?)",
            ("old-closed", "down", "2020-01-01T00:00:00", "2020-01-01T01:00:00", 3600, "server")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, tag) VALUES (?, ?, ?, ?)",
            ("old-open", "down", "2020-01-01T00:00:00", "server")
        )
        c.execute(
            "INSERT INTO metrics (timestamp, metric_name, metric_value, metadata) VALUES (?, ?, ?, ?)",
            ("2020-01-01T00:00:00", "cpu_usage", 10, None)
        )
        c.execute(
            "INSERT INTO audit_log (timestamp, admin_id, username, command, params, result) VALUES (?, ?, ?, ?, ?, ?)",
            ("2020-01-01T00:00:00", 1, "admin", "/cmd", "", "ok")
        )
        conn.commit()

    deleted = database.cleanup_old_data(days=60)
    assert deleted == 3
    history = database.get_recent_history(10)
    assert any(row["host"] == "old-open" for row in history)
    assert all(row["host"] != "old-closed" for row in history)


def test_reset_all_data_returns_deleted_counts():
    database.log_incident_down("host1", "DOWN", "snap", "server")
    database.record_metric("cpu_usage", 10)
    database.audit_log(1, "admin", "/cmd", "", "ok")

    result = database.reset_all_data()
    assert result == {"incidents": 1, "metrics": 1, "audit_log": 1, "total": 3}
    assert database.count_all_incidents() == 0
    assert database.get_metrics("cpu_usage", hours=24) == []
    assert database.get_audit_log(10) == []


def test_get_uptime_stats_formats_seconds_minutes_and_hours():
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, waktu_up, durasi_detik, tag) VALUES (?, ?, ?, ?, ?, ?)",
            ("host-sec", "down", datetime.now().isoformat(), datetime.now().isoformat(), 45, "server")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, waktu_up, durasi_detik, tag) VALUES (?, ?, ?, ?, ?, ?)",
            ("host-min", "down", datetime.now().isoformat(), datetime.now().isoformat(), 125, "server")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, waktu_up, durasi_detik, tag) VALUES (?, ?, ?, ?, ?, ?)",
            ("host-hour", "down", datetime.now().isoformat(), datetime.now().isoformat(), 3665, "server")
        )
        conn.commit()

    stats = database.get_uptime_stats(days=7)
    assert stats["host-sec"]["total_downtime_str"] == "45s"
    assert stats["host-min"]["total_downtime_str"] == "2m 5s"
    assert stats["host-hour"]["total_downtime_str"] == "1j 1m 5s"


def test_get_uptime_stats_returns_empty_dict_when_no_rows():
    assert database.get_uptime_stats(days=7) == {}


def test_record_metric_and_batch_preserve_metadata():
    database.record_metric("cpu_usage", 45.5, metadata={"iface": "ether1"})
    database.record_metrics_batch([
        ("traffic_rx_bps", 1000, {"iface": "ether1"}),
        ("traffic_tx_bps", 2000, None),
    ])

    cpu = database.get_metrics("cpu_usage", hours=24)
    rx = database.get_metrics("traffic_rx_bps", hours=24)
    tx = database.get_metrics("traffic_tx_bps", hours=24)

    assert cpu[0]["metadata"] == {"iface": "ether1"}
    assert rx[0]["metadata"] == {"iface": "ether1"}
    assert tx[0]["metadata"] is None


def test_get_metrics_summary_returns_none_when_empty():
    assert database.get_metrics_summary("missing", days=1) is None


def test_get_audit_log_can_filter_by_admin():
    database.audit_log(1, "admin1", "/one", "", "ok")
    database.audit_log(2, "admin2", "/two", "", "ok")

    logs = database.get_audit_log(limit=10, admin_id=2)
    assert len(logs) == 1
    assert logs[0]["username"] == "admin2"


def test_get_report_returns_host_and_tag_breakdown():
    now = datetime.now().isoformat()
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, waktu_up, durasi_detik, tag) VALUES (?, ?, ?, ?, ?, ?)",
            ("srv1", "Server Down", now, now, 120, "server")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, waktu_up, durasi_detik, tag) VALUES (?, ?, ?, ?, ?, ?)",
            ("ap1", "Wifi Down", now, now, 60, "wifi")
        )
        conn.commit()

    report = database.get_report(days=7)
    assert report["total_incidents"] == 2
    assert report["mttr_seconds"] == 90
    assert {row["tag"] for row in report["tags"]} == {"server", "wifi"}
    assert {row["host"] for row in report["hosts"]} == {"srv1", "ap1"}


def test_get_report_can_filter_by_tag():
    now = datetime.now().isoformat()
    with database._get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, waktu_up, durasi_detik, tag) VALUES (?, ?, ?, ?, ?, ?)",
            ("srv1", "Server Down", now, now, 120, "server")
        )
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, waktu_up, durasi_detik, tag) VALUES (?, ?, ?, ?, ?, ?)",
            ("ap1", "Wifi Down", now, now, 60, "wifi")
        )
        conn.commit()

    report = database.get_report(days=7, tag_filter="wifi")
    assert report["total_incidents"] == 1
    assert report["tags"] == [{"tag": "wifi", "count": 1}]
    assert report["hosts"][0]["host"] == "ap1"


def test_auto_tagging_additional_branches():
    assert database._auto_tag("CRITICAL DEVICE DOWN", "192.168.1.50") == "critical"
    assert database._auto_tag("Internet unreachable", "1.1.1.1") == "internet"
    assert database._auto_tag("DHCP conflict", "192.168.1.60") == "dhcp"
    assert database._auto_tag("misc", "dns.local") == "dns"
    assert database._auto_tag("misc", "host") == "other"
    assert database._auto_tag("", "host") == ""

