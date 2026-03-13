# 🔬 MIKRO_WATCHER — Laporan Analisis Mendalam Codebase

> **Tanggal**: 2026-03-13 | **Cakupan**: Seluruh source code (~15.000 baris, 40+ file Python)
> **Metode**: Pembacaan langsung setiap file, bukan spekulasi

---

## 📐 Arsitektur Sistem

**Dual-Process Architecture**: Bot dan Monitor berjalan sebagai 2 proses PM2 terpisah, berkomunikasi via file JSON IPC (`pending_acks.json`, `ack_events.json`, `alert_gate.json`, `state.json`).

```
┌─────────────────────────────┐     ┌─────────────────────────────┐
│  Proses 1: MIKRO_WATCHER    │     │  Proses 2: MIKRO_MONITOR    │
│  (bot.py)                   │     │  (run_monitor.py)           │
│                             │     │                             │
│  Telegram Bot               │     │  Monitor Orchestrator       │
│  ├─ Handlers (9 file)       │     │  ├─ Tasks (system/log/dhcp) │
│  ├─ Services (chart/config) │     │  ├─ Checks (cpu/ram/vpn)    │
│  └─ Core (config/db/log)    │     │  ├─ Netwatch (ping/tcp/dns) │
│                             │     │  └─ Alerts (escalation/ack) │
└──────────────┬──────────────┘     └──────────────┬──────────────┘
               │                                   │
               └──────────┬───────────────────────-┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
     ┌────▼────┐   ┌──────▼──────┐  ┌─────▼─────┐
     │ SQLite  │   │ IPC Files   │  │ MikroTik  │
     │ DB      │   │ (JSON)      │  │ RouterOS  │
     └─────────┘   └─────────────┘  └───────────┘
```

### Statistik Codebase

| Komponen | File | ~Baris | Fungsi |
|----------|------|--------|--------|
| `bot.py` (Entry) | 1 | 569 | Registrasi handler, scheduler, error handler |
| `core/` | 7 | ~1.900 | Config, DB, logging, classification, backup, guard |
| `mikrotik/` | 11 | ~2.500 | Koneksi pool, system, network, scan, tools, VPN, DNS, firewall, queue, scheduler |
| `monitor/` | 5 | ~2.600 | Alerts, checks, tasks, netwatch, orchestrator |
| `handlers/` | 9 | ~4.100 | UI commands: general, network, charts, report, alert, tools, queue |
| `services/` | 3 | ~820 | Chart generation, config manager, runtime reset |
| **Total** | **~40** | **~15.000** | |

---

## ✅ Kekuatan Arsitektural

### 1. Thread-Safe Connection Pool (`mikrotik/connection.py`)
- **Thread-local storage** (`threading.local()`) memastikan setiap thread mendapat koneksi API sendiri
- **Auto-reconnect** dengan backoff eksponensial (max 5 menit)
- **Health check** method dan `connection_diagnostics()` untuk observability
- `reset_all()` untuk force-reconnect semua thread

### 2. Cross-Process IPC yang Robust (`monitor/alerts.py`)
- Lock file berbasis `os.O_CREAT | os.O_EXCL` (atomic create)
- Stale lock detection via timestamp metadata
- Atomic write via `os.replace()` (rename atomik)
- Explicit ACK event queue (`ack_events.json`) mencegah race condition inference

### 3. Anti-Flapping Recovery (`monitor/netwatch.py`)
- Host DOWN memerlukan `PING_FAIL_THRESHOLD` kegagalan berturut-turut
- Recovery memerlukan `RECOVERY_CONFIRM_COUNT` sukses + `RECOVERY_MIN_UP_SECONDS` stabil
- **Critical devices** punya threshold terpisah (`CRITICAL_RECOVERY_*`) yang lebih ketat

### 4. Alert Severity System dengan Escalation (`monitor/alerts.py`)
- 3 tingkat: CRITICAL, WARNING, INFO
- Escalation otomatis untuk alert belum di-ACK (max 3x)
- Digest batching untuk WARNING agar tidak spam
- Mute global untuk maintenance window
- Alert gate (require `/start`) sebagai safety startup

