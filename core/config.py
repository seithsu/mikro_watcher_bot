# ============================================
# CONFIG - Konfigurasi Bot dari .env
# ============================================

BOT_VERSION = "2.3.0"

from dotenv import load_dotenv, dotenv_values
import os
from pathlib import Path

# Load file .env
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# ============ DATA DIRECTORY ============
DATA_DIR = Path('.') / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============ TELEGRAM ============

TOKEN = os.getenv("TOKEN", "").strip()
TELEGRAM_CONNECT_TIMEOUT = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "10").strip())
TELEGRAM_READ_TIMEOUT = float(os.getenv("TELEGRAM_READ_TIMEOUT", "20").strip())
TELEGRAM_WRITE_TIMEOUT = float(os.getenv("TELEGRAM_WRITE_TIMEOUT", "20").strip())
TELEGRAM_POOL_TIMEOUT = float(os.getenv("TELEGRAM_POOL_TIMEOUT", "10").strip())
TELEGRAM_GET_UPDATES_READ_TIMEOUT = float(os.getenv("TELEGRAM_GET_UPDATES_READ_TIMEOUT", "35").strip())
TELEGRAM_CONNECTION_POOL_SIZE = int(os.getenv("TELEGRAM_CONNECTION_POOL_SIZE", "32").strip())
TELEGRAM_NETWORK_LOG_WINDOW_SEC = int(os.getenv("TELEGRAM_NETWORK_LOG_WINDOW_SEC", "300").strip())
TELEGRAM_NETWORK_LOG_COOLDOWN_SEC = int(os.getenv("TELEGRAM_NETWORK_LOG_COOLDOWN_SEC", "120").strip())

# Multi-admin: support ADMIN_IDS (comma-separated) atau fallback ke CHAT_ID
_admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
_chat_id_raw = os.getenv("CHAT_ID", "0").strip()

try:
    if _admin_ids_raw:
        ADMIN_IDS = [int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip()]
    else:
        ADMIN_IDS = [int(_chat_id_raw)]
except ValueError:
    raise ValueError("ADMIN_IDS / CHAT_ID harus angka! Cek file .env")

# Hardening: ID admin harus angka positif.
ADMIN_IDS = [aid for aid in ADMIN_IDS if isinstance(aid, int) and aid > 0]

# CHAT_ID utama untuk notifikasi (admin pertama)
CHAT_ID = ADMIN_IDS[0] if ADMIN_IDS else 0


# ============ MIKROTIK ============

MIKROTIK_IP = os.getenv("MIKROTIK_IP", "").strip()
MIKROTIK_USER = os.getenv("MIKROTIK_USER", "").strip()
MIKROTIK_PASS = os.getenv("MIKROTIK_PASS", "").strip()
MIKROTIK_PORT = int(os.getenv("MIKROTIK_PORT", "8728").strip())
MIKROTIK_USE_SSL = os.getenv("MIKROTIK_USE_SSL", "False").strip().lower() in ['true', '1', 'yes']
MIKROTIK_TLS_VERIFY = os.getenv("MIKROTIK_TLS_VERIFY", "True").strip().lower() in ['true', '1', 'yes']
MIKROTIK_TLS_CA_FILE = os.getenv("MIKROTIK_TLS_CA_FILE", "").strip()
MIKROTIK_FTP_TLS = os.getenv("MIKROTIK_FTP_TLS", "True").strip().lower() in ['true', '1', 'yes']
MIKROTIK_FTP_ALLOW_INSECURE = os.getenv("MIKROTIK_FTP_ALLOW_INSECURE", "False").strip().lower() in ['true', '1', 'yes']
MIKROTIK_FTP_PORT = int(os.getenv("MIKROTIK_FTP_PORT", "21").strip())

# Connection tuning untuk skenario hot-swap/unstable link
MIKROTIK_MAX_CONNECTIONS = int(os.getenv("MIKROTIK_MAX_CONNECTIONS", "12").strip())
MIKROTIK_RECONNECT_BASE_BACKOFF = int(os.getenv("MIKROTIK_RECONNECT_BASE_BACKOFF", "1").strip())
MIKROTIK_RECONNECT_MAX_BACKOFF = int(os.getenv("MIKROTIK_RECONNECT_MAX_BACKOFF", "30").strip())
MIKROTIK_RESET_ALL_COOLDOWN_SEC = int(os.getenv("MIKROTIK_RESET_ALL_COOLDOWN_SEC", "15").strip())
ASYNC_THREAD_WORKERS = int(os.getenv("ASYNC_THREAD_WORKERS", "8").strip())
MIKROTIK_CONNECTION_MAX_AGE_SEC = int(os.getenv("MIKROTIK_CONNECTION_MAX_AGE_SEC", "0").strip())

# IP host yang menjalankan bot (untuk filter log, agar login bot tidak masuk alert)
BOT_IP = os.getenv("BOT_IP", "").strip()

# Nama institusi (tampil di report & status)
INSTITUTION_NAME = os.getenv("INSTITUTION_NAME", "RSIA Palaraya").strip()


# ============ MONITORING ============

# Interval cek monitor dalam detik (default 5 menit)
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "300").strip())

# Interval netwatch matrix monitor dalam detik.
NETWATCH_INTERVAL = int(os.getenv("NETWATCH_INTERVAL", "15").strip())

# Threshold alert
CPU_THRESHOLD = int(os.getenv("CPU_THRESHOLD", "80").strip())
RAM_THRESHOLD = int(os.getenv("RAM_THRESHOLD", "90").strip())

# Interface yang di-skip dari monitoring (comma-separated, kosongkan jika tidak ada)
_ignore_raw = os.getenv("MONITOR_IGNORE_IFACE", "").strip()
MONITOR_IGNORE_IFACE = set(x.strip() for x in _ignore_raw.split(",") if x.strip())

# Monitoring VPN tunnel bisa dimatikan total jika jaringan tidak memakai VPN.
MONITOR_VPN_ENABLED = os.getenv("MONITOR_VPN_ENABLED", "True").strip().lower() in ['true', '1', 'yes']
_vpn_ignore_raw = os.getenv("MONITOR_VPN_IGNORE_NAMES", "").strip()
MONITOR_VPN_IGNORE_NAMES = set(x.strip().lower() for x in _vpn_ignore_raw.split(",") if x.strip())

# Ambang batas indikator putus jaringan (Berapa kali ping gagal berturut-turut sebelum alert)
PING_FAIL_THRESHOLD = int(os.getenv("PING_FAIL_THRESHOLD", "3").strip())

# Jam kirim daily report (format 24h, default jam 7 pagi)
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "7").strip())

# Threshold Traffic Alert (Dalam Mbps). Akan dikonversi ke bytes di monitor.py
TRAFFIC_THRESHOLD_MBPS = int(os.getenv("TRAFFIC_THRESHOLD_MBPS", "100").strip())

# Threshold traffic per host untuk alert kebocoran (Mbps, 0 = nonaktif)
TRAFFIC_LEAK_THRESHOLD_MBPS = int(os.getenv("TRAFFIC_LEAK_THRESHOLD_MBPS", "50").strip())

