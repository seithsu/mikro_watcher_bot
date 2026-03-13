# ============================================
# DATABASE - SQLite Storage Layer
# Context-managed connections, metrics, audit trail
# ============================================

import sqlite3
import json
import os
from datetime import datetime, timedelta
from contextlib import contextmanager
from core.config import DATA_DIR

DB_PATH = str(DATA_DIR / "downtime.db")


# ============ CONNECTION MANAGER ============

@contextmanager
def _get_conn():
    """Thread-safe context manager untuk SQLite connection.
    
    Setiap koneksi otomatis di-close setelah selesai.
    Timeout 10 detik untuk menghindari 'database is locked'.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    try:
        yield conn
    finally:
        conn.close()


def _init_db():
    """Inisialisasi schema database."""
    with _get_conn() as conn:
        c = conn.cursor()
        
        # Tabel utama: incidents
        c.execute('''
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT NOT NULL,
                kategori TEXT,
                tag TEXT,
                waktu_down TEXT NOT NULL,
                waktu_up TEXT,
                durasi_detik INTEGER,
                snapshot_text TEXT
            )
        ''')
        
        # Tabel metrics: time-series data
        c.execute('''
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                metadata TEXT
            )
        ''')
        
        # Tabel audit_log: command audit trail
        c.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                admin_id INTEGER,
                username TEXT,
                command TEXT,
                params TEXT,
                result TEXT
            )
        ''')
        
        # Migration: tambah kolom tag jika belum ada
        try:
            c.execute("SELECT tag FROM incidents LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE incidents ADD COLUMN tag TEXT")

        # Migration: penanda alasan close incident (normal / auto-close / manual)
        try:
            c.execute("SELECT closed_reason FROM incidents LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE incidents ADD COLUMN closed_reason TEXT")
            
        # Indexes
        c.execute('CREATE INDEX IF NOT EXISTS idx_incidents_host ON incidents(host)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_incidents_waktu_down ON incidents(waktu_down)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_incidents_waktu_up ON incidents(waktu_up)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_incidents_tag ON incidents(tag)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_metrics_time ON metrics(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_metrics_name_time ON metrics(metric_name, timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_audit_admin ON audit_log(admin_id)')
        
        conn.commit()


# Inisialisasi saat di-import (skip saat testing agar test bisa isolasi DB)
if not (os.environ.get('TESTING') or os.environ.get('TEST_MODE')):
    _init_db()


# ============ INCIDENT FUNCTIONS ============

def log_incident_down(host, kategori, snapshot_text="", tag=""):
    """Mencatat kejadian DOWN baru, mengembalikan ID baris."""
    with _get_conn() as conn:
        c = conn.cursor()
        waktu_down = datetime.now().isoformat()
        
        # Auto-tag berdasarkan kategori jika tidak disediakan
        if not tag:
            tag = _auto_tag(kategori, host)

        # Jangan buat incident open duplikat untuk host yang sama.
        c.execute(
            "SELECT id FROM incidents WHERE host = ? AND waktu_up IS NULL ORDER BY id DESC LIMIT 1",
            (host,)
        )
        existing = c.fetchone()
        if existing:
            return existing[0]
        
        c.execute(
            "INSERT INTO incidents (host, kategori, waktu_down, snapshot_text, tag) VALUES (?, ?, ?, ?, ?)",
            (host, kategori, waktu_down, snapshot_text, tag)
        )
        last_id = c.lastrowid
        conn.commit()
        return last_id


def log_incident_up(host, closed_reason="normal"):
    """Mencari record DOWN terakhir untuk host ini yang belum UP, lalu update.

    Return: jumlah incident terbuka yang berhasil ditutup.
    """
    with _get_conn() as conn:
        c = conn.cursor()
        
        c.execute(
            "SELECT id, waktu_down FROM incidents WHERE host = ? AND waktu_up IS NULL ORDER BY id DESC",
            (host,)
        )
        rows = c.fetchall()
        
        if rows:
            waktu_up_dt = datetime.now()
            waktu_up_iso = waktu_up_dt.isoformat()

            updated = 0
            for incident_id, waktu_down_iso in rows:
                try:
                    waktu_down_dt = datetime.fromisoformat(waktu_down_iso)
                    durasi_detik = int((waktu_up_dt - waktu_down_dt).total_seconds())
                except ValueError:
                    durasi_detik = 0

                c.execute(
                    "UPDATE incidents SET waktu_up = ?, durasi_detik = ?, closed_reason = ? WHERE id = ?",
                    (waktu_up_iso, durasi_detik, closed_reason or "normal", incident_id)
                )
                updated += 1
            conn.commit()
            return updated
    return 0


def get_recent_history(limit=10, tag_filter=None, offset=0):
    """Mengambil riwayat insiden terakhir, opsional filter by tag, dengan offset untuk pagination."""
    with _get_conn() as conn:
        c = conn.cursor()
        
        if tag_filter:
            c.execute(
                "SELECT host, kategori, waktu_down, waktu_up, durasi_detik, tag, closed_reason FROM incidents "
                "WHERE tag = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (tag_filter, limit, offset)
            )
        else:
            c.execute(
                "SELECT host, kategori, waktu_down, waktu_up, durasi_detik, tag, closed_reason FROM incidents "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
        rows = c.fetchall()
        
        results = []
        for r in rows:
            results.append({
                'host': r[0],
                'kategori': r[1],
                'waktu_down': r[2],
                'waktu_up': r[3],
                'durasi_detik': r[4],
                'tag': r[5] or '',
                'closed_reason': (r[6] if len(r) > 6 else None) or ''
            })
        return results


def count_all_incidents():
    """Return total jumlah insiden di database."""
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT count(*) FROM incidents")
        return c.fetchone()[0]


def close_stale_incidents(max_hours=24):
    """Close incidents yang sudah DOWN > max_hours tanpa recovery."""
    with _get_conn() as conn:
        c = conn.cursor()
        now_iso = datetime.now().isoformat()
        cutoff = (datetime.now() - timedelta(hours=max_hours)).isoformat()
        c.execute(
            "UPDATE incidents "
            "SET waktu_up = ?, "
            "    durasi_detik = CASE "
            "        WHEN waktu_down IS NOT NULL "
            "        THEN MAX(0, CAST((julianday(?) - julianday(waktu_down)) * 86400 AS INTEGER)) "
            "        ELSE 0 "
            "    END, "
            "    closed_reason = 'auto-close' "
            "WHERE waktu_up IS NULL AND waktu_down < ?",
            (now_iso, now_iso, cutoff)
        )
        count = c.rowcount
        conn.commit()
        return count


def dedupe_open_incidents(host=None, closed_reason="deduped-open"):
    """Sisakan hanya 1 incident open terbaru per host.

    Return: jumlah row open lama yang ditutup.
    """
    with _get_conn() as conn:
        c = conn.cursor()
        if host:
            c.execute(
                "SELECT id, waktu_down FROM incidents WHERE host = ? AND waktu_up IS NULL ORDER BY id DESC",
                (host,)
            )
        else:
            c.execute(
                "SELECT id, host, waktu_down FROM incidents WHERE waktu_up IS NULL ORDER BY host ASC, id DESC"
            )
        rows = c.fetchall()
        if not rows:
            return 0

        now_dt = datetime.now()
        now_iso = now_dt.isoformat()
        updated = 0

        if host:
            stale_rows = rows[1:]
            iterable = [(row[0], row[1]) for row in stale_rows]
        else:
            latest_per_host = set()
            iterable = []
            for incident_id, row_host, waktu_down_iso in rows:
                if row_host not in latest_per_host:
                    latest_per_host.add(row_host)
                    continue
                iterable.append((incident_id, waktu_down_iso))

        for incident_id, waktu_down_iso in iterable:
            try:
                waktu_down_dt = datetime.fromisoformat(waktu_down_iso)
                durasi_detik = int((now_dt - waktu_down_dt).total_seconds())
            except ValueError:
                durasi_detik = 0
            c.execute(
                "UPDATE incidents SET waktu_up = ?, durasi_detik = ?, closed_reason = ? WHERE id = ?",
                (now_iso, durasi_detik, closed_reason or "deduped-open", incident_id)
            )
            updated += 1

        conn.commit()
        return updated


def close_open_incidents_by_tag(tag, closed_reason="tag-closed"):
    """Tutup semua incident open untuk tag tertentu."""
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, waktu_down FROM incidents WHERE tag = ? AND waktu_up IS NULL ORDER BY id DESC",
            (tag,)
        )
        rows = c.fetchall()
        if not rows:
            return 0

        now_dt = datetime.now()
        now_iso = now_dt.isoformat()
        updated = 0
        for incident_id, waktu_down_iso in rows:
            try:
                waktu_down_dt = datetime.fromisoformat(waktu_down_iso)
                durasi_detik = int((now_dt - waktu_down_dt).total_seconds())
            except ValueError:
                durasi_detik = 0
            c.execute(
                "UPDATE incidents SET waktu_up = ?, durasi_detik = ?, closed_reason = ? WHERE id = ?",
                (now_iso, durasi_detik, closed_reason or "tag-closed", incident_id)
            )
            updated += 1

        conn.commit()
        return updated


def get_stats_today():
    """Mengambil statistik hari ini untuk daily report."""
    with _get_conn() as conn:
        c = conn.cursor()
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        c.execute(
            "SELECT count(*) FROM incidents WHERE waktu_down LIKE ?",
            (f"{today_str}%",)
        )
        count = c.fetchone()[0]
        return count


# Alias untuk dashboard
count_incidents_today = get_stats_today


def cleanup_old_data(days=60):
    """Menghapus data (yang sudah punya waktu_up) yang lebih tua dari batas hari yang ditentukan."""
    with _get_conn() as conn:
        c = conn.cursor()
        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_iso = cutoff_date.isoformat()
        
        c.execute(
            "DELETE FROM incidents WHERE waktu_down < ? AND waktu_up IS NOT NULL",
            (cutoff_iso,)
        )
        deleted_incidents = c.rowcount
        
        # Cleanup old metrics too (older than retention)
        c.execute(
            "DELETE FROM metrics WHERE timestamp < ?",
            (cutoff_iso,)
        )
        deleted_metrics = c.rowcount
        
        # Cleanup old audit logs (older than 90 days)
        audit_cutoff = (datetime.now() - timedelta(days=90)).isoformat()
        c.execute(
            "DELETE FROM audit_log WHERE timestamp < ?",
            (audit_cutoff,)
        )
        deleted_audit = c.rowcount
        
        conn.commit()
        return deleted_incidents + deleted_metrics + deleted_audit


def reset_all_data():
    """Hapus SEMUA data dari semua tabel (untuk fresh start).
    
    Returns: dict dengan jumlah record yang dihapus per tabel.
    """
    with _get_conn() as conn:
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM incidents")
        cnt_incidents = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM metrics")
        cnt_metrics = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM audit_log")
        cnt_audit = c.fetchone()[0]
        
        c.execute("DELETE FROM incidents")
        c.execute("DELETE FROM metrics")
        c.execute("DELETE FROM audit_log")
        
        conn.commit()
        return {
            'incidents': cnt_incidents,
            'metrics': cnt_metrics,
            'audit_log': cnt_audit,
            'total': cnt_incidents + cnt_metrics + cnt_audit
        }


def get_uptime_stats(days=7):
    """
    Menghitung statistik uptime per host berdasarkan data insiden.
    Return: dict { host: { uptime_pct, incident_count, total_downtime_sec, total_downtime_str } }
    """
    with _get_conn() as conn:
        c = conn.cursor()
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        
        c.execute(
            """SELECT host, COUNT(*) as cnt, 
                      SUM(CASE WHEN durasi_detik IS NOT NULL AND durasi_detik >= 0 THEN durasi_detik ELSE 0 END) as total_down
               FROM incidents 
               WHERE waktu_down >= ?
               GROUP BY host
               ORDER BY total_down DESC""",
            (cutoff_iso,)
        )
        rows = c.fetchall()
        
        if not rows:
            return {}
        
        total_seconds = days * 86400
        stats = {}
        for host, cnt, total_down in rows:
            total_down = total_down or 0
            uptime_sec = max(0, total_seconds - total_down)
            uptime_pct = (uptime_sec / total_seconds) * 100 if total_seconds > 0 else 100
            
            hours = total_down // 3600
            mins = (total_down % 3600) // 60
            secs = total_down % 60
            if hours > 0:
                dur_str = f"{hours}j {mins}m {secs}s"
            elif mins > 0:
                dur_str = f"{mins}m {secs}s"
            else:
                dur_str = f"{secs}s"
            
            stats[host] = {
                'uptime_pct': uptime_pct,
                'incident_count': cnt,
                'total_downtime_sec': total_down,
                'total_downtime_str': dur_str,
            }
        return stats


# ============ METRICS FUNCTIONS ============

def record_metric(metric_name, metric_value, metadata=None):
    """Simpan satu data point metrik."""
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO metrics (timestamp, metric_name, metric_value, metadata) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), metric_name, float(metric_value),
             json.dumps(metadata) if metadata else None)
        )
        conn.commit()


def record_metrics_batch(entries):
    """Simpan batch metrik sekaligus. entries: list of (name, value, metadata)."""
    with _get_conn() as conn:
        c = conn.cursor()
        ts = datetime.now().isoformat()
        for name, value, meta in entries:
            c.execute(
                "INSERT INTO metrics (timestamp, metric_name, metric_value, metadata) VALUES (?, ?, ?, ?)",
                (ts, name, float(value), json.dumps(meta) if meta else None)
            )
        conn.commit()


def get_metrics(metric_name, hours=24, limit=500):
    """Ambil data metrik untuk nama tertentu dalam rentang jam terakhir."""
    with _get_conn() as conn:
        c = conn.cursor()
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        # Ambil data TERBARU terlebih dahulu, lalu dibalik agar hasil akhir tetap ASC.
        # Ini mencegah dataset chart terpotong di data lama saat jumlah row sangat besar.
        c.execute(
            "SELECT timestamp, metric_value, metadata FROM metrics "
            "WHERE metric_name = ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
            (metric_name, cutoff, limit)
        )
        rows = list(reversed(c.fetchall()))
        return [
            {'timestamp': r[0], 'value': r[1], 'metadata': json.loads(r[2]) if r[2] else None}
            for r in rows
        ]


def get_metrics_summary(metric_name, days=7):
    """Statistik ringkasan metrik: avg, min, max, count."""
    with _get_conn() as conn:
        c = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        c.execute(
            "SELECT AVG(metric_value), MIN(metric_value), MAX(metric_value), COUNT(*) "
            "FROM metrics WHERE metric_name = ? AND timestamp >= ?",
            (metric_name, cutoff)
        )
        row = c.fetchone()
        if row and row[3] > 0:
            return {
                'avg': round(row[0], 2),
                'min': round(row[1], 2),
                'max': round(row[2], 2),
                'count': row[3],
            }
        return None


# ============ AUDIT LOG FUNCTIONS ============

def audit_log(admin_id, username, command, params="", result="berhasil"):
    """Mencatat aktivitas command ke audit trail database."""
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO audit_log (timestamp, admin_id, username, command, params, result) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), admin_id, username, command, params, result)
        )
        conn.commit()


def get_audit_log(limit=20, admin_id=None):
    """Ambil audit trail terbaru, opsional filter admin."""
    with _get_conn() as conn:
        c = conn.cursor()
        if admin_id is not None:
            c.execute(
                "SELECT timestamp, admin_id, username, command, params, result "
                "FROM audit_log WHERE admin_id = ? ORDER BY id DESC LIMIT ?",
                (admin_id, limit)
            )
        else:
            c.execute(
                "SELECT timestamp, admin_id, username, command, params, result "
                "FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,)
            )
        rows = c.fetchall()
        return [
            {
                'timestamp': r[0], 'admin_id': r[1], 'username': r[2],
                'command': r[3], 'params': r[4], 'result': r[5]
            }
            for r in rows
        ]


# ============ REPORT FUNCTIONS ============

def get_report(days=7, tag_filter=None):
    """Generate laporan ringkasan untuk periode tertentu.
    
    Return: dict dengan total_incidents, mttr, hosts, per_tag stats.
    """
    with _get_conn() as conn:
        c = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        # Base query
        if tag_filter:
            where_clause = "WHERE waktu_down >= ? AND tag = ?"
            params_count = (cutoff, tag_filter)
            params_detail = (cutoff, tag_filter)
        else:
            where_clause = "WHERE waktu_down >= ?"
            params_count = (cutoff,)
            params_detail = (cutoff,)
        
        # Total incidents
        c.execute(f"SELECT COUNT(*) FROM incidents {where_clause}", params_count)
        total = c.fetchone()[0]
        
        # MTTR (Mean Time To Recovery)
        c.execute(
            f"SELECT AVG(durasi_detik) FROM incidents {where_clause} "
            f"AND durasi_detik IS NOT NULL AND durasi_detik >= 0",
            params_detail
        )
        avg_recovery = c.fetchone()[0] or 0
        
        # Per-host summary
        c.execute(
            f"SELECT host, COUNT(*) as cnt, "
            f"SUM(CASE WHEN durasi_detik IS NOT NULL AND durasi_detik >= 0 THEN durasi_detik ELSE 0 END) as total_down, "
            f"AVG(CASE WHEN durasi_detik IS NOT NULL AND durasi_detik >= 0 THEN durasi_detik END) as avg_down "
            f"FROM incidents {where_clause} GROUP BY host ORDER BY cnt DESC",
            params_detail
        )
        host_rows = c.fetchall()
        
        # Per-tag breakdown
        c.execute(
            f"SELECT COALESCE(tag, 'untagged') as t, COUNT(*) FROM incidents {where_clause} GROUP BY t ORDER BY COUNT(*) DESC",
            params_detail
        )
        tag_rows = c.fetchall()
        
        # Format
        hosts_data = []
        for h in host_rows:
            hosts_data.append({
                'host': h[0], 'count': h[1],
                'total_down_sec': h[2] or 0,
                'avg_down_sec': round(h[3]) if h[3] else 0
            })
        
        tags_data = [{'tag': t[0], 'count': t[1]} for t in tag_rows]
        
        return {
            'period_days': days,
            'total_incidents': total,
            'mttr_seconds': round(avg_recovery),
            'hosts': hosts_data,
            'tags': tags_data,
        }


# ============ HELPERS ============

def _auto_tag(kategori, host):
    """Auto-generate tag berdasarkan kategori dan host."""
    if not kategori:
        return ""
    kat_lower = kategori.lower()
    if "core down" in kat_lower:
        return "core"
    elif "critical device" in kat_lower:
        return "critical"
    elif "wan" in kat_lower:
        return "wan"
    elif "internet" in kat_lower or "upstream" in kat_lower:
        return "internet"
    elif "server" in kat_lower:
        return "server"
    elif "wifi" in kat_lower or "ap" in kat_lower:
        return "wifi"
    elif "ip conflict" in kat_lower or "dhcp" in kat_lower:
        return "dhcp"
    elif "dns" in host.lower():
        return "dns"
    return "other"


# W4 FIX: _format_duration() dihapus — dead code (duplikat logika yang ada di get_uptime_stats)