### 5. Runtime Config Tanpa Restart (`services/config_manager.py`)
- 30+ parameter bisa diubah via bot (CPU/RAM threshold, interval, dll)
- Whitelist validasi (type, min, max) mencegah nilai invalid
- Cross-validation (WARN ≤ CRIT untuk Top BW)
- Audit trail di database untuk setiap perubahan

### 6. Sensitive Data Redaction (`core/logging_setup.py`)
- Custom `SensitiveDataFilter` menyaring TOKEN, PASSWORD, API KEY dari log
- Regex-based replacement ke `***REDACTED***`

### 7. Comprehensive Monitoring Coverage
- **System**: CPU, RAM, Disk, Firmware, Uptime anomaly
- **Network**: Interface up/down, VPN tunnel, DHCP pool, ARP conflict
- **Security**: Login brute-force auto-block, router log forwarding
- **Traffic**: Per-interface bandwidth, per-host top consumer, traffic leak detection
- **Netwatch**: Multi-host ICMP, TCP service check, DNS resolve check, klasifikasi root-cause

---

## 🔴 Temuan Kritis (High Severity)

### K1. Race Condition pada SQLite Multi-Process Write
**File**: `core/database.py`

Bot dan Monitor **menggunakan database SQLite yang sama secara paralel** dari 2 proses OS berbeda. SQLite dalam mode default (`journal_mode=DELETE`) sangat rentan `SQLITE_BUSY` saat concurrent write.

```python
# database.py - kedua proses menulis tanpa koordinasi
def _get_conn():
    conn = sqlite3.connect(str(DB_FILE), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")  # ← hanya di-set per koneksi baru
```

**Masalah**: `PRAGMA journal_mode=WAL` dieksekusi setiap kali koneksi dibuat, tapi **tidak persisten** jika proses lain sudah membuka DB dalam mode DELETE. WAL mode hanya efektif jika **semua** koneksi ke file tersebut menggunakan WAL.

> ⚠️ **CAUTION**: Pada load tinggi, `record_metrics_batch()` dari Monitor bisa konflik dengan `audit_log()` dari Bot, menghasilkan `sqlite3.OperationalError: database is locked`.

**Rekomendasi**: Pindah ke WAL mode persisten dengan file-level locking, atau gunakan dedicated DB writer thread/process.

---

### K2. Brute-Force Auto-Block Bisa Self-Lock Bot
**File**: `monitor/tasks.py` L689-739

Jika `BOT_IP` di `.env` **kosong atau salah**, dan IP bot terdeteksi sebagai login failure source (misalnya karena salah password):

```python
# Guardrail hanya efektif jika BOT_IP benar
if ip_part in trusted_autoblock_ips:
    bruteforce_tracker.pop(ip_part, None)
```

Ada fallback `_get_local_ipv4_set()` tapi hanya membaca local interface — **tidak menjamin deteksi IP NAT/bridge** yang terlihat oleh router.

> ⚠️ **WARNING**: Jika bot login gagal ≥5x (karena typo password saat deploy baru), bot bisa **memblokir IP-nya sendiri** di firewall router, menyebabkan total lockout.

**Rekomendasi**: Tambahkan `MIKROTIK_IP` ke trusted list (sudah ada), dan tambahkan guardrail: jangan auto-block IP yang sedang terkoneksi aktif di router API.

---

### K3. Monitor State File Tidak Atomic pada Windows
**File**: `monitor/checks.py` L58-77

```python
def _save_state():
    tmp_path = str(_STATE_FILE) + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(serializable, f)
    import os
    os.replace(tmp_path, str(_STATE_FILE))
```

`os.replace()` di Windows **bisa gagal** jika file target sedang dibuka oleh proses lain (misalnya antivirus scanning). Tidak ada error handling jika `os.replace()` gagal — state hilang.

**Rekomendasi**: Wrap dalam try/except dan retain `.tmp` file sebagai fallback jika replace gagal.

---

## 🟠 Temuan Penting (Medium Severity)