# Daftar nama host/queue yang dikecualikan dari traffic leak alert (comma-separated)
_leak_whitelist_raw = os.getenv("TRAFFIC_LEAK_WHITELIST", "").strip()
TRAFFIC_LEAK_WHITELIST = [x.strip() for x in _leak_whitelist_raw.split(",") if x.strip()]

# Top bandwidth consumer alert engine (queue-based)
TOP_BW_ALERT_ENABLED = os.getenv("TOP_BW_ALERT_ENABLED", "True").strip().lower() in ['true', '1', 'yes']
TOP_BW_ALERT_TOP_N = int(os.getenv("TOP_BW_ALERT_TOP_N", "3").strip())
TOP_BW_ALERT_WARN_MBPS = int(os.getenv("TOP_BW_ALERT_WARN_MBPS", "50").strip())
TOP_BW_ALERT_CRIT_MBPS = int(os.getenv("TOP_BW_ALERT_CRIT_MBPS", "100").strip())
TOP_BW_ALERT_CONSECUTIVE_HITS = int(os.getenv("TOP_BW_ALERT_CONSECUTIVE_HITS", "3").strip())
TOP_BW_ALERT_RECOVERY_HITS = int(os.getenv("TOP_BW_ALERT_RECOVERY_HITS", "2").strip())
TOP_BW_ALERT_COOLDOWN_SEC = int(os.getenv("TOP_BW_ALERT_COOLDOWN_SEC", "900").strip())
TOP_BW_ALERT_MIN_TX_MBPS = int(os.getenv("TOP_BW_ALERT_MIN_TX_MBPS", "1").strip())
TOP_BW_ALERT_MIN_RX_MBPS = int(os.getenv("TOP_BW_ALERT_MIN_RX_MBPS", "1").strip())

# Threshold Disk Alert (dalam persen)
DISK_THRESHOLD = int(os.getenv("DISK_THRESHOLD", "85").strip())

# Jumlah paket ping (default 4)
PING_COUNT = int(os.getenv("PING_COUNT", "4").strip())

# Interval log monitor dalam detik (default 30)
MONITOR_LOG_INTERVAL = int(os.getenv("MONITOR_LOG_INTERVAL", "30").strip())
MONITOR_LOG_FETCH_LINES = int(os.getenv("MONITOR_LOG_FETCH_LINES", "100").strip())
NETWATCH_PING_CONCURRENCY = int(os.getenv("NETWATCH_PING_CONCURRENCY", "4").strip())
BRUTEFORCE_FAIL_THRESHOLD = int(os.getenv("BRUTEFORCE_FAIL_THRESHOLD", "5").strip())
API_ACCOUNT_DEDUP_WINDOW_SEC = int(os.getenv("API_ACCOUNT_DEDUP_WINDOW_SEC", "300").strip())
_api_skip_users_raw = os.getenv("API_ACCOUNT_SKIP_USERS", "").strip()
API_ACCOUNT_SKIP_USERS = [x.strip().lower() for x in _api_skip_users_raw.split(",") if x.strip()]
_auto_block_trusted_raw = os.getenv("AUTO_BLOCK_TRUSTED_IPS", "").strip()
AUTO_BLOCK_TRUSTED_IPS = [x.strip() for x in _auto_block_trusted_raw.split(",") if x.strip()]
_dns_check_raw = os.getenv("DNS_CHECK_DOMAIN", "google.com").strip()
DNS_CHECK_DOMAINS = [x.strip() for x in _dns_check_raw.split(",") if x.strip()]
if not DNS_CHECK_DOMAINS:
    DNS_CHECK_DOMAINS = ["google.com"]
DNS_CHECK_DOMAIN = DNS_CHECK_DOMAINS[0]

# Netwatch hosts lama (dijaga untuk kompatibilitas jika ada)
_netwatch_hosts_raw = os.getenv("NETWATCH_HOSTS", "").strip()
NETWATCH_HOSTS = [x.strip() for x in _netwatch_hosts_raw.split(",") if x.strip()]

# ============ ADVANCED MONITORING (RS LEVEL) ============
GW_WAN = os.getenv("GW_WAN", "192.168.1.1").strip()
GW_INET = os.getenv("GW_INET", "1.1.1.1").strip()

# Interface keyword matching untuk snapshot (WAN vs LAN error reporting)
# C1 FIX: strip() per item agar spasi di .env tidak merusak matching
WAN_IFACE_KEYWORDS = [kw.strip() for kw in os.getenv("WAN_IFACE_KEYWORDS", "indibiz,ether1,wan,sfp1").split(",") if kw.strip()]
LAN_IFACE_KEYWORDS = [kw.strip() for kw in os.getenv("LAN_IFACE_KEYWORDS", "local,ether2,bridge,lan").split(",") if kw.strip()]

# Recovery confirmation: berapa kali ping berhasil sebelum declare RECOVERY (anti-flapping)
RECOVERY_CONFIRM_COUNT = int(os.getenv("RECOVERY_CONFIRM_COUNT", "2").strip())
# Recovery hold time: host harus stabil UP selama N detik sebelum kirim RECOVERY.
# Mengurangi false-recovery saat link/device flapping.
RECOVERY_MIN_UP_SECONDS = int(os.getenv("RECOVERY_MIN_UP_SECONDS", "90").strip())
# Timeout seluruh siklus netwatch berturut-turut sebelum status monitor dianggap degraded.
NETWATCH_CYCLE_TIMEOUT_THRESHOLD = int(os.getenv("NETWATCH_CYCLE_TIMEOUT_THRESHOLD", "2").strip())
# Cooldown notifikasi degraded agar tidak spam.
NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC = int(os.getenv("NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC", "300").strip())
# Recovery khusus host critical agar tidak flapping saat device memang mati.
CRITICAL_RECOVERY_CONFIRM_COUNT = int(os.getenv("CRITICAL_RECOVERY_CONFIRM_COUNT", "3").strip())
CRITICAL_RECOVERY_MIN_UP_SECONDS = int(os.getenv("CRITICAL_RECOVERY_MIN_UP_SECONDS", "180").strip())

# Ping success ratio minimum agar host dianggap UP pada 1 siklus netwatch.
# Contoh default 0.5 dan PING_COUNT=4 -> minimal 2 reply.
try:
    NETWATCH_UP_MIN_SUCCESS_RATIO = float(os.getenv("NETWATCH_UP_MIN_SUCCESS_RATIO", "0.5").strip())
except (ValueError, TypeError):
    NETWATCH_UP_MIN_SUCCESS_RATIO = 0.5

