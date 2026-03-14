import json
from pathlib import Path

from services import runtime_reset
from core.runtime_reset_signal import read_runtime_reset_signal


def _seed_runtime_db(db_module):
    db_module._init_db()
    db_module.log_incident_down("192.168.3.10", "SERVER DOWN", "snapshot", "server")
    db_module.record_metric("cpu_usage", 50, None)
    db_module.audit_log(1, "admin", "/status", "", "ok")


def test_reset_runtime_data_clears_db_and_runtime_files(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    data_dir.mkdir()
    logs_dir.mkdir()

    test_db = str(data_dir / "downtime.db")
    monkeypatch.setattr(runtime_reset.database, "DB_PATH", test_db, raising=False)
    _seed_runtime_db(runtime_reset.database)

    (data_dir / "state.json").write_text("{}", encoding="utf-8")
    (data_dir / "monitor_state.json").write_text("{}", encoding="utf-8")
    (data_dir / "alert_gate.json").write_text("{}", encoding="utf-8")
    (data_dir / "pending_acks.json").write_text('{"a":1}', encoding="utf-8")
    (data_dir / "ack_events.json").write_text('["x"]', encoding="utf-8")
    (data_dir / "aktivitas.log").write_text("history", encoding="utf-8")
    (logs_dir / "bot.log").write_text("bot-history", encoding="utf-8")
    (logs_dir / "monitor.log").write_text("monitor-history", encoding="utf-8")
    (logs_dir / "pm2-bot.log").write_text("pm2-bot-history", encoding="utf-8")
    (logs_dir / "pm2-monitor.log").write_text("pm2-monitor-history", encoding="utf-8")
    (data_dir / "runtime_config.json").write_text('{"x":1}', encoding="utf-8")
    (data_dir / "tmpabc.tmp").write_text("junk", encoding="utf-8")

    result = runtime_reset.reset_runtime_data(project_root=tmp_path)

    assert result["database"]["incidents"] == 1
    assert result["database"]["metrics"] == 1
    assert result["database"]["audit_log"] == 1
    assert json.loads((data_dir / "pending_acks.json").read_text(encoding="utf-8")) == {}
    assert json.loads((data_dir / "ack_events.json").read_text(encoding="utf-8")) == []
    assert not (data_dir / "state.json").exists()
    assert not (data_dir / "monitor_state.json").exists()
    assert not (data_dir / "alert_gate.json").exists()
    assert (data_dir / "runtime_config.json").exists()
    assert (data_dir / "aktivitas.log").read_text(encoding="utf-8") == ""
    assert (logs_dir / "bot.log").read_text(encoding="utf-8") == ""
    assert (logs_dir / "monitor.log").read_text(encoding="utf-8") == ""
    assert (logs_dir / "pm2-bot.log").read_text(encoding="utf-8") == ""
    assert (logs_dir / "pm2-monitor.log").read_text(encoding="utf-8") == ""
    assert not (data_dir / "tmpabc.tmp").exists()
    assert result["reset_signal_emitted"] is True
    signal_payload = read_runtime_reset_signal(data_dir / "runtime_reset_signal.json")
    assert signal_payload["reason"] == "reset_runtime_data"
    assert signal_payload["clear_runtime_config"] is False


def test_reset_runtime_data_can_remove_runtime_config(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    test_db = str(data_dir / "downtime.db")
    monkeypatch.setattr(runtime_reset.database, "DB_PATH", test_db, raising=False)
    runtime_reset.database._init_db()
    (data_dir / "runtime_config.json").write_text('{"DAILY_REPORT_HOUR":6}', encoding="utf-8")

    result = runtime_reset.reset_runtime_data(project_root=tmp_path, clear_runtime_config=True)

    assert result["runtime_config_removed"] is True
    assert not (data_dir / "runtime_config.json").exists()
    signal_payload = read_runtime_reset_signal(data_dir / "runtime_reset_signal.json")
    assert signal_payload["clear_runtime_config"] is True