### M1. Connection Pool Backoff Timer Tidak Per-Thread
**File**: `mikrotik/connection.py`

```python
_backoff_until = 0.0  # Global — shared antar semua thread
```

Ketika satu thread memicu backoff, **semua thread** ikut terpause. Ini bisa memperlambat recovery jika hanya satu koneksi yang bermasalah.

---

### M2. Memory Leak Potensial di `_top_bw_host_state`
**File**: `monitor/tasks.py` L368

```python
_top_bw_host_state = {}  # Tidak ada cap ukuran
```

Jika jaringan memiliki banyak queue yang berputar (nama berubah-ubah), dict ini akan terus bertumbuh. Pruning hanya dilakukan untuk host tanpa `last_level` yang idle > 30 menit — tapi host _dengan_ `last_level` tidak pernah di-prune.

---

### M3. `_seen_set` di Log Monitor Bisa Drift
**File**: `monitor/tasks.py` L596-614

```python
_LOG_CACHE_MAX = 200
_seen_deque = deque(maxlen=_LOG_CACHE_MAX)
_seen_set = set()
```

`_seen_deque` memiliki maxlen 200, tapi `_seen_set` **tidak pernah dicap**. Eviction dari deque menghapus 1 item dari set, tapi jika ada hash collision atau timing issue, set dan deque bisa desync.

---

### M4. Chart `generate_cpu_chart` Division by Zero Risk
**File**: `services/chart_service.py` L126

```python
summary = database.get_metrics_summary('cpu_usage', days=hours // 24 or 1)
```

Jika `hours = 1` → `1 // 24 = 0` → `0 or 1 = 1` → aman. Tapi logika `hours // 24 or 1` tidak intuitif dan bisa membingungkan maintenance.

---

### M5. `block_ip` Dipanggil dari async tanpa timeout
**File**: `monitor/tasks.py` L707

```python
await asyncio.to_thread(block_ip, ip_part, f"Auto Blocked by Bot (Bruteforce)")
```

Tidak ada `with_timeout()` wrapper pada `block_ip`. Jika router API hang saat menambahkan firewall rule, ini bisa memblokir log monitor task selamanya.

---

### M6. `_last_uptime_seconds` Tidak Persisten
**File**: `monitor/checks.py` L89

```python
_last_uptime_seconds = None
```

Variabel ini **hilang saat monitor restart**. Setiap restart monitor akan melewatkan deteksi restart pertama router.

---

## 🟡 Temuan Minor (Low Severity)

### L1. Hardcoded Interface Detection di `cmd_status`
**File**: `handlers/general.py` L628-636

```python
indibiz = next((i for i in interfaces if 'indibiz' in i['name'].lower() or 'ether1' in ...), None)
local = next((i for i in interfaces if 'local' in i['name'].lower() or 'ether2' in ...), None)
```

Nama interface di-hardcode. Jika nama interface berbeda, info ini tidak muncul di status.

---

### L2. Duplikasi Kode di `daily_report` dan `cmd_status`
**File**: `handlers/jobs.py` vs `handlers/general.py`

Kedua fungsi memuat logika **nyaris identik** (~150 baris) untuk mengambil dan memformat system info, interfaces, DHCP, sensor, dll.

---

### L3. `_CHART_MENU_TEXT` Digenerate Saat Import
**File**: `handlers/charts.py` L57

Timestamp di-freeze saat module di-import → menampilkan waktu stale jika bot long-running.

---

### L4. `import os` di Dalam Fungsi
**File**: `monitor/checks.py` L74 — seharusnya di top-level module.

---

### L5. Voltage Display Logic
**File**: `handlers/general.py` L617-618

```python
if v_val > 100: v_val = v_val / 10
```

Asumsi voltage > 100 = deci-volt. Fragile untuk model yang melaporkan mili-volt.

---

## 📊 Alur Data & Fitur

### Monitoring Loop (6 Concurrent Tasks)