# Deteksi Server & AP: Otomatis dari Simple Queue berdasarkan field 'comment'
# Di MikroTik Winbox/WebFig, set comment queue:
#   - comment = 'server'  → terdeteksi sebagai server yang dimonitor
#   - comment = 'ap'      → terdeteksi sebagai WiFi AP yang dimonitor
#   - comment kosong      → tidak dimonitor (client biasa)
#
# Fallback static (dipakai jika tidak ada queue ber-comment):
# Default kosong agar tidak memonitor host legacy tanpa konfigurasi eksplisit.
_servers_raw = os.getenv("SERVERS", "").strip()
SERVERS_FALLBACK = {}
for s in _servers_raw.split(","):
    if ":" in s:
        name, ip = s.split(":", 1)
        SERVERS_FALLBACK[name.strip()] = ip.strip()

_aps_raw = os.getenv("WIFI_APS", "").strip()
APS_FALLBACK = {}
for s in _aps_raw.split(","):
    if ":" in s:
        name, ip = s.split(":", 1)
        APS_FALLBACK[name.strip()] = ip.strip()

# Device penting (wajib dipantau):
# 1) Static mapping langsung name:ip (selalu dipantau)
_critical_devices_raw = os.getenv("CRITICAL_DEVICES", "").strip()
CRITICAL_DEVICES_FALLBACK = {}
for s in _critical_devices_raw.split(","):
    if ":" in s:
        name, ip = s.split(":", 1)
        CRITICAL_DEVICES_FALLBACK[name.strip()] = ip.strip()

# 2) Lookup otomatis berdasarkan hostname/comment DHCP lease.
_critical_names_raw = os.getenv("CRITICAL_DEVICE_NAMES", "").strip()
CRITICAL_DEVICE_NAMES = [x.strip() for x in _critical_names_raw.split(",") if x.strip()]

# Window monitor per perangkat penting.
# Format: NAMA_DEVICE=HH:MM-HH:MM (pisah koma untuk banyak device).
# Contoh:
# CRITICAL_DEVICE_WINDOWS=KOMP PENDAFTARAN POLI=07:00-17:00
def _parse_hhmm_to_minutes(value):
    try:
        text = str(value or "").strip()
        hh_str, mm_str = text.split(":", 1)
        hh = int(hh_str)
        mm = int(mm_str)
        if hh < 0 or hh > 23 or mm < 0 or mm > 59:
            return None
        return (hh * 60) + mm
    except Exception:
        return None


def _parse_critical_device_windows(raw_value):
    windows = {}
    for item in str(raw_value or "").split(","):
        entry = item.strip()
        if not entry or "=" not in entry:
            continue
        name, range_text = entry.rsplit("=", 1)
        if "-" not in range_text:
            continue
        start_text, end_text = range_text.split("-", 1)
        start_min = _parse_hhmm_to_minutes(start_text)
        end_min = _parse_hhmm_to_minutes(end_text)
        if start_min is None or end_min is None:
            continue
        name_clean = name.strip()
        if not name_clean:
            continue
        windows[name_clean] = (start_min, end_min)
    return windows


_critical_windows_raw = os.getenv("CRITICAL_DEVICE_WINDOWS", "").strip()
CRITICAL_DEVICE_WINDOWS = _parse_critical_device_windows(_critical_windows_raw)

# Default kosong agar TCP monitor hanya aktif jika memang didefinisikan.
_tcp_raw = os.getenv("TCP_SERVICES", "").strip()
TCP_SERVICES = []
if _tcp_raw:
    for s in _tcp_raw.split(","):
        parts = s.split(":")
        if len(parts) == 3:
            TCP_SERVICES.append({"name": parts[0].strip(), "ip": parts[1].strip(), "port": int(parts[2].strip())})

DHCP_POOL_SIZE = int(os.getenv("DHCP_POOL_SIZE", "60").strip())
DHCP_ALERT_THRESHOLD = int(os.getenv("DHCP_ALERT_THRESHOLD", "85").strip())

_macs_raw = os.getenv("CRITICAL_MACS", "").strip()
CRITICAL_MACS = {}
if _macs_raw:
    for m in _macs_raw.split(","):
        # Format: IP=MAC (gunakan = sebagai separator agar tidak konflik dengan : di MAC address)
        if "=" in m:
            parts = m.split("=", 1)
            CRITICAL_MACS[parts[0].strip()] = parts[1].strip().lower()
        elif ":" in m:
            # Backward compat: coba split hanya jika format IP:placeholder (tanpa MAC asli)
            parts = m.split(":", 1)
            CRITICAL_MACS[parts[0].strip()] = parts[1].strip().lower()

# Hari untuk auto-backup (english: monday, tuesday, dll)
AUTO_BACKUP_DAY = os.getenv("AUTO_BACKUP_DAY", "sunday").strip().lower()


# ============ RATE LIMIT ============

# Cooldown reboot dalam detik (default 5 menit)
REBOOT_COOLDOWN = int(os.getenv("REBOOT_COOLDOWN", "300").strip())

# Command rate limit: max request per menit per user
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20").strip())


# ============ ALERTING ============

# Escalation timeout (menit) - kirim ulang alert jika tidak di-ack
ALERT_ESCALATION_MINUTES = int(os.getenv("ALERT_ESCALATION_MINUTES", "15").strip())

# Digest threshold - batch alert jika lebih dari N alert dalam window
ALERT_DIGEST_THRESHOLD = int(os.getenv("ALERT_DIGEST_THRESHOLD", "5").strip())

# Digest window dalam detik (default 5 menit)
ALERT_DIGEST_WINDOW = int(os.getenv("ALERT_DIGEST_WINDOW", "300").strip())

# TTL lock IPC ACK lintas-proses (detik) agar lock stale bisa direclaim.
ALERT_IPC_LOCK_STALE_SEC = int(os.getenv("ALERT_IPC_LOCK_STALE_SEC", "15").strip())

# Jika true, monitor disarm saat boot dan mulai kirim alert setelah admin menjalankan /start.
ALERT_REQUIRE_START = os.getenv("ALERT_REQUIRE_START", "False").strip().lower() in ['true', '1', 'yes']

# Guardrail: batas critical tidak boleh di bawah warning.
if TOP_BW_ALERT_CRIT_MBPS < TOP_BW_ALERT_WARN_MBPS:
    TOP_BW_ALERT_CRIT_MBPS = TOP_BW_ALERT_WARN_MBPS


# ============ LOGGING ============

# Ukuran max log sebelum rotate (bytes, default 1MB)
LOG_MAX_SIZE = int(os.getenv("LOG_MAX_SIZE", str(1024 * 1024)).strip())

# Jumlah backup log yang disimpan
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "3").strip())


# ============ RANGE VALIDATION ============

def _assert_range(name, value, min_value, max_value):
    if value < min_value or value > max_value:
        raise ValueError(f"{name} di luar batas aman ({min_value}-{max_value}): {value}")