| # | Task | Interval | Fungsi |
|---|------|----------|--------|
| 1 | `task_monitor_system` | 5 menit | CPU/RAM/Disk/Interface/VPN/Firmware/Traffic alert |
| 2 | `task_monitor_traffic` | 60 detik | Record traffic metrics per-interface ke DB |
| 3 | `task_monitor_logs` | 30 detik | Forward router log + brute-force detection |
| 4 | `task_monitor_netwatch` | 15 detik | Ping/TCP/DNS multi-host + classification |
| 5 | `task_monitor_dhcp_arp` | 5 menit | DHCP pool + ARP MAC anomaly |
| 6 | `task_monitor_alert_maintenance` | 20 detik | Escalation loop + digest batching |

### Telegram Bot Commands (28 Commands)

| Kategori | Commands |
|----------|----------|
| **Monitor** | `/start`, `/status`, `/history`, `/uptime`, `/audit`, `/report`, `/chart` |
| **Network** | `/interface`, `/traffic`, `/scan`, `/freeip`, `/dhcp`, `/ping`, `/dns` |
| **Bandwidth** | `/bandwidth`, `/queue` |
| **Security** | `/firewall`, `/vpn` |
| **System** | `/mute`, `/unmute`, `/ack`, `/log`, `/mtlog`, `/backup`, `/reboot` |
| **Tools** | `/wol`, `/schedule`, `/config`, Reset Data (button) |

### Security Features

| Feature | Implementasi |
|---------|-------------|
| Admin-only access | Multi-admin via `ADMIN_IDS` list |
| Rate limiting | Per-user per-minute (`RateLimiter` class) |
| Log redaction | Token/password filtered dari log files |
| Brute-force protection | Auto-block IP setelah N login failures |
| Reboot cooldown | Configurable delay antara reboot commands |
| Mute/Alert gate | Maintenance window + require-start safety |

---

## 🔧 Dependency & Deployment

### Dependencies (`requirements.txt`)

| Package | Versi | Fungsi |
|---------|-------|--------|
| `python-telegram-bot[job-queue]` | ≥22.6, <23 | Telegram Bot API + job scheduler |
| `librouteros` | ≥4.0.0, <5 | MikroTik RouterOS API client |
| `python-dotenv` | ≥1.0.0, <2 | Load `.env` configuration |
| `matplotlib` | ≥3.10.0, <3.11 | Chart generation (CPU/RAM/Traffic/DHCP) |
| `pytest` / `pytest-asyncio` | Testing | Unit test framework |

### Deployment (`ecosystem.config.js`)

- **PM2** process manager dengan 2 proses: `MIKRO_WATCHER` (bot) + `MIKRO_MONITOR`
- Auto-restart dengan exponential backoff (100ms start)
- Memory limit: Bot 200MB, Monitor 150MB
- Windows-compatible (`exec_mode: "fork"`, `windowsHide: true`)

---

## 📝 Ringkasan Rekomendasi Prioritas

| Prioritas | Item | Effort |
|-----------|------|--------|
| 🔴 P1 | SQLite WAL mode consistency antar proses | Medium |
| 🔴 P1 | Guardrail auto-block terhadap IP bot sendiri | Low |
| 🟠 P2 | Timeout wrapper pada `block_ip` call | Low |
| 🟠 P2 | Cap memory `_top_bw_host_state` | Low |
| 🟠 P2 | Atomic file write error handling di Windows | Low |
| 🟡 P3 | Refactor duplikasi `daily_report` vs `cmd_status` | Medium |
| 🟡 P3 | Konfigurasi nama interface via `.env` | Low |
| 🟡 P3 | Import `os` ke top-level | Trivial |

---

> **Kesimpulan**: MIKRO_WATCHER adalah bot monitoring MikroTik yang **mature dan well-engineered** dengan arsitektur dual-process, alert escalation, anti-flapping, dan runtime configuration. Temuan kritis terbatas pada edge-case SQLite concurrency dan self-lock scenario yang bisa dimitigasi dengan perubahan kecil. Secara keseluruhan, codebase ini menunjukkan iterasi perbaikan bertahap yang konsisten dan production-ready untuk deployment single-router.