_assert_range("MIKROTIK_PORT", MIKROTIK_PORT, 1, 65535)
_assert_range("MIKROTIK_FTP_PORT", MIKROTIK_FTP_PORT, 1, 65535)
_assert_range("MIKROTIK_MAX_CONNECTIONS", MIKROTIK_MAX_CONNECTIONS, 1, 256)
_assert_range("MIKROTIK_RECONNECT_BASE_BACKOFF", MIKROTIK_RECONNECT_BASE_BACKOFF, 1, 300)
_assert_range("MIKROTIK_RECONNECT_MAX_BACKOFF", MIKROTIK_RECONNECT_MAX_BACKOFF, 1, 3600)
_assert_range("MIKROTIK_RESET_ALL_COOLDOWN_SEC", MIKROTIK_RESET_ALL_COOLDOWN_SEC, 5, 3600)
_assert_range("ASYNC_THREAD_WORKERS", ASYNC_THREAD_WORKERS, 2, 128)
_assert_range("MIKROTIK_CONNECTION_MAX_AGE_SEC", MIKROTIK_CONNECTION_MAX_AGE_SEC, 0, 86_400)
_assert_range("MONITOR_INTERVAL", MONITOR_INTERVAL, 10, 86400)
_assert_range("NETWATCH_INTERVAL", NETWATCH_INTERVAL, 5, 3600)
_assert_range("MONITOR_LOG_INTERVAL", MONITOR_LOG_INTERVAL, 5, 3600)
_assert_range("MONITOR_LOG_FETCH_LINES", MONITOR_LOG_FETCH_LINES, 20, 1000)
_assert_range("NETWATCH_PING_CONCURRENCY", NETWATCH_PING_CONCURRENCY, 1, 32)
_assert_range("BRUTEFORCE_FAIL_THRESHOLD", BRUTEFORCE_FAIL_THRESHOLD, 3, 20)
_assert_range("API_ACCOUNT_DEDUP_WINDOW_SEC", API_ACCOUNT_DEDUP_WINDOW_SEC, 30, 86_400)
_assert_range("CPU_THRESHOLD", CPU_THRESHOLD, 10, 100)
_assert_range("RAM_THRESHOLD", RAM_THRESHOLD, 10, 100)
_assert_range("DISK_THRESHOLD", DISK_THRESHOLD, 10, 100)
_assert_range("PING_FAIL_THRESHOLD", PING_FAIL_THRESHOLD, 1, 20)
_assert_range("RECOVERY_CONFIRM_COUNT", RECOVERY_CONFIRM_COUNT, 1, 20)
_assert_range("RECOVERY_MIN_UP_SECONDS", RECOVERY_MIN_UP_SECONDS, 0, 3600)
_assert_range("NETWATCH_CYCLE_TIMEOUT_THRESHOLD", NETWATCH_CYCLE_TIMEOUT_THRESHOLD, 1, 20)
_assert_range("NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC", NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC, 30, 86_400)
_assert_range("CRITICAL_RECOVERY_CONFIRM_COUNT", CRITICAL_RECOVERY_CONFIRM_COUNT, 1, 20)
_assert_range("CRITICAL_RECOVERY_MIN_UP_SECONDS", CRITICAL_RECOVERY_MIN_UP_SECONDS, 0, 3600)
_assert_range("PING_COUNT", PING_COUNT, 1, 20)
if NETWATCH_UP_MIN_SUCCESS_RATIO < 0.1 or NETWATCH_UP_MIN_SUCCESS_RATIO > 1.0:
    raise ValueError(
        f"NETWATCH_UP_MIN_SUCCESS_RATIO di luar batas aman (0.1-1.0): {NETWATCH_UP_MIN_SUCCESS_RATIO}"
    )
_assert_range("DAILY_REPORT_HOUR", DAILY_REPORT_HOUR, 0, 23)
_assert_range("TRAFFIC_THRESHOLD_MBPS", TRAFFIC_THRESHOLD_MBPS, 0, 1_000_000)
_assert_range("TRAFFIC_LEAK_THRESHOLD_MBPS", TRAFFIC_LEAK_THRESHOLD_MBPS, 0, 1_000_000)
_assert_range("TOP_BW_ALERT_TOP_N", TOP_BW_ALERT_TOP_N, 1, 50)
_assert_range("TOP_BW_ALERT_WARN_MBPS", TOP_BW_ALERT_WARN_MBPS, 1, 1_000_000)
_assert_range("TOP_BW_ALERT_CRIT_MBPS", TOP_BW_ALERT_CRIT_MBPS, 1, 1_000_000)
_assert_range("TOP_BW_ALERT_CONSECUTIVE_HITS", TOP_BW_ALERT_CONSECUTIVE_HITS, 1, 20)
_assert_range("TOP_BW_ALERT_RECOVERY_HITS", TOP_BW_ALERT_RECOVERY_HITS, 1, 20)
_assert_range("TOP_BW_ALERT_COOLDOWN_SEC", TOP_BW_ALERT_COOLDOWN_SEC, 0, 86_400)
_assert_range("TOP_BW_ALERT_MIN_TX_MBPS", TOP_BW_ALERT_MIN_TX_MBPS, 0, 1_000_000)
_assert_range("TOP_BW_ALERT_MIN_RX_MBPS", TOP_BW_ALERT_MIN_RX_MBPS, 0, 1_000_000)
_assert_range("DHCP_POOL_SIZE", DHCP_POOL_SIZE, 1, 1_000_000)
_assert_range("DHCP_ALERT_THRESHOLD", DHCP_ALERT_THRESHOLD, 10, 100)
_assert_range("REBOOT_COOLDOWN", REBOOT_COOLDOWN, 1, 86_400)
_assert_range("RATE_LIMIT_PER_MINUTE", RATE_LIMIT_PER_MINUTE, 1, 10_000)
_assert_range("ALERT_ESCALATION_MINUTES", ALERT_ESCALATION_MINUTES, 1, 10_000)
_assert_range("ALERT_DIGEST_THRESHOLD", ALERT_DIGEST_THRESHOLD, 1, 10_000)
_assert_range("ALERT_DIGEST_WINDOW", ALERT_DIGEST_WINDOW, 10, 86_400)
_assert_range("ALERT_IPC_LOCK_STALE_SEC", ALERT_IPC_LOCK_STALE_SEC, 3, 600)
_assert_range("TELEGRAM_CONNECT_TIMEOUT", TELEGRAM_CONNECT_TIMEOUT, 1, 120)
_assert_range("TELEGRAM_READ_TIMEOUT", TELEGRAM_READ_TIMEOUT, 1, 300)
_assert_range("TELEGRAM_WRITE_TIMEOUT", TELEGRAM_WRITE_TIMEOUT, 1, 300)
_assert_range("TELEGRAM_POOL_TIMEOUT", TELEGRAM_POOL_TIMEOUT, 1, 120)
_assert_range("TELEGRAM_GET_UPDATES_READ_TIMEOUT", TELEGRAM_GET_UPDATES_READ_TIMEOUT, 1, 300)
_assert_range("TELEGRAM_CONNECTION_POOL_SIZE", TELEGRAM_CONNECTION_POOL_SIZE, 1, 512)
_assert_range("TELEGRAM_NETWORK_LOG_WINDOW_SEC", TELEGRAM_NETWORK_LOG_WINDOW_SEC, 60, 86_400)
_assert_range("TELEGRAM_NETWORK_LOG_COOLDOWN_SEC", TELEGRAM_NETWORK_LOG_COOLDOWN_SEC, 30, 86_400)
_assert_range("LOG_MAX_SIZE", LOG_MAX_SIZE, 1024, 1024 * 1024 * 1024)
_assert_range("LOG_BACKUP_COUNT", LOG_BACKUP_COUNT, 1, 100)


# ============ VALIDASI ============

_missing = []
if not TOKEN: _missing.append("TOKEN")
if not ADMIN_IDS: _missing.append("CHAT_ID atau ADMIN_IDS")
if not MIKROTIK_IP: _missing.append("MIKROTIK_IP")
if not MIKROTIK_USER: _missing.append("MIKROTIK_USER")
if not MIKROTIK_PASS: _missing.append("MIKROTIK_PASS")

if _missing:
    raise ValueError(f"Config tidak lengkap! Variabel kosong: {', '.join(_missing)}. Cek file .env")


# ============ RUNTIME CONFIG OVERRIDE ============
# Load runtime config overrides (dari /config command bot)

import time as _time
import json as _json

_RUNTIME_CONFIG_FILE = DATA_DIR / "runtime_config.json"
_OVERRIDABLE_KEYS = {
    'CPU_THRESHOLD', 'RAM_THRESHOLD', 'DISK_THRESHOLD',
    'MONITOR_INTERVAL', 'NETWATCH_INTERVAL', 'MONITOR_LOG_INTERVAL', 'MONITOR_LOG_FETCH_LINES',
    'NETWATCH_PING_CONCURRENCY', 'API_ACCOUNT_DEDUP_WINDOW_SEC',
    'PING_COUNT',
    'PING_FAIL_THRESHOLD', 'RECOVERY_CONFIRM_COUNT', 'RECOVERY_MIN_UP_SECONDS',
    'NETWATCH_CYCLE_TIMEOUT_THRESHOLD', 'NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC',
    'CRITICAL_RECOVERY_CONFIRM_COUNT', 'CRITICAL_RECOVERY_MIN_UP_SECONDS',
    'NETWATCH_UP_MIN_SUCCESS_RATIO',
    'RATE_LIMIT_PER_MINUTE',
    'DHCP_ALERT_THRESHOLD', 'TRAFFIC_THRESHOLD_MBPS',
    'MONITOR_VPN_ENABLED',
    'TOP_BW_ALERT_ENABLED',
    'TOP_BW_ALERT_TOP_N', 'TOP_BW_ALERT_WARN_MBPS', 'TOP_BW_ALERT_CRIT_MBPS',
    'TOP_BW_ALERT_CONSECUTIVE_HITS', 'TOP_BW_ALERT_RECOVERY_HITS',
    'TOP_BW_ALERT_COOLDOWN_SEC', 'TOP_BW_ALERT_MIN_TX_MBPS', 'TOP_BW_ALERT_MIN_RX_MBPS',
    'DAILY_REPORT_HOUR', 'ALERT_ESCALATION_MINUTES',
    'ALERT_DIGEST_THRESHOLD', 'ALERT_DIGEST_WINDOW',
    'TRAFFIC_LEAK_THRESHOLD_MBPS', 'ALERT_REQUIRE_START',
    'MIKROTIK_RESET_ALL_COOLDOWN_SEC',
}

_OVERRIDABLE_SCHEMA = {
    'CPU_THRESHOLD': (int, 10, 100),
    'RAM_THRESHOLD': (int, 10, 100),
    'DISK_THRESHOLD': (int, 10, 100),
    'MONITOR_INTERVAL': (int, 10, 86400),
    'NETWATCH_INTERVAL': (int, 5, 3600),
    'MONITOR_LOG_INTERVAL': (int, 5, 3600),
    'MONITOR_LOG_FETCH_LINES': (int, 20, 1000),
    'NETWATCH_PING_CONCURRENCY': (int, 1, 32),
    'API_ACCOUNT_DEDUP_WINDOW_SEC': (int, 30, 86_400),
    'PING_COUNT': (int, 1, 20),
    'PING_FAIL_THRESHOLD': (int, 1, 20),
    'RECOVERY_CONFIRM_COUNT': (int, 1, 20),
    'RECOVERY_MIN_UP_SECONDS': (int, 0, 3600),
    'NETWATCH_CYCLE_TIMEOUT_THRESHOLD': (int, 1, 20),
    'NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC': (int, 30, 86_400),
    'CRITICAL_RECOVERY_CONFIRM_COUNT': (int, 1, 20),
    'CRITICAL_RECOVERY_MIN_UP_SECONDS': (int, 0, 3600),
    'NETWATCH_UP_MIN_SUCCESS_RATIO': (float, 0.1, 1.0),
    'RATE_LIMIT_PER_MINUTE': (int, 1, 10000),
    'DHCP_ALERT_THRESHOLD': (int, 10, 100),
    'TRAFFIC_THRESHOLD_MBPS': (int, 0, 1_000_000),
    'MONITOR_VPN_ENABLED': (bool, None, None),
    'TOP_BW_ALERT_ENABLED': (bool, None, None),
    'TOP_BW_ALERT_TOP_N': (int, 1, 50),
    'TOP_BW_ALERT_WARN_MBPS': (int, 1, 1_000_000),
    'TOP_BW_ALERT_CRIT_MBPS': (int, 1, 1_000_000),
    'TOP_BW_ALERT_CONSECUTIVE_HITS': (int, 1, 20),
    'TOP_BW_ALERT_RECOVERY_HITS': (int, 1, 20),
    'TOP_BW_ALERT_COOLDOWN_SEC': (int, 0, 86_400),
    'TOP_BW_ALERT_MIN_TX_MBPS': (int, 0, 1_000_000),
    'TOP_BW_ALERT_MIN_RX_MBPS': (int, 0, 1_000_000),
    'DAILY_REPORT_HOUR': (int, 0, 23),
    'ALERT_ESCALATION_MINUTES': (int, 1, 10_000),
    'ALERT_DIGEST_THRESHOLD': (int, 1, 10_000),
    'ALERT_DIGEST_WINDOW': (int, 10, 86_400),
    'TRAFFIC_LEAK_THRESHOLD_MBPS': (int, 0, 1_000_000),
    'ALERT_REQUIRE_START': (bool, None, None),
    'MIKROTIK_RESET_ALL_COOLDOWN_SEC': (int, 5, 3600),
}

# Snapshot default dari env agar reset via file (hapus key) bisa kembali ke nilai asli.
_DEFAULT_OVERRIDABLES = {k: globals().get(k) for k in _OVERRIDABLE_KEYS}
_last_runtime_reload_ts = 0.0
_last_runtime_mtime = None
_router_env_last_reload_ts = 0.0
_router_env_last_mtime = None


def reload_runtime_overrides(force=False, min_interval=5):
    """Reload runtime overrides dari file secara aman dan idempotent.

    Return True jika reload dicoba (dan state dipastikan sinkron),
    False jika di-skip karena throttling.
    """
    global _last_runtime_reload_ts, _last_runtime_mtime

    now = _time.time()
    if not force and (now - _last_runtime_reload_ts) < min_interval:
        return False
    _last_runtime_reload_ts = now

    # Jika file hilang, kembalikan semua key ke default env.
    if not _RUNTIME_CONFIG_FILE.exists():
        for key, val in _DEFAULT_OVERRIDABLES.items():
            globals()[key] = val
        _last_runtime_mtime = None
        return True

    try:
        mtime = _RUNTIME_CONFIG_FILE.stat().st_mtime
    except OSError:
        return True

    if not force and _last_runtime_mtime is not None and mtime == _last_runtime_mtime:
        return True

    try:
        with open(_RUNTIME_CONFIG_FILE, "r") as f:
            overrides = _json.load(f)
    except Exception:
        return True

    if not isinstance(overrides, dict):
        overrides = {}

    # Reset dulu ke default, lalu apply override yang valid.
    for key, val in _DEFAULT_OVERRIDABLES.items():
        globals()[key] = val

    def _parse_runtime_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ('1', 'true', 'yes', 'on'):
                return True
            if text in ('0', 'false', 'no', 'off'):
                return False
        raise ValueError("invalid bool")

    for key, value in overrides.items():
        if key not in _OVERRIDABLE_KEYS:
            continue
        schema = _OVERRIDABLE_SCHEMA.get(key)
        if not schema:
            continue
        type_fn, min_v, max_v = schema
        if type_fn is bool:
            try:
                cast_val = _parse_runtime_bool(value)
            except ValueError:
                continue
        else:
            try:
                cast_val = type_fn(value)
            except (ValueError, TypeError):
                continue
            if cast_val < min_v or cast_val > max_v:
                continue
        globals()[key] = cast_val

    # Guardrail lintas-key: CRIT tidak boleh di bawah WARN.
    if TOP_BW_ALERT_CRIT_MBPS < TOP_BW_ALERT_WARN_MBPS:
        globals()['TOP_BW_ALERT_CRIT_MBPS'] = TOP_BW_ALERT_WARN_MBPS

    _last_runtime_mtime = mtime
    return True


def reload_router_env(force=False, min_interval=5):
    """Reload kredensial router dari `.env` saat runtime.

    Berguna saat router di-hot-swap dan parameter koneksi berubah
    tanpa harus restart bot/monitor.
    """
    global _router_env_last_reload_ts, _router_env_last_mtime
    global ADMIN_IDS, CHAT_ID
    global MIKROTIK_IP, MIKROTIK_USER, MIKROTIK_PASS, MIKROTIK_PORT, MIKROTIK_USE_SSL, BOT_IP
    global MIKROTIK_MAX_CONNECTIONS, MIKROTIK_RECONNECT_BASE_BACKOFF, MIKROTIK_RECONNECT_MAX_BACKOFF
    global MIKROTIK_RESET_ALL_COOLDOWN_SEC, ASYNC_THREAD_WORKERS
    global MIKROTIK_CONNECTION_MAX_AGE_SEC
    global MIKROTIK_TLS_VERIFY, MIKROTIK_TLS_CA_FILE, MIKROTIK_FTP_TLS, MIKROTIK_FTP_ALLOW_INSECURE, MIKROTIK_FTP_PORT
    global TELEGRAM_CONNECT_TIMEOUT, TELEGRAM_READ_TIMEOUT, TELEGRAM_WRITE_TIMEOUT
    global TELEGRAM_POOL_TIMEOUT, TELEGRAM_GET_UPDATES_READ_TIMEOUT, TELEGRAM_CONNECTION_POOL_SIZE
    global TELEGRAM_NETWORK_LOG_WINDOW_SEC, TELEGRAM_NETWORK_LOG_COOLDOWN_SEC
    global INSTITUTION_NAME, DHCP_POOL_SIZE
    global GW_WAN, GW_INET
    global SERVERS_FALLBACK, APS_FALLBACK, CRITICAL_DEVICES_FALLBACK, CRITICAL_DEVICE_NAMES, CRITICAL_DEVICE_WINDOWS
    global MONITOR_IGNORE_IFACE
    global API_ACCOUNT_SKIP_USERS, AUTO_BLOCK_TRUSTED_IPS, MONITOR_VPN_ENABLED, MONITOR_VPN_IGNORE_NAMES, ALERT_REQUIRE_START
    global DNS_CHECK_DOMAIN, DNS_CHECK_DOMAINS
    global TOP_BW_ALERT_ENABLED, TOP_BW_ALERT_TOP_N, TOP_BW_ALERT_WARN_MBPS, TOP_BW_ALERT_CRIT_MBPS
    global TOP_BW_ALERT_CONSECUTIVE_HITS, TOP_BW_ALERT_RECOVERY_HITS, TOP_BW_ALERT_COOLDOWN_SEC
    global TOP_BW_ALERT_MIN_TX_MBPS, TOP_BW_ALERT_MIN_RX_MBPS
    global NETWATCH_INTERVAL, MONITOR_LOG_FETCH_LINES, NETWATCH_PING_CONCURRENCY, API_ACCOUNT_DEDUP_WINDOW_SEC
    global RECOVERY_MIN_UP_SECONDS, NETWATCH_UP_MIN_SUCCESS_RATIO
    global NETWATCH_CYCLE_TIMEOUT_THRESHOLD, NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC
    global CRITICAL_RECOVERY_CONFIRM_COUNT, CRITICAL_RECOVERY_MIN_UP_SECONDS

    now = _time.time()
    if not force and (now - _router_env_last_reload_ts) < min_interval:
        return False
    _router_env_last_reload_ts = now

    try:
        mtime = env_path.stat().st_mtime if env_path.exists() else None
    except OSError:
        return False

    if not force and _router_env_last_mtime is not None and mtime == _router_env_last_mtime:
        return False

    try:
        values = dotenv_values(dotenv_path=env_path)
    except Exception:
        return False

    if not values:
        _router_env_last_mtime = mtime
        return False

    def _parse_bool(value, default=False):
        if value is None:
            return default
        return str(value).strip().lower() in ['true', '1', 'yes']

    def _parse_int(value, default):
        try:
            if value is None or str(value).strip() == "":
                return default
            return int(str(value).strip())
        except (ValueError, TypeError):
            return default

    def _parse_int_range(value, default, min_value, max_value):
        parsed = _parse_int(value, default)
        if parsed < min_value or parsed > max_value:
            return default
        return parsed

    def _parse_float_range(value, default, min_value, max_value):
        try:
            if value is None or str(value).strip() == "":
                return default
            parsed = float(str(value).strip())
        except (ValueError, TypeError):
            return default
        if parsed < min_value or parsed > max_value:
            return default
        return parsed

    _admin_ids_raw_val = str(values.get("ADMIN_IDS", "") or "").strip()
    _chat_id_raw_val = str(values.get("CHAT_ID", "") or "").strip()
    try:
        if _admin_ids_raw_val:
            parsed_admin_ids = [int(x.strip()) for x in _admin_ids_raw_val.split(",") if x.strip()]
        elif _chat_id_raw_val:
            parsed_admin_ids = [int(_chat_id_raw_val)]
        else:
            parsed_admin_ids = list(ADMIN_IDS)
        parsed_admin_ids = [aid for aid in parsed_admin_ids if isinstance(aid, int) and aid > 0]
        if parsed_admin_ids:
            ADMIN_IDS = parsed_admin_ids
            CHAT_ID = ADMIN_IDS[0]
    except Exception:
        # Pertahankan nilai lama jika parsing gagal.
        pass

    MIKROTIK_IP = str(values.get("MIKROTIK_IP", MIKROTIK_IP)).strip()
    MIKROTIK_USER = str(values.get("MIKROTIK_USER", MIKROTIK_USER)).strip()
    MIKROTIK_PASS = str(values.get("MIKROTIK_PASS", MIKROTIK_PASS)).strip()
    MIKROTIK_PORT = _parse_int_range(values.get("MIKROTIK_PORT"), MIKROTIK_PORT, 1, 65535)
    MIKROTIK_USE_SSL = _parse_bool(values.get("MIKROTIK_USE_SSL"), MIKROTIK_USE_SSL)
    MIKROTIK_TLS_VERIFY = _parse_bool(values.get("MIKROTIK_TLS_VERIFY"), MIKROTIK_TLS_VERIFY)
    MIKROTIK_TLS_CA_FILE = str(values.get("MIKROTIK_TLS_CA_FILE", MIKROTIK_TLS_CA_FILE)).strip()
    MIKROTIK_FTP_TLS = _parse_bool(values.get("MIKROTIK_FTP_TLS"), MIKROTIK_FTP_TLS)
    MIKROTIK_FTP_ALLOW_INSECURE = _parse_bool(values.get("MIKROTIK_FTP_ALLOW_INSECURE"), MIKROTIK_FTP_ALLOW_INSECURE)
    MIKROTIK_FTP_PORT = _parse_int_range(values.get("MIKROTIK_FTP_PORT"), MIKROTIK_FTP_PORT, 1, 65535)
    BOT_IP = str(values.get("BOT_IP", BOT_IP)).strip()
    INSTITUTION_NAME = str(values.get("INSTITUTION_NAME", INSTITUTION_NAME)).strip() or INSTITUTION_NAME

    MIKROTIK_MAX_CONNECTIONS = _parse_int_range(
        values.get("MIKROTIK_MAX_CONNECTIONS"), MIKROTIK_MAX_CONNECTIONS, 1, 256
    )
    MIKROTIK_RECONNECT_BASE_BACKOFF = _parse_int_range(
        values.get("MIKROTIK_RECONNECT_BASE_BACKOFF"), MIKROTIK_RECONNECT_BASE_BACKOFF, 1, 300
    )
    MIKROTIK_RECONNECT_MAX_BACKOFF = _parse_int_range(
        values.get("MIKROTIK_RECONNECT_MAX_BACKOFF"), MIKROTIK_RECONNECT_MAX_BACKOFF, 1, 3600
    )
    MIKROTIK_RESET_ALL_COOLDOWN_SEC = _parse_int_range(
        values.get("MIKROTIK_RESET_ALL_COOLDOWN_SEC"), MIKROTIK_RESET_ALL_COOLDOWN_SEC, 5, 3600
    )
    ASYNC_THREAD_WORKERS = _parse_int_range(
        values.get("ASYNC_THREAD_WORKERS"), ASYNC_THREAD_WORKERS, 2, 128
    )
    MIKROTIK_CONNECTION_MAX_AGE_SEC = _parse_int_range(
        values.get("MIKROTIK_CONNECTION_MAX_AGE_SEC"), MIKROTIK_CONNECTION_MAX_AGE_SEC, 0, 86_400
    )
    TELEGRAM_CONNECT_TIMEOUT = _parse_float_range(
        values.get("TELEGRAM_CONNECT_TIMEOUT"), TELEGRAM_CONNECT_TIMEOUT, 1, 120
    )
    TELEGRAM_READ_TIMEOUT = _parse_float_range(
        values.get("TELEGRAM_READ_TIMEOUT"), TELEGRAM_READ_TIMEOUT, 1, 300
    )
    TELEGRAM_WRITE_TIMEOUT = _parse_float_range(
        values.get("TELEGRAM_WRITE_TIMEOUT"), TELEGRAM_WRITE_TIMEOUT, 1, 300
    )
    TELEGRAM_POOL_TIMEOUT = _parse_float_range(
        values.get("TELEGRAM_POOL_TIMEOUT"), TELEGRAM_POOL_TIMEOUT, 1, 120
    )
    TELEGRAM_GET_UPDATES_READ_TIMEOUT = _parse_float_range(
        values.get("TELEGRAM_GET_UPDATES_READ_TIMEOUT"), TELEGRAM_GET_UPDATES_READ_TIMEOUT, 1, 300
    )
    TELEGRAM_CONNECTION_POOL_SIZE = _parse_int_range(
        values.get("TELEGRAM_CONNECTION_POOL_SIZE"), TELEGRAM_CONNECTION_POOL_SIZE, 1, 512
    )
    TELEGRAM_NETWORK_LOG_WINDOW_SEC = _parse_int_range(
        values.get("TELEGRAM_NETWORK_LOG_WINDOW_SEC"), TELEGRAM_NETWORK_LOG_WINDOW_SEC, 60, 86_400
    )
    TELEGRAM_NETWORK_LOG_COOLDOWN_SEC = _parse_int_range(
        values.get("TELEGRAM_NETWORK_LOG_COOLDOWN_SEC"), TELEGRAM_NETWORK_LOG_COOLDOWN_SEC, 30, 86_400
    )
    _api_skip_users_raw_val = str(values.get("API_ACCOUNT_SKIP_USERS", "") or "").strip()
    API_ACCOUNT_SKIP_USERS = [x.strip().lower() for x in _api_skip_users_raw_val.split(",") if x.strip()]
    API_ACCOUNT_DEDUP_WINDOW_SEC = _parse_int_range(
        values.get("API_ACCOUNT_DEDUP_WINDOW_SEC"), API_ACCOUNT_DEDUP_WINDOW_SEC, 30, 86_400
    )
    _auto_block_trusted_raw_val = str(values.get("AUTO_BLOCK_TRUSTED_IPS", "") or "").strip()
    AUTO_BLOCK_TRUSTED_IPS = [x.strip() for x in _auto_block_trusted_raw_val.split(",") if x.strip()]
    _dns_domains_raw = str(values.get("DNS_CHECK_DOMAIN", "") or "").strip()
    DNS_CHECK_DOMAINS = [x.strip() for x in _dns_domains_raw.split(",") if x.strip()] or DNS_CHECK_DOMAINS
    DNS_CHECK_DOMAIN = DNS_CHECK_DOMAINS[0] if DNS_CHECK_DOMAINS else DNS_CHECK_DOMAIN
    _ignore_iface_raw_val = str(values.get("MONITOR_IGNORE_IFACE", "") or "").strip()
    MONITOR_IGNORE_IFACE = set(x.strip() for x in _ignore_iface_raw_val.split(",") if x.strip())
    MONITOR_VPN_ENABLED = _parse_bool(values.get("MONITOR_VPN_ENABLED"), MONITOR_VPN_ENABLED)
    _vpn_ignore_raw_val = str(values.get("MONITOR_VPN_IGNORE_NAMES", "") or "").strip()
    MONITOR_VPN_IGNORE_NAMES = set(x.strip().lower() for x in _vpn_ignore_raw_val.split(",") if x.strip())
    NETWATCH_INTERVAL = _parse_int_range(values.get("NETWATCH_INTERVAL"), NETWATCH_INTERVAL, 5, 3600)
    MONITOR_LOG_FETCH_LINES = _parse_int_range(
        values.get("MONITOR_LOG_FETCH_LINES"), MONITOR_LOG_FETCH_LINES, 20, 1000
    )
    NETWATCH_PING_CONCURRENCY = _parse_int_range(
        values.get("NETWATCH_PING_CONCURRENCY"), NETWATCH_PING_CONCURRENCY, 1, 32
    )
    GW_WAN = str(values.get("GW_WAN", GW_WAN)).strip() or GW_WAN
    GW_INET = str(values.get("GW_INET", GW_INET)).strip() or GW_INET

    _servers_raw_val = str(values.get("SERVERS", "") or "").strip()
    parsed_servers = {}
    for s in _servers_raw_val.split(","):
        if ":" in s:
            name, ip = s.split(":", 1)
            parsed_servers[name.strip()] = ip.strip()
    SERVERS_FALLBACK = parsed_servers

    _aps_raw_val = str(values.get("WIFI_APS", "") or "").strip()
    parsed_aps = {}
    for s in _aps_raw_val.split(","):
        if ":" in s:
            name, ip = s.split(":", 1)
            parsed_aps[name.strip()] = ip.strip()
    APS_FALLBACK = parsed_aps

    _critical_devices_raw_val = str(values.get("CRITICAL_DEVICES", "") or "").strip()
    parsed_critical_devices = {}
    for s in _critical_devices_raw_val.split(","):
        if ":" in s:
            name, ip = s.split(":", 1)
            parsed_critical_devices[name.strip()] = ip.strip()
    CRITICAL_DEVICES_FALLBACK = parsed_critical_devices

    _critical_names_raw_val = str(values.get("CRITICAL_DEVICE_NAMES", "") or "").strip()
    CRITICAL_DEVICE_NAMES = [x.strip() for x in _critical_names_raw_val.split(",") if x.strip()]
    _critical_windows_raw_val = str(values.get("CRITICAL_DEVICE_WINDOWS", "") or "").strip()
    CRITICAL_DEVICE_WINDOWS = _parse_critical_device_windows(_critical_windows_raw_val)

    DHCP_POOL_SIZE = _parse_int_range(values.get("DHCP_POOL_SIZE"), DHCP_POOL_SIZE, 1, 1_000_000)
    ALERT_REQUIRE_START = _parse_bool(values.get("ALERT_REQUIRE_START"), ALERT_REQUIRE_START)
    TOP_BW_ALERT_ENABLED = _parse_bool(values.get("TOP_BW_ALERT_ENABLED"), TOP_BW_ALERT_ENABLED)
    TOP_BW_ALERT_TOP_N = _parse_int_range(values.get("TOP_BW_ALERT_TOP_N"), TOP_BW_ALERT_TOP_N, 1, 50)
    TOP_BW_ALERT_WARN_MBPS = _parse_int_range(values.get("TOP_BW_ALERT_WARN_MBPS"), TOP_BW_ALERT_WARN_MBPS, 1, 1_000_000)
    TOP_BW_ALERT_CRIT_MBPS = _parse_int_range(values.get("TOP_BW_ALERT_CRIT_MBPS"), TOP_BW_ALERT_CRIT_MBPS, 1, 1_000_000)
    TOP_BW_ALERT_CONSECUTIVE_HITS = _parse_int_range(
        values.get("TOP_BW_ALERT_CONSECUTIVE_HITS"), TOP_BW_ALERT_CONSECUTIVE_HITS, 1, 20
    )
    TOP_BW_ALERT_RECOVERY_HITS = _parse_int_range(
        values.get("TOP_BW_ALERT_RECOVERY_HITS"), TOP_BW_ALERT_RECOVERY_HITS, 1, 20
    )
    TOP_BW_ALERT_COOLDOWN_SEC = _parse_int_range(
        values.get("TOP_BW_ALERT_COOLDOWN_SEC"), TOP_BW_ALERT_COOLDOWN_SEC, 0, 86_400
    )
    TOP_BW_ALERT_MIN_TX_MBPS = _parse_int_range(
        values.get("TOP_BW_ALERT_MIN_TX_MBPS"), TOP_BW_ALERT_MIN_TX_MBPS, 0, 1_000_000
    )
    TOP_BW_ALERT_MIN_RX_MBPS = _parse_int_range(
        values.get("TOP_BW_ALERT_MIN_RX_MBPS"), TOP_BW_ALERT_MIN_RX_MBPS, 0, 1_000_000
    )
    RECOVERY_MIN_UP_SECONDS = _parse_int_range(
        values.get("RECOVERY_MIN_UP_SECONDS"), RECOVERY_MIN_UP_SECONDS, 0, 3600
    )
    NETWATCH_CYCLE_TIMEOUT_THRESHOLD = _parse_int_range(
        values.get("NETWATCH_CYCLE_TIMEOUT_THRESHOLD"), NETWATCH_CYCLE_TIMEOUT_THRESHOLD, 1, 20
    )
    NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC = _parse_int_range(
        values.get("NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC"),
        NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC,
        30,
        86_400,
    )
    CRITICAL_RECOVERY_CONFIRM_COUNT = _parse_int_range(
        values.get("CRITICAL_RECOVERY_CONFIRM_COUNT"), CRITICAL_RECOVERY_CONFIRM_COUNT, 1, 20
    )
    CRITICAL_RECOVERY_MIN_UP_SECONDS = _parse_int_range(
        values.get("CRITICAL_RECOVERY_MIN_UP_SECONDS"), CRITICAL_RECOVERY_MIN_UP_SECONDS, 0, 3600
    )
    NETWATCH_UP_MIN_SUCCESS_RATIO = _parse_float_range(
        values.get("NETWATCH_UP_MIN_SUCCESS_RATIO"), NETWATCH_UP_MIN_SUCCESS_RATIO, 0.1, 1.0
    )
    if TOP_BW_ALERT_CRIT_MBPS < TOP_BW_ALERT_WARN_MBPS:
        TOP_BW_ALERT_CRIT_MBPS = TOP_BW_ALERT_WARN_MBPS

    _router_env_last_mtime = mtime
    return True


# Initial sync at import.
reload_runtime_overrides(force=True, min_interval=0)
