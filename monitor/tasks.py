# ============================================
# MONITOR/TASKS - Monitor Tasks (System, Logs, DHCP/ARP)
# ============================================

import time
import asyncio
import logging
import re
import socket
import ipaddress
import random
from collections import deque

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import core.config as cfg
from mikrotik import (
    get_status, get_interfaces, get_traffic, get_mikrotik_log,
    get_dhcp_usage_count, get_dhcp_pool_capacity, get_arp_anomalies, get_active_arp_ip_set, block_ip, _pool
)
from .alerts import (
    kirim_ke_semua_admin, with_timeout, bot, check_escalation, send_digest,
    AlertSeverity,
)
from .checks import (
    cek_cpu_ram, cek_disk, cek_interface,
    cek_uptime_anomaly, cek_firmware, cek_vpn_tunnels,
    _last_alerts, clear_runtime_state as clear_checks_runtime_state
)
from core import database
from core.runtime_reset_signal import read_runtime_reset_signal

logger = logging.getLogger(__name__)
_LOCAL_IP_CACHE = {"ips": set(), "ts": 0.0}
_API_HEALTH_CACHE = {"ts": 0.0, "healthy": True, "last_error": ""}
_API_PAUSE_LOG_TS = {}
_API_HEAL_ATTEMPT_TS = 0.0
_INTERFACES_CACHE = {"ts": 0.0, "items": []}
_INTERFACE_TRAFFIC_CACHE = {"ts": 0.0, "items": {}}
_DHCP_USAGE_CACHE = {"ts": 0.0, "bound": 0}
_DHCP_POOL_CAPACITY_CACHE = {"ts": 0.0, "size": 0}
_ROUTER_LOG_CACHE = {"ts": 0.0, "lines": []}
_TRAFFIC_QUERY_MIN_CONCURRENCY = 1
_TRAFFIC_QUERY_MAX_CONCURRENCY = 3
_BACKGROUND_LOG_FETCH_HARD_CAP = 250
_LAST_RUNTIME_RESET_SEEN = 0.0
_rx_anomaly_state = {}  # iface_name -> state dict untuk deteksi RX packet anomali
_rx_packet_counter_cache = {}  # iface_name -> {"rx_packet": int, "tx_packet": int, "ts": float}


def clear_runtime_state():
    """Reset cache/state in-memory task monitor."""
    global _LAST_RUNTIME_RESET_SEEN, _API_HEAL_ATTEMPT_TS
    _LOCAL_IP_CACHE["ips"] = set()
    _LOCAL_IP_CACHE["ts"] = 0.0
    _API_HEALTH_CACHE["ts"] = 0.0
    _API_HEALTH_CACHE["healthy"] = True
    _API_HEALTH_CACHE["last_error"] = ""
    _API_PAUSE_LOG_TS.clear()
    _API_HEAL_ATTEMPT_TS = 0.0
    _INTERFACES_CACHE["ts"] = 0.0
    _INTERFACES_CACHE["items"] = []
    _INTERFACE_TRAFFIC_CACHE["ts"] = 0.0
    _INTERFACE_TRAFFIC_CACHE["items"] = {}
    _DHCP_USAGE_CACHE["ts"] = 0.0
    _DHCP_USAGE_CACHE["bound"] = 0
    _DHCP_POOL_CAPACITY_CACHE["ts"] = 0.0
    _DHCP_POOL_CAPACITY_CACHE["size"] = 0
    _ROUTER_LOG_CACHE["ts"] = 0.0
    _ROUTER_LOG_CACHE["lines"] = []
    _alerted_hosts_traffic.clear()
    _top_bw_host_state.clear()
    _rx_anomaly_state.clear()
    _rx_packet_counter_cache.clear()
    clear_checks_runtime_state()
    for key in list(_last_alerts.keys()):
        if key.startswith("traffic_"):
            _last_alerts.pop(key, None)


def apply_runtime_reset_if_signaled():
    """Apply reset signal shared file sekali per proses."""
    global _LAST_RUNTIME_RESET_SEEN
    payload = read_runtime_reset_signal()
    try:
        ts = float(payload.get("ts", 0) or 0)
    except (TypeError, ValueError):
        ts = 0.0
    if ts <= 0 or ts <= _LAST_RUNTIME_RESET_SEEN:
        return False

    clear_runtime_state()
    try:
        cfg.reload_runtime_overrides(force=True, min_interval=0)
        cfg.reload_router_env(force=True, min_interval=0)
    except Exception as e:
        logger.debug("Tasks runtime reset reload gagal: %s", e)
    _LAST_RUNTIME_RESET_SEEN = ts
    logger.info("Monitor tasks state dibersihkan via shared reset signal.")
    return True


def _get_local_ipv4_set(cache_ttl=300):
    """Best-effort list IP lokal host bot (untuk filter log API login sendiri)."""
    now = time.time()
    if (now - float(_LOCAL_IP_CACHE.get("ts", 0.0))) < max(10, int(cache_ttl)):
        return set(_LOCAL_IP_CACHE.get("ips", set()))
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            ip = info[4][0]
            if ip and ip != "127.0.0.1":
                ips.add(ip)
    except Exception as e:
        logger.debug("Tidak bisa membaca local IPv4 set: %s", e)
    _LOCAL_IP_CACHE["ips"] = ips
    _LOCAL_IP_CACHE["ts"] = now
    return set(ips)


def _normalize_ipv4(value):
    """Normalisasi string IPv4 valid, return None jika invalid."""
    try:
        parsed = ipaddress.ip_address(str(value or "").strip())
        if parsed.version != 4:
            return None
        return str(parsed)
    except ValueError:
        return None


async def _get_api_health_cached(cache_ttl=5):
    """Cek health API RouterOS dengan cache singkat agar tidak memicu connect storm."""
    global _API_HEAL_ATTEMPT_TS
    now = time.time()
    if (now - float(_API_HEALTH_CACHE.get("ts", 0.0))) < max(1, int(cache_ttl)):
        return bool(_API_HEALTH_CACHE.get("healthy", False)), str(_API_HEALTH_CACHE.get("last_error", ""))

    try:
        diag = _pool.connection_diagnostics()
    except Exception as e:
        logger.debug("connection_diagnostics direct call gagal: %s", e)
        diag = {}
    healthy = bool(isinstance(diag, dict) and diag.get("healthy", False))
    last_error = str((diag or {}).get("last_error", "")).strip() if isinstance(diag, dict) else ""

    backoff_seconds = 0.0
    if isinstance(diag, dict):
        try:
            backoff_seconds = float(diag.get("backoff_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            backoff_seconds = 0.0

    heal_cooldown = max(5, int(cache_ttl))
    if (not healthy) and backoff_seconds <= 0.0 and (now - float(_API_HEAL_ATTEMPT_TS or 0.0)) >= heal_cooldown:
        _API_HEAL_ATTEMPT_TS = now
        try:
            recovered = await asyncio.to_thread(_pool.health_check)
        except Exception as e:
            logger.debug("API self-heal attempt gagal: %s", e)
            recovered = False
        if recovered:
            healthy = True
            last_error = ""

    _API_HEALTH_CACHE["ts"] = now
    _API_HEALTH_CACHE["healthy"] = healthy
    _API_HEALTH_CACHE["last_error"] = last_error
    return healthy, last_error


def _clone_interfaces(items):
    return [dict(item) for item in (items or []) if isinstance(item, dict)]


async def _get_interfaces_snapshot(cache_ttl=180, timeout=10, log_key="tasks:get_interfaces"):
    """Ambil daftar interface dengan cache last-good agar task periodik lebih stabil."""
    now = time.time()
    cached_items = _clone_interfaces(_INTERFACES_CACHE.get("items", []))
    if cached_items and (now - float(_INTERFACES_CACHE.get("ts", 0.0))) < max(30, int(cache_ttl)):
        return cached_items

    interfaces = await with_timeout(
        asyncio.to_thread(get_interfaces),
        timeout=timeout,
        log_key=log_key,
        warn_every_sec=300,
    )
    if interfaces:
        snapshot = _clone_interfaces(interfaces)
        _INTERFACES_CACHE["items"] = snapshot
        _INTERFACES_CACHE["ts"] = now
        return _clone_interfaces(snapshot)

    if cached_items:
        logger.debug("[%s] memakai cache interface last-good (%s item)", log_key, len(cached_items))
        return cached_items
    return []


async def _get_dhcp_usage_snapshot(cache_ttl=600):
    """Ambil bound DHCP dengan fallback ke nilai last-good saat query timeout."""
    bound = await with_timeout(
        asyncio.to_thread(get_dhcp_usage_count),
        timeout=10,
        default=None,
        log_key="tasks:get_dhcp_usage_count",
        warn_every_sec=300,
    )
    now = time.time()
    if bound is not None:
        _DHCP_USAGE_CACHE["bound"] = int(bound)
        _DHCP_USAGE_CACHE["ts"] = now
        return int(bound)

    if (now - float(_DHCP_USAGE_CACHE.get("ts", 0.0))) < max(60, int(cache_ttl)):
        cached_bound = int(_DHCP_USAGE_CACHE.get("bound", 0) or 0)
        logger.debug("[tasks:get_dhcp_usage_count] memakai cache last-good=%s", cached_bound)
        return cached_bound
    return 0


async def _get_dhcp_pool_capacity_snapshot(cache_ttl=900):
    """Ambil ukuran pool DHCP aktual dengan cache last-good dan fallback config."""
    pool_size = await with_timeout(
        asyncio.to_thread(get_dhcp_pool_capacity),
        timeout=10,
        default=None,
        log_key="tasks:get_dhcp_pool_capacity",
        warn_every_sec=900,
    )
    now = time.time()
    if pool_size is not None and int(pool_size or 0) > 0:
        _DHCP_POOL_CAPACITY_CACHE["size"] = int(pool_size)
        _DHCP_POOL_CAPACITY_CACHE["ts"] = now
        return int(pool_size)

    if (now - float(_DHCP_POOL_CAPACITY_CACHE.get("ts", 0.0))) < max(60, int(cache_ttl)):
        cached_size = int(_DHCP_POOL_CAPACITY_CACHE.get("size", 0) or 0)
        if cached_size > 0:
            logger.debug("[tasks:get_dhcp_pool_capacity] memakai cache last-good=%s", cached_size)
            return cached_size

    return int(getattr(cfg, "DHCP_POOL_SIZE", 0) or 0)


async def _get_router_logs_snapshot(fetch_lines, timeout=15, cache_ttl=180):
    """Ambil tail log router dengan batas aman background dan fallback cache last-good."""
    requested = max(1, int(fetch_lines))
    effective_lines = min(requested, _BACKGROUND_LOG_FETCH_HARD_CAP)
    logs = await with_timeout(
        asyncio.to_thread(get_mikrotik_log, effective_lines),
        timeout=timeout,
        default=None,
        log_key="tasks:get_mikrotik_log",
        warn_every_sec=900,
    )
    now = time.time()
    if logs is not None:
        normalized = list(logs)
        _ROUTER_LOG_CACHE["lines"] = normalized
        _ROUTER_LOG_CACHE["ts"] = now
        return normalized

    cached_logs = list(_ROUTER_LOG_CACHE.get("lines", []))
    if cached_logs and (now - float(_ROUTER_LOG_CACHE.get("ts", 0.0))) < max(30, int(cache_ttl)):
        logger.debug("[tasks:get_mikrotik_log] memakai cache last-good (%s line)", len(cached_logs))
        return cached_logs[-effective_lines:]
    return None


# Single source of truth — canonical implementation in monitor.utils
from .utils import compute_sleep_with_jitter as _compute_sleep_with_jitter
from .utils import sleep_with_jitter as _sleep_with_jitter


async def _pause_if_api_unavailable(task_name, interval, cache_ttl=5, log_every_sec=300):
    """Pause task non-netwatch saat API unavailable agar tidak spam error."""
    healthy, last_error = await _get_api_health_cached(cache_ttl=cache_ttl)
    if healthy:
        return False

    now = time.time()
    last_log = float(_API_PAUSE_LOG_TS.get(task_name, 0.0))
    if (now - last_log) >= max(30, int(log_every_sec)):
        logger.warning(
            "[%s] dipause karena MikroTik API unavailable. last_error=%s",
            task_name,
            last_error or "-",
        )
        _API_PAUSE_LOG_TS[task_name] = now
    await _sleep_with_jitter(interval)
    return True


def _traffic_query_concurrency():
    """Batasi query monitor-traffic agar tidak memicu burst koneksi ke RouterOS."""
    try:
        limit = int(getattr(cfg, "MIKROTIK_MAX_CONNECTIONS", 8) or 8) // 4
    except (TypeError, ValueError):
        limit = 2
    return max(_TRAFFIC_QUERY_MIN_CONCURRENCY, min(_TRAFFIC_QUERY_MAX_CONCURRENCY, limit or 2))


def _remember_interface_traffic(active_ifaces, traffic_results):
    """Simpan snapshot traffic terakhir agar task lain bisa reuse tanpa query ulang."""
    snapshot = {}
    for iface, traffic in zip(active_ifaces, traffic_results):
        if isinstance(traffic, Exception) or not traffic:
            continue
        name = str(iface.get("name", "")).strip()
        if not name:
            continue
        snapshot[name] = dict(traffic)
    if snapshot:
        _INTERFACE_TRAFFIC_CACHE["items"] = snapshot
        _INTERFACE_TRAFFIC_CACHE["ts"] = time.time()


def _get_recent_interface_traffic(active_ifaces, cache_ttl=75):
    """Ambil snapshot traffic interface terakhir jika semua iface tersedia dan masih fresh."""
    now = time.time()
    if (now - float(_INTERFACE_TRAFFIC_CACHE.get("ts", 0.0))) > max(5, int(cache_ttl)):
        return None

    cached_items = _INTERFACE_TRAFFIC_CACHE.get("items", {}) or {}
    results = []
    for iface in active_ifaces:
        name = str(iface.get("name", "")).strip()
        traffic = cached_items.get(name)
        if not traffic:
            return None
        results.append(dict(traffic))
    return results


async def _collect_interface_traffic(active_ifaces, log_prefix, timeout=10):
    """Kumpulkan traffic interface dengan concurrency terbatas untuk menekan timeout."""
    if not active_ifaces:
        return []

    semaphore = asyncio.Semaphore(_traffic_query_concurrency())
    effective_timeout = max(5, int(timeout))

    async def _fetch(iface):
        async with semaphore:
            return await with_timeout(
                asyncio.to_thread(get_traffic, iface['name']),
                timeout=effective_timeout,
                log_key=f"{log_prefix}:{iface['name']}",
                warn_every_sec=300,
            )

    tasks = [_fetch(iface) for iface in active_ifaces]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    _remember_interface_traffic(active_ifaces, results)
    return results


def _extract_login_failure_ip(message_text):
    """Ekstrak source IP dari log 'login failure ... from X.X.X.X'."""
    msg = str(message_text or "").lower()
    match = re.search(r"\bfrom\s+(\d{1,3}(?:\.\d{1,3}){3})\b", msg)
    if not match:
        return None
    return _normalize_ipv4(match.group(1))


def _is_queue_change_log(topics, message_text):
    """Deteksi log perubahan queue yang layak diforward walau topic hanya info."""
    msg = str(message_text or "").lower()
    if "queue" not in msg:
        return False
    if "by admin" not in msg:
        return False

    action_tokens = (
        "added",
        "removed",
        "deleted",
        "changed",
        "updated",
        "edited",
        "disabled",
        "enabled",
        "moved",
        "set ",
    )
    if not any(token in msg for token in action_tokens):
        return False

    topics_l = str(topics or "").lower()
    return any(token in topics_l for token in ("system", "account", "info"))


def _is_dhcp_pool_exhausted_log(topics, message_text):
    """Deteksi log DHCP pool habis yang lebih baik ditangani monitor stateful."""
    topics_l = str(topics or "").lower()
    msg_l = str(message_text or "").lower()
    if "dhcp" not in topics_l or "error" not in topics_l:
        return False
    if "failed to give out ip address" not in msg_l:
        return False
    if "pool" not in msg_l:
        return False
    return ("is empty" in msg_l) or ("no more addresses" in msg_l)


def _get_autoblock_trusted_ips():
    """Set IP trusted yang tidak boleh pernah di-auto-block."""
    trusted = {"127.0.0.1", "0.0.0.0"}

    # Sumber utama dari config.
    for raw in [cfg.BOT_IP, cfg.MIKROTIK_IP]:
        ip = _normalize_ipv4(raw)
        if ip:
            trusted.add(ip)

    # Fallback ip lokal host bot.
    for raw in _get_local_ipv4_set():
        ip = _normalize_ipv4(raw)
        if ip:
            trusted.add(ip)

    # Allowlist tambahan dari .env jika dibutuhkan.
    for raw in getattr(cfg, "AUTO_BLOCK_TRUSTED_IPS", []):
        ip = _normalize_ipv4(raw)
        if ip:
            trusted.add(ip)

    return trusted


def _should_skip_api_account_log(
    topics,
    message_text,
    bot_ip,
    last_sent_map,
    dedup_window_sec,
    now_ts=None,
    bot_usernames=None,
):
    """Return True jika log account API perlu di-skip (noise/dedup)."""
    topics_l = str(topics or "").lower()
    msg_l = str(message_text or "").lower()
    bot_users = {str(u).strip().lower() for u in (bot_usernames or []) if str(u).strip()}
    if 'account' not in topics_l:
        return False
    if 'via api' not in msg_l:
        return False
    if ('logged in from' not in msg_l) and ('logged out from' not in msg_l):
        return False

    m_ip = re.search(r'from\s+(\d{1,3}(?:\.\d{1,3}){3})', msg_l)
    src_ip = m_ip.group(1) if m_ip else None
    m_user = re.search(r'user\s+([^\s]+)\s+logged\s+(?:in|out)', msg_l)
    actor_user = m_user.group(1) if m_user else ""
    is_bot_user = (not bot_users) or (actor_user in bot_users)

    # Event login/logout dari IP bot sendiri -> skip total.
    if bot_ip and src_ip == bot_ip and is_bot_user:
        return True

    # Fallback otomatis jika BOT_IP belum diset:
    # jika source IP termasuk IP lokal host bot, perlakukan sebagai noise operasional.
    if (not bot_ip) and src_ip and (src_ip in _get_local_ipv4_set()) and is_bot_user:
        return True

    ts_now = time.time() if now_ts is None else float(now_ts)
    sig = f"{topics_l}|{msg_l}"
    last_ts = float(last_sent_map.get(sig, 0.0) or 0.0)
    if (ts_now - last_ts) < max(30, int(dedup_window_sec)):
        return True

    last_sent_map[sig] = ts_now
    return False


def _build_router_log_chunks(log_entries, max_chars=3500):
    """Pecah forward log router jadi beberapa pesan agar tidak melewati limit Telegram."""
    header = "🔔 <b>Router Logs Detected:</b>\n\n"
    chunks = []
    current = header

    for l in log_entries:
        safe_msg = str(l.get('message', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        entry = f"⏰ {l.get('time', '')}\n🏷️ {l.get('topics', '')}\n📝 {safe_msg}\n\n"
        if len(current) + len(entry) > max_chars:
            if current != header:
                chunks.append(current)
            # Jika single entry terlalu panjang, potong agar tetap terkirim.
            if len(entry) > max_chars:
                entry = entry[:max_chars - len(header) - 16] + "\n...(truncated)\n\n"
            current = header + entry
        else:
            current += entry

    if current != header:
        chunks.append(current)
    return chunks


async def task_monitor_system():
    """Task 1: Monitor System (CPU, RAM, Interface) tiap 5 menit."""
    interval = int(cfg.MONITOR_INTERVAL)
    logger.info(f"[INIT] System Monitor berjalan (Interval: {interval}s)")

    _last_error_alert_time = 0
    _last_prune_time = 0
    _last_health_check = 0
    _ERROR_ALERT_COOLDOWN = 900

    while True:
        try:
            if apply_runtime_reset_if_signaled():
                _last_error_alert_time = 0
                _last_prune_time = 0
                _last_health_check = 0
            cfg.reload_runtime_overrides(min_interval=10)
            cfg.reload_router_env(min_interval=10)
            interval = int(cfg.MONITOR_INTERVAL)
            now_time = time.time()

            # Auto-prune & close stale incidents setiap 24 jam
            if now_time - _last_prune_time > 86400:
                try:
                    deleted = await asyncio.to_thread(database.cleanup_old_data, 60)
                    if deleted > 0:
                        logger.info(f"[DB] Auto-pruned {deleted} old records.")
                except Exception as dbe:
                    logger.warning(f"[ERR] DB Prune: {dbe}")
                # C1 FIX: Tutup incident yang terbuka > 24 jam (seharusnya sudah UP tapi tidak tercatat)
                try:
                    stale = await asyncio.to_thread(database.close_stale_incidents, 24)
                    if stale > 0:
                        logger.info(f"[DB] Closed {stale} stale incidents (> 24h tanpa recovery).")
                except Exception as se:
                    logger.warning(f"[ERR] Close stale incidents: {se}")
                _last_prune_time = now_time

            if await _pause_if_api_unavailable("system", interval):
                continue

            # Connection health check periodik (setiap 5 menit)
            if now_time - _last_health_check > 300:
                try:
                    healthy = await asyncio.to_thread(_pool.health_check)
                    if not healthy:
                        logger.warning("[WARN] MikroTik connection health check failed, reconnecting...")
                        # Router bisa di-hot-swap (IP sama, sesi lama invalid).
                        # Paksa semua thread reconnect pada request berikutnya.
                        await asyncio.to_thread(_pool.reset_all)
                except Exception as e:
                    logger.debug(f"Health check error: {e}")
                _last_health_check = now_time

            logger.debug("System check tick")
            info = await with_timeout(
                asyncio.to_thread(get_status),
                timeout=15,
                log_key="tasks:get_status",
                warn_every_sec=300,
            )
            if info is None:
                logger.warning("[ERR] get_status timed out")
                await _sleep_with_jitter(interval)
                continue


            await cek_disk(info)
            # W2 FIX: Ambil interfaces sekali dan reuse untuk cek_interface + traffic check
            _cached_interfaces = await _get_interfaces_snapshot(cache_ttl=max(interval, 180))
            await cek_interface(_cached_interfaces)
            await cek_firmware()
            await cek_vpn_tunnels()

            # Cek traffic alert threshold menggunakan cached interfaces
            if cfg.TRAFFIC_THRESHOLD_MBPS > 0 and _cached_interfaces:
                threshold_bps = cfg.TRAFFIC_THRESHOLD_MBPS * 1_000_000
                active_ifaces = [
                    iface for iface in _cached_interfaces
                    if iface['name'] not in cfg.MONITOR_IGNORE_IFACE and iface['running']
                ]
                traffic_results = _get_recent_interface_traffic(active_ifaces, cache_ttl=75)
                if traffic_results is None:
                    traffic_results = await _collect_interface_traffic(active_ifaces, "tasks:get_traffic")

                for iface, traffic in zip(active_ifaces, traffic_results):
                    if isinstance(traffic, Exception) or not traffic:
                        continue
                    rx_bps = traffic.get('rx_bps', 0)
                    tx_bps = traffic.get('tx_bps', 0)
                    if rx_bps > threshold_bps or tx_bps > threshold_bps:
                        alert_key = f"traffic_{iface['name']}"
                        if not _last_alerts.get(alert_key):
                            rx_mb = rx_bps / 1_000_000
                            tx_mb = tx_bps / 1_000_000

                            # Ambil top users dari Simple Queue untuk ditampilkan di alert
                            top_users_text = ""
                            try:
                                from mikrotik import get_top_queues
                                top = await with_timeout(
                                    asyncio.to_thread(get_top_queues, 5),
                                    timeout=8,
                                    log_key="tasks:traffic_alert:get_top_queues",
                                    warn_every_sec=300,
                                )
                                if top:
                                    top_lines = []
                                    for idx, q in enumerate(top[:3], 1):
                                        if not isinstance(q, dict):
                                            continue
                                        name = q.get('name', '?')
                                        q_rx = _queue_rate_to_mbps(q.get('rx_rate', 0))
                                        q_tx = _queue_rate_to_mbps(q.get('tx_rate', 0))
                                        q_total = q_rx + q_tx
                                        if q_total <= 0:
                                            continue
                                        top_lines.append(
                                            f"  {idx}. <b>{name}</b> — {q_total:.1f} Mbps "
                                            f"(RX: {q_rx:.1f} | TX: {q_tx:.1f})"
                                        )
                                    if top_lines:
                                        top_users_text = (
                                            "\n\n👥 <b>Top Pengguna Saat Ini:</b>\n"
                                            + "\n".join(top_lines)
                                        )
                            except Exception as tq_err:
                                logger.debug("Gagal ambil top queues untuk traffic alert: %s", tq_err)

                            await kirim_ke_semua_admin(
                                f"⚠️ <b>TRAFFIC ALERT</b>\n\n"
                                f"Interface: <b>{iface['name']}</b>\n"
                                f"Traffic melampaui threshold ({cfg.TRAFFIC_THRESHOLD_MBPS} Mbps)\n"
                                f"RX: {rx_mb:.1f} Mbps\nTX: {tx_mb:.1f} Mbps"
                                f"{top_users_text}",
                                parse_mode='HTML'
                            )
                            _last_alerts[alert_key] = True
                    else:
                        _last_alerts[f"traffic_{iface['name']}"] = False

        except asyncio.CancelledError:
            raise
        except Exception as e:
            now = time.time()
            if now - _last_error_alert_time >= _ERROR_ALERT_COOLDOWN:
                await kirim_ke_semua_admin(
                    f"[ALERT] Router Monitor Error!\n{str(e)[:100]}"
                )
                _last_error_alert_time = now

        await _sleep_with_jitter(interval)


async def task_monitor_resources():
    """Task 1b: Monitor resource CPU/RAM lebih rapat tanpa membebani full system check."""
    interval = int(getattr(cfg, "RESOURCE_MONITOR_INTERVAL", 60) or 60)
    logger.info(f"[INIT] Resource Monitor berjalan (Interval: {interval}s)")

    _last_error_alert_time = 0
    _ERROR_ALERT_COOLDOWN = 900

    while True:
        try:
            if apply_runtime_reset_if_signaled():
                _last_error_alert_time = 0

            cfg.reload_runtime_overrides(min_interval=10)
            cfg.reload_router_env(min_interval=10)
            interval = int(getattr(cfg, "RESOURCE_MONITOR_INTERVAL", 60) or 60)

            if await _pause_if_api_unavailable("resources", interval):
                continue

            info = await with_timeout(
                asyncio.to_thread(get_status),
                timeout=15,
                log_key="resources:get_status",
                warn_every_sec=300,
            )
            if info is None:
                logger.warning("[ERR] resources:get_status timed out")
                await _sleep_with_jitter(interval)
                continue

            await cek_cpu_ram(info)
            await cek_uptime_anomaly(info)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[ERR] Task Resource Monitor: {e}")
            now = time.time()
            if now - _last_error_alert_time >= _ERROR_ALERT_COOLDOWN:
                try:
                    await kirim_ke_semua_admin(
                        f"⚠️ <b>Resource Monitor Error</b>\n\n<code>{str(e)[:300]}</code>",
                        parse_mode='HTML',
                        severity=AlertSeverity.WARNING,
                    )
                    _last_error_alert_time = now
                except Exception:
                    pass

        await _sleep_with_jitter(interval)


# ============ PER-HOST TRAFFIC LEAK DETECTION ============

_alerted_hosts_traffic = set()  # Tracking host yang sudah di-alert traffic leak
_ALERTED_HOSTS_TRAFFIC_MAX = 2000  # FIND-1 FIX: cap agar tidak memory leak di legacy mode
_top_bw_host_state = {}         # host -> state dict (engine top bandwidth baru)


def _classify_bw_level(peak_mbps):
    """Klasifikasi level bandwidth berdasarkan peak sisi RX/TX, bukan total gabungan."""
    warn = float(cfg.TOP_BW_ALERT_WARN_MBPS)
    crit = float(max(cfg.TOP_BW_ALERT_CRIT_MBPS, cfg.TOP_BW_ALERT_WARN_MBPS))
    if peak_mbps >= crit:
        return "critical"
    if peak_mbps >= warn:
        return "warning"
    return None


def _queue_rate_to_mbps(raw_rate):
    """Konversi rate simple queue RouterOS (bit/s) ke Mbps."""
    try:
        return float(raw_rate or 0) / 1_000_000
    except (TypeError, ValueError):
        return 0.0


def _build_top_bw_alert_message(host_name, rank, level, total_mbps, rx_mbps, tx_mbps, peak_mbps, peak_dir, hits, threshold_hits):
    lvl = "CRITICAL" if level == "critical" else "WARNING"
    return (
        f"🚨 <b>[TOP BW {lvl}] {host_name} (#{rank})</b>\n\n"
        f"Peak: <b>{peak_mbps:.1f} Mbps</b> ({peak_dir})\n"
        f"RX: {rx_mbps:.1f} Mbps | TX: {tx_mbps:.1f} Mbps\n"
        f"Total: {total_mbps:.1f} Mbps\n"
        f"Warn/Crit: {cfg.TOP_BW_ALERT_WARN_MBPS}/{cfg.TOP_BW_ALERT_CRIT_MBPS} Mbps\n"
        f"Observed hits: {hits}x\n"
        f"Threshold hits: {threshold_hits}x"
    )


def _build_top_bw_recovery_message(host_name):
    return f"✅ <b>[TOP BW RECOVERY] {host_name}</b>\n\nTraffic kembali normal."


def _should_skip_top_bw_queue(queue_item):
    """Skip queue agregat/ignored agar top bandwidth fokus ke host nyata."""
    if not isinstance(queue_item, dict):
        return True

    name = str(queue_item.get('name', '')).strip()
    target = str(queue_item.get('target', '')).strip()
    ignore_names = {str(x).strip().lower() for x in getattr(cfg, "TOP_BW_ALERT_IGNORE_QUEUES", []) if str(x).strip()}

    if name and name.lower() in ignore_names:
        return True

    if "/" in target:
        try:
            net = ipaddress.ip_network(target, strict=False)
            if net.prefixlen < 32:
                return True
        except ValueError:
            pass

    return False


def _extract_single_target_ip(queue_item):
    """Ambil target IP tunggal dari queue /32. Return None jika bukan host tunggal."""
    if not isinstance(queue_item, dict):
        return None

    target = str(queue_item.get('target', '')).strip()
    if not target or "," in target:
        return None

    if "/" not in target:
        return _normalize_ipv4(target)

    try:
        net = ipaddress.ip_network(target, strict=False)
    except ValueError:
        return None

    if net.prefixlen != 32:
        return None
    return str(net.network_address)


def _normalize_top_bw_candidates(queue_list):
    """Normalisasi queue list menjadi kandidat terurut untuk evaluasi top-N."""
    candidates = []
    active_arp_ips = None

    for q in queue_list:
        if not isinstance(q, dict):
            continue
        name = str(q.get('name', '')).strip()
        if not name:
            continue
        if name in cfg.TRAFFIC_LEAK_WHITELIST:
            continue
        if _should_skip_top_bw_queue(q):
            continue

        target_ip = _extract_single_target_ip(q)
        if target_ip:
            # Query ARP aktif hanya saat queue benar-benar merepresentasikan satu host.
            if active_arp_ips is None:
                try:
                    active_arp_ips = set(get_active_arp_ip_set() or set())
                except Exception as e:
                    logger.debug("Gagal mengambil active ARP IP set untuk top_bw: %s", e)
                    active_arp_ips = set()
            if active_arp_ips and target_ip not in active_arp_ips:
                logger.info(
                    "[top_bw] skip queue '%s' karena target %s tidak aktif di ARP.",
                    name,
                    target_ip,
                )
                continue

        rx_bps = float(q.get('rx_rate', 0) or 0)
        tx_bps = float(q.get('tx_rate', 0) or 0)
        total_bps = rx_bps + tx_bps
        if total_bps <= 0:
            continue

        rx_mbps = _queue_rate_to_mbps(rx_bps)
        tx_mbps = _queue_rate_to_mbps(tx_bps)
        total_mbps = _queue_rate_to_mbps(total_bps)
        peak_mbps = max(rx_mbps, tx_mbps)
        peak_dir = "RX" if rx_mbps >= tx_mbps else "TX"
        # Filter asimetris/noise: minimal salah satu sisi melewati ambang min.
        if rx_mbps < cfg.TOP_BW_ALERT_MIN_RX_MBPS and tx_mbps < cfg.TOP_BW_ALERT_MIN_TX_MBPS:
            continue

        candidates.append({
            "name": name,
            "rx_mbps": rx_mbps,
            "tx_mbps": tx_mbps,
            "total_mbps": total_mbps,
            "peak_mbps": peak_mbps,
            "peak_dir": peak_dir,
        })

    candidates.sort(key=lambda x: (x["peak_mbps"], x["total_mbps"]), reverse=True)
    for idx, c in enumerate(candidates, start=1):
        c["rank"] = idx
    return candidates


async def _run_top_bw_alert_engine(queue_list):
    """Engine stateful untuk alert top bandwidth consumer."""
    global _top_bw_host_state
    now = time.time()
    top_n = max(1, int(cfg.TOP_BW_ALERT_TOP_N))
    consecutive_hits = max(1, int(cfg.TOP_BW_ALERT_CONSECUTIVE_HITS))
    recovery_hits = max(1, int(cfg.TOP_BW_ALERT_RECOVERY_HITS))
    cooldown_sec = max(0, int(cfg.TOP_BW_ALERT_COOLDOWN_SEC))
    candidates = _normalize_top_bw_candidates(queue_list)[:top_n]
    seen_names = set()

    for c in candidates:
        name = c["name"]
        seen_names.add(name)
        state = _top_bw_host_state.setdefault(name, {
            "warn_hits": 0,
            "crit_hits": 0,
            "recovery_hits": 0,
            "last_level": None,
            "last_alert_ts": 0.0,
            "last_seen_ts": 0.0,
        })
        state["last_seen_ts"] = now

        level = _classify_bw_level(c["peak_mbps"])
        if level == "critical":
            state["warn_hits"] += 1
            state["crit_hits"] += 1
            state["recovery_hits"] = 0

            if state["crit_hits"] < consecutive_hits:
                continue

            is_escalation = state["last_level"] != "critical"
            cooldown_ok = (now - float(state["last_alert_ts"])) >= cooldown_sec
            if is_escalation or cooldown_ok:
                await kirim_ke_semua_admin(
                    _build_top_bw_alert_message(
                        name, c["rank"], "critical",
                        c["total_mbps"], c["rx_mbps"], c["tx_mbps"], c["peak_mbps"], c["peak_dir"],
                        state["crit_hits"], consecutive_hits
                    ),
                    parse_mode='HTML',
                    severity=AlertSeverity.CRITICAL,
                )
                state["last_level"] = "critical"
                state["last_alert_ts"] = now
            continue

        if level == "warning":
            state["warn_hits"] += 1
            state["crit_hits"] = 0
            state["recovery_hits"] = 0

            if state["warn_hits"] < consecutive_hits:
                continue

            first_warning = state["last_level"] is None
            repeated_warning = (
                state["last_level"] == "warning" and
                (now - float(state["last_alert_ts"])) >= cooldown_sec
            )
            if first_warning or repeated_warning:
                await kirim_ke_semua_admin(
                    _build_top_bw_alert_message(
                        name, c["rank"], "warning",
                        c["total_mbps"], c["rx_mbps"], c["tx_mbps"], c["peak_mbps"], c["peak_dir"],
                        state["warn_hits"], consecutive_hits
                    ),
                    parse_mode='HTML',
                    severity=AlertSeverity.WARNING,
                )
                state["last_level"] = "warning"
                state["last_alert_ts"] = now
            continue

        # Normal/recovery path
        state["warn_hits"] = 0
        state["crit_hits"] = 0
        state["recovery_hits"] += 1
        if state["last_level"] and state["recovery_hits"] >= recovery_hits:
            await kirim_ke_semua_admin(
                _build_top_bw_recovery_message(name),
                parse_mode='HTML',
                severity=AlertSeverity.INFO,
            )
            state["last_level"] = None
            state["last_alert_ts"] = 0.0

    # Host tidak muncul lagi di top-N -> proses recovery bertahap agar tidak sticky.
    for name, state in list(_top_bw_host_state.items()):
        if name in seen_names:
            continue
        if state.get("last_level"):
            state["warn_hits"] = 0
            state["crit_hits"] = 0
            state["recovery_hits"] = int(state.get("recovery_hits", 0)) + 1
            if state["recovery_hits"] >= recovery_hits:
                await kirim_ke_semua_admin(
                    _build_top_bw_recovery_message(name),
                    parse_mode='HTML',
                    severity=AlertSeverity.INFO,
                )
                state["last_level"] = None
                state["last_alert_ts"] = 0.0

        # Prune state host idle agar memory stabil.
        last_seen_ts = float(state.get("last_seen_ts", 0.0) or 0.0)
        if not state.get("last_level") and (now - last_seen_ts) > max(1800, cooldown_sec * 2):
            _top_bw_host_state.pop(name, None)


async def _cek_per_host_traffic(queue_list):
    """Cek per-host traffic leak dan kirim alert jika melampaui TRAFFIC_LEAK_THRESHOLD_MBPS.

    Args:
        queue_list: list of queue dicts dari get_top_queues()
    """
    if cfg.TOP_BW_ALERT_ENABLED:
        await _run_top_bw_alert_engine(queue_list)
        return

    # Legacy mode (backward-compatible) jika engine baru dimatikan.
    global _alerted_hosts_traffic
    threshold_bps = cfg.TRAFFIC_LEAK_THRESHOLD_MBPS * 1_000_000

    for q in queue_list:
        if not isinstance(q, dict):
            continue
        name = q.get('name', '')
        if not name or name in cfg.TRAFFIC_LEAK_WHITELIST:
            continue

        rx_rate = q.get('rx_rate', 0)
        tx_rate = q.get('tx_rate', 0)
        total_rate = rx_rate + tx_rate
        peak_rate = max(rx_rate, tx_rate)
        peak_dir = "RX" if rx_rate >= tx_rate else "TX"

        if peak_rate >= threshold_bps:
            if name not in _alerted_hosts_traffic:
                rx_mb = _queue_rate_to_mbps(rx_rate)
                tx_mb = _queue_rate_to_mbps(tx_rate)
                total_mb = _queue_rate_to_mbps(total_rate)
                peak_mb = _queue_rate_to_mbps(peak_rate)
                await kirim_ke_semua_admin(
                    f"🚨 <b>[TRAFFIC LEAK] {name}</b>\n\n"
                    f"Peak: <b>{peak_mb:.1f} Mbps</b> ({peak_dir}) (threshold: {cfg.TRAFFIC_LEAK_THRESHOLD_MBPS} Mbps)\n"
                    f"RX: {rx_mb:.1f} Mbps\n"
                    f"TX: {tx_mb:.1f} Mbps\n\n"
                    f"Total: {total_mb:.1f} Mbps\n"
                    f"Kemungkinan: aktivitas tidak wajar, download massal, atau kerentanan jaringan.",
                    parse_mode='HTML',
                    severity=AlertSeverity.WARNING,
                )
                _alerted_hosts_traffic.add(name)
                logger.warning(f"[TRAFFIC LEAK] {name}: peak={peak_mb:.1f} Mbps ({peak_dir}), total={total_mb:.1f} Mbps")
        else:
            _alerted_hosts_traffic.discard(name)

    # FIND-1 FIX: Batas ukuran _alerted_hosts_traffic agar tidak memory leak di legacy mode
    if len(_alerted_hosts_traffic) > _ALERTED_HOSTS_TRAFFIC_MAX:
        try:
            evict = set(list(_alerted_hosts_traffic)[:len(_alerted_hosts_traffic) - _ALERTED_HOSTS_TRAFFIC_MAX])
            _alerted_hosts_traffic.difference_update(evict)
        except Exception:
            pass


async def _record_top_queue_metrics_and_alerts():
    """Rekam top queue metrics dan evaluasi alert bandwidth per-host."""
    from mikrotik import get_top_queues

    top = await with_timeout(
        asyncio.to_thread(get_top_queues, 10),
        timeout=10,
        log_key="tasks:get_top_queues",
        warn_every_sec=300,
    )
    if top is None:
        top = []

    if top:
        queue_batch = []
        for q in top:
            if not isinstance(q, dict):
                continue
            safe_name = q.get('name', '').replace(' ', '_')[:50]
            total_rate = q.get('rx_rate', 0) + q.get('tx_rate', 0)
            queue_batch.append(('bw_' + safe_name, total_rate, q.get('name', '')))
        if queue_batch:
            await asyncio.to_thread(database.record_metrics_batch, queue_batch)

    if cfg.TOP_BW_ALERT_ENABLED or cfg.TRAFFIC_LEAK_THRESHOLD_MBPS > 0:
        await _cek_per_host_traffic(top)


async def task_monitor_logs():
    """Task 2: Monitor Logs Real-time tiap 30 detik."""
    interval = int(cfg.MONITOR_LOG_INTERVAL)
    fetch_lines = int(getattr(cfg, "MONITOR_LOG_FETCH_LINES", 100))
    logger.info(f"[INIT] Log Monitor berjalan (Interval: {interval}s)")

    _LOG_CACHE_MAX = 200
    _seen_deque = deque(maxlen=_LOG_CACHE_MAX)
    _seen_set = set()
    # B2 FIX: dict{uid: timestamp} agar cleanup berbasis waktu, bukan set yang tidak pernah bersih
    _power_events_sent = {}  # uid -> float (unix timestamp saat event dikirim)
    _POWER_EVENT_TTL = 300   # 5 menit - event yang lebih tua dari ini dianggap expired
    _api_account_last_sent = {}  # signature -> float
    _api_account_dedup_window = max(30, int(getattr(cfg, "API_ACCOUNT_DEDUP_WINDOW_SEC", 300)))
    _api_skip_users = {str(getattr(cfg, "MIKROTIK_USER", "")).strip().lower()}
    for u in getattr(cfg, "API_ACCOUNT_SKIP_USERS", []):
        if str(u).strip():
            _api_skip_users.add(str(u).strip().lower())

    def _add_seen(uid):
        if len(_seen_deque) >= _LOG_CACHE_MAX:
            evicted = _seen_deque[0]
            _seen_set.discard(evicted)
        _seen_deque.append(uid)
        _seen_set.add(uid)

    bruteforce_tracker = {}
    _BRUTEFORCE_TRACKER_TTL = int(getattr(cfg, "BRUTEFORCE_TRACKER_TTL_SEC", 600))  # default 10 menit

    # Init: baseline
    try:
        logs = await _get_router_logs_snapshot(fetch_lines, timeout=10, cache_ttl=300)
        for l in (logs or []):
            uid = f"{l['time']}|{l['message']}"
            _add_seen(uid)
    except Exception as e:
        logger.debug(f"Log baseline init error: {e}")

    while True:
        try:
            if apply_runtime_reset_if_signaled():
                _seen_deque.clear()
                _seen_set.clear()
                _power_events_sent.clear()
                _api_account_last_sent.clear()
                bruteforce_tracker.clear()
            cfg.reload_runtime_overrides(min_interval=10)
            cfg.reload_router_env(min_interval=10)
            interval = int(cfg.MONITOR_LOG_INTERVAL)
            fetch_lines = int(getattr(cfg, "MONITOR_LOG_FETCH_LINES", fetch_lines))
            if await _pause_if_api_unavailable("logs", interval):
                continue
            _api_skip_users = {str(getattr(cfg, "MIKROTIK_USER", "")).strip().lower()}
            for u in getattr(cfg, "API_ACCOUNT_SKIP_USERS", []):
                if str(u).strip():
                    _api_skip_users.add(str(u).strip().lower())
            logs = await _get_router_logs_snapshot(fetch_lines, timeout=15, cache_ttl=300)
            if logs is None:
                await _sleep_with_jitter(interval)
                continue

            new_logs = []

            now = time.time()
            # B2 FIX: Cleanup power events expired (lebih dari 5 menit)
            _power_events_sent_cleanup = {u: t for u, t in _power_events_sent.items() if now - t < _POWER_EVENT_TTL}
            _power_events_sent.clear()
            _power_events_sent.update(_power_events_sent_cleanup)
            _api_account_last_sent = {
                sig: ts for sig, ts in _api_account_last_sent.items()
                if (now - ts) < _api_account_dedup_window
            }
            trusted_autoblock_ips = _get_autoblock_trusted_ips()

            for l in logs:
                uid = f"{l.get('time', '')}|{l.get('message', '')}"
                if uid not in _seen_set:
                    msg = l.get('message', '').lower()
                    msg_text = l.get('message', '')
                    topics = l.get('topics', '')
                    topic_tokens = {t.strip().lower() for t in str(topics).split(",") if t.strip()}

                    is_bot_ip = cfg.BOT_IP in msg_text if cfg.BOT_IP else False
                    if _should_skip_api_account_log(
                        topics,
                        msg_text,
                        cfg.BOT_IP,
                        _api_account_last_sent,
                        _api_account_dedup_window,
                        now,
                        bot_usernames=_api_skip_users,
                    ):
                        _add_seen(uid)
                        continue

                    # Cek Bruteforce
                    if "login failure" in msg:
                        ip_part = _extract_login_failure_ip(msg_text)
                        if ip_part:
                            # Guardrail: IP trusted tidak boleh pernah di-auto-block.
                            if ip_part in trusted_autoblock_ips:
                                bruteforce_tracker.pop(ip_part, None)
                                logger.info("[SHIELD] Skip trusted IP %s (login failure).", ip_part)
                            else:
                                if ip_part not in bruteforce_tracker:
                                    bruteforce_tracker[ip_part] = {'count': 1, 'last_seen': time.time()}
                                else:
                                    bruteforce_tracker[ip_part]['count'] += 1
                                    bruteforce_tracker[ip_part]['last_seen'] = time.time()

                                threshold = int(getattr(cfg, "BRUTEFORCE_FAIL_THRESHOLD", 5))
                                if bruteforce_tracker[ip_part]['count'] >= threshold:
                                    try:
                                        await asyncio.to_thread(block_ip, ip_part, f"Auto Blocked by Bot (Bruteforce)")
                                        bruteforce_tracker.pop(ip_part, None)  # Bersihkan setelah diblokir

                                        # W6 FIX: Audit ke database agar ada trace permanen
                                        try:
                                            await asyncio.to_thread(
                                                database.audit_log, 0, 'monitor',
                                                '/auto-block', f"IP: {ip_part}", 'bruteforce'
                                            )
                                        except Exception as dbe:
                                            logger.debug("Gagal simpan audit auto-block: %s", dbe, exc_info=True)

                                        pesan_block = (
                                            f"🛡️ <b>[AUTO-BLOCK TRIGGERED]</b>\n"
                                            f"IP <code>{ip_part}</code> telah diblokir secara otomatis karena terdeteksi "
                                            f"mencoba Login Brute-force ke router (>= {threshold}x kegagalan)."
                                        )

                                        btn = InlineKeyboardMarkup([[
                                            InlineKeyboardButton("✅ Unban / Buka Blokir", callback_data=f"unban_{ip_part}")
                                        ]])

                                        for admin_id in cfg.ADMIN_IDS:
                                            try:
                                                await bot.send_message(chat_id=admin_id, text=pesan_block, parse_mode='HTML', reply_markup=btn)
                                            except Exception as send_err:
                                                logger.warning(
                                                    "Gagal kirim notifikasi auto-block ke admin %s: %s",
                                                    admin_id, send_err
                                                )
                                        logger.info(f"[SHIELD] IP {ip_part} blocked.")
                                    except Exception as be:
                                        logger.error(f"Gagal auto block ip {ip_part}: {be}")

                    # Deteksi event power/UPS/voltage
                    is_power_event = any(kw in msg for kw in ['power', 'voltage', 'ups', 'poe'])
                    is_queue_change = _is_queue_change_log(topics, msg_text)
                    is_dhcp_pool_exhausted = _is_dhcp_pool_exhausted_log(topics, msg_text)

                    # Filter topik penting untuk alert log standar
                    if (topic_tokens.intersection({'error', 'critical', 'warning', 'account'}) or is_queue_change) and not is_dhcp_pool_exhausted:
                        if not is_bot_ip:
                            new_logs.append(l)
                            if is_power_event:
                                # Tandai sebagai sudah masuk new_logs (jangan kirim duplikat via power event handler)
                                _power_events_sent[uid] = time.time()

                    # Kirim power event HANYA jika belum masuk new_logs
                    if is_power_event and uid not in _power_events_sent and not is_bot_ip:
                        _power_events_sent[uid] = time.time()
                        await kirim_ke_semua_admin(
                            f"⚡ <b>[POWER EVENT]</b>\n\n"
                            f"⏰ {l.get('time', '')}\n"
                            f"📝 <code>{msg_text}</code>\n\n"
                            f"Terdeteksi event terkait power/UPS/voltage.",
                            parse_mode='HTML'
                        )
                        logger.info(f"[SENT] Power event: {msg_text[:50]}")

                    _add_seen(uid)

            # FIND-5 FIX: Prune bruteforce_tracker entries yang sudah expired (TTL-based).
            # Mencegah memory leak saat ribuan IP mencoba tapi tidak pernah capai threshold.
            _BRUTEFORCE_TRACKER_TTL = int(getattr(cfg, "BRUTEFORCE_TRACKER_TTL_SEC", 600))
            expired_ips = [
                ip for ip, state in list(bruteforce_tracker.items())
                if (now - float(state.get('last_seen', now))) > _BRUTEFORCE_TRACKER_TTL
            ]
            for ip in expired_ips:
                bruteforce_tracker.pop(ip, None)
                logger.debug("[bruteforce_tracker] Entry expired (TTL=%ss) di-prune: %s", _BRUTEFORCE_TRACKER_TTL, ip)

            # Kirim alert log umum
            if new_logs:
                chunks = _build_router_log_chunks(new_logs)

                for admin_id in cfg.ADMIN_IDS:
                    for pesan in chunks:
                        try:
                            await bot.send_message(chat_id=admin_id, text=pesan, parse_mode='HTML')
                        except Exception as send_err:
                            logger.warning("Gagal forward log router ke admin %s: %s", admin_id, send_err)
                logger.debug(f"Forwarded {len(new_logs)} log entries")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[ERR] Task Log Monitor: {e}")

        await _sleep_with_jitter(interval)


async def task_monitor_dhcp_arp():
    """Task 4: Memantau batasan pemakaian DHCP dan Konflik MAC Anomaly."""
    interval = 300
    logger.info(f"[INIT] DHCP & ARP Monitor berjalan (Interval: {interval}s)")

    alerted_dhcp = False
    alerted_macs = set()
    open_conflict_incidents = set()

    while True:
        try:
            if apply_runtime_reset_if_signaled():
                alerted_dhcp = False
                alerted_macs.clear()
                open_conflict_incidents.clear()
            cfg.reload_runtime_overrides(min_interval=10)
            cfg.reload_router_env(min_interval=10)
            if await _pause_if_api_unavailable("dhcp_arp", interval):
                continue
            # 1. DHCP Pool Monitor
            pool_size = await _get_dhcp_pool_capacity_snapshot()
            if pool_size > 0:
                bound = await _get_dhcp_usage_snapshot()
                pct = (bound / pool_size) * 100

                try:
                    await asyncio.to_thread(database.record_metric, 'dhcp_usage_pct', pct)
                except Exception as metric_err:
                    logger.debug("Gagal simpan metric dhcp_usage_pct: %s", metric_err, exc_info=True)

                if pct >= cfg.DHCP_ALERT_THRESHOLD and not alerted_dhcp:
                    alerted_dhcp = True
                    msg = (f"⚠️ <b>[DHCP POOL WARNING]</b>\n\n"
                           f"Kapasitas IP hampir penuh!\n"
                           f"Terpakai: {bound}/{pool_size} ({pct:.0f}%)\n"
                           f"Segera audit manual atau kosongkan lease agar klien baru bisa menyambung.")
                    await kirim_ke_semua_admin(msg, parse_mode='HTML')

                elif pct < cfg.DHCP_ALERT_THRESHOLD - 10 and alerted_dhcp:
                    alerted_dhcp = False
                    msg = (f"✅ <b>[DHCP POOL RECOVERY]</b>\n\n"
                           f"Kapasitas DHCP sudah kembali aman.\n"
                           f"Terpakai: {bound}/{pool_size} ({pct:.0f}%)")
                    await kirim_ke_semua_admin(msg, parse_mode='HTML', severity=AlertSeverity.INFO)

            # 2. IP Conflict (MAC Anomaly) Monitor
            if cfg.CRITICAL_MACS:
                anomalies = await with_timeout(
                    asyncio.to_thread(get_arp_anomalies, cfg.CRITICAL_MACS),
                    timeout=10,
                    default=[],
                    log_key="tasks:get_arp_anomalies",
                    warn_every_sec=300,
                )
                current_anomalies_ips = set(a['ip'] for a in anomalies)

                for a in anomalies:
                    ip = a['ip']
                    if ip not in alerted_macs:
                        alerted_macs.add(ip)
                        msg = (f"⚠️ <b>[IP CONFLICT SUSPECT]</b>\n\n"
                               f"Host kritis <b>{ip}</b> terdeteksi mengalami perubahan MAC Address di tabel ARP MikroTik!\n\n"
                               f"Expected: <code>{a['expected_mac']}</code>\n"
                               f"Found: <code>{a['current_mac']}</code>\n\n"
                               f"<i>Saran: Cek apabila ada IP statik liar yang nyempil, loop jaringan, atau penggantian NIC.</i>")
                        await kirim_ke_semua_admin(msg, parse_mode='HTML')
                        await asyncio.to_thread(
                            database.log_incident_down,
                            ip,
                            "🟠 IP CONFLICT SUSPECT",
                            f"Found MAC {a['current_mac']} instead of {a['expected_mac']}",
                            "dhcp",
                        )
                        open_conflict_incidents.add(ip)

                resolved = alerted_macs - current_anomalies_ips
                for ip in resolved:
                    alerted_macs.remove(ip)
                    if ip in open_conflict_incidents:
                        await asyncio.to_thread(database.log_incident_up, ip)
                        open_conflict_incidents.remove(ip)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[ERR] Task DHCP/ARP Monitor: {e}")

        await _sleep_with_jitter(interval, max_jitter=1.0)


# ============================================
# RX PACKET ANOMALY DETECTION ENGINE
# Mendeteksi lonjakan RX packet/s abnormal pada interface
# (terutama local/bridge) yang bisa jadi indikasi:
# - Broadcast/ARP storm, device flooding
# - IP 0.0.0.0 memakan RX packet banyak
# ============================================

def _classify_rx_anomaly_level(rx_pps):
    """Klasifikasi level anomali berdasarkan RX packets-per-second."""
    crit = int(max(cfg.RX_ANOMALY_CRIT_PPS, cfg.RX_ANOMALY_WARN_PPS))
    warn = int(cfg.RX_ANOMALY_WARN_PPS)
    if rx_pps >= crit:
        return "critical"
    if rx_pps >= warn:
        return "warning"
    return None


def _format_pps(pps):
    """Format packets-per-second ke satuan yang mudah dibaca."""
    try:
        value = float(pps or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M pps"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K pps"
    return f"{int(value)} pps"


async def _identify_rx_anomaly_sources():
    """Coba identifikasi sumber RX anomali dari top queue consumers."""
    sources = []
    try:
        from mikrotik import get_top_queues
        top = await with_timeout(
            asyncio.to_thread(get_top_queues, 5),
            timeout=8,
            log_key="tasks:rx_anomaly:get_top_queues",
            warn_every_sec=600,
        )
        if top:
            for q in top[:5]:
                if not isinstance(q, dict):
                    continue
                name = q.get('name', '?')
                target = q.get('target', '')
                rx_rate = q.get('rx_rate', 0)
                tx_rate = q.get('tx_rate', 0)
                if rx_rate <= 0 and tx_rate <= 0:
                    continue
                # Ambil IP target dari queue
                ip = None
                if target:
                    raw_ip = target.split('/')[0].strip() if '/' in target else target.strip()
                    if raw_ip:
                        try:
                            ipaddress.ip_address(raw_ip)
                            ip = raw_ip
                        except ValueError:
                            pass
                sources.append({
                    'name': name,
                    'ip': ip,
                    'rx_rate': rx_rate,
                    'tx_rate': tx_rate,
                    'rx_fmt': rx_rate / 1_000_000,
                    'tx_fmt': tx_rate / 1_000_000,
                })
    except Exception as e:
        logger.debug("Gagal identifikasi sumber RX anomali: %s", e)

    return sources


def _build_rx_anomaly_alert_message(iface_name, level, rx_pps, tx_pps, rx_bps, tx_bps, hits, threshold_hits, sources):
    """Bangun pesan alert RX anomaly."""
    from mikrotik.queue import format_rate_bps

    lvl = "CRITICAL" if level == "critical" else "WARNING"
    emoji = "🔴" if level == "critical" else "🟡"

    msg = (
        f"{emoji} <b>[RX PACKET ANOMALY — {lvl}]</b>\n\n"
        f"Interface: <b>{iface_name}</b>\n"
        f"RX Packets: <b>{_format_pps(rx_pps)}</b>\n"
        f"TX Packets: {_format_pps(tx_pps)}\n"
        f"RX Rate: {format_rate_bps(rx_bps)}\n"
        f"TX Rate: {format_rate_bps(tx_bps)}\n"
        f"Threshold: Warn={_format_pps(cfg.RX_ANOMALY_WARN_PPS)} / Crit={_format_pps(cfg.RX_ANOMALY_CRIT_PPS)}\n"
        f"Observed: {hits}x berturut-turut (threshold: {threshold_hits}x)\n\n"
    )

    if sources:
        msg += "👥 <b>Kemungkinan Sumber:</b>\n"
        for idx, s in enumerate(sources[:5], 1):
            ip_info = f" ({s['ip']})" if s.get('ip') and s['ip'] != '0.0.0.0' else ""
            rx_mb = s.get('rx_fmt', 0)
            tx_mb = s.get('tx_fmt', 0)
            msg += f"  {idx}. <b>{s['name']}</b>{ip_info} — RX: {rx_mb:.1f} Mbps | TX: {tx_mb:.1f} Mbps\n"
        msg += "\n"
    else:
        msg += "⚠️ Tidak dapat mengidentifikasi sumber spesifik.\n\n"

    msg += (
        "<i>Kemungkinan: broadcast/ARP storm, device flooding, "
        "loop jaringan, atau perangkat tanpa IP (0.0.0.0).</i>"
    )
    return msg


def _build_rx_anomaly_recovery_message(iface_name):
    return f"✅ <b>[RX PACKET RECOVERY] {iface_name}</b>\n\nRX Packet rate kembali normal."


def _update_rx_packet_counter_cache(interfaces):
    """Update cache packet counter dari get_interfaces() untuk fallback delta detection."""
    now = time.time()
    for iface in (interfaces or []):
        name = str(iface.get('name', '')).strip()
        if not name:
            continue
        _rx_packet_counter_cache[name] = {
            "rx_packet": int(iface.get('rx_packet', 0) or 0),
            "tx_packet": int(iface.get('tx_packet', 0) or 0),
            "ts": now,
        }


def _estimate_pps_from_counter_delta(iface_name):
    """Estimasi RX/TX pps dari delta interface packet counter antara 2 snapshot.

    Return (rx_pps, tx_pps) atau None jika tidak bisa dihitung.
    """
    current = _rx_packet_counter_cache.get(iface_name)
    if not current:
        return None

    prev_key = f"_prev_{iface_name}"
    prev = _rx_packet_counter_cache.get(prev_key)
    # Simpan current sebagai prev untuk siklus berikutnya.
    _rx_packet_counter_cache[prev_key] = dict(current)

    if not prev:
        return None

    dt = current["ts"] - prev["ts"]
    if dt <= 0:
        return None

    rx_delta = current["rx_packet"] - prev["rx_packet"]
    tx_delta = current["tx_packet"] - prev["tx_packet"]
    # Counter wrap-around atau reset: abaikan.
    if rx_delta < 0 or tx_delta < 0:
        return None

    return (int(rx_delta / dt), int(tx_delta / dt))


async def _run_rx_anomaly_detection(active_ifaces, traffic_results, all_interfaces=None):
    """Engine stateful untuk deteksi anomali RX Packet pada interface yang dimonitor.

    Args:
        active_ifaces: list interface yang di-query traffic-nya.
        traffic_results: list hasil query traffic (bisa None/Exception saat timeout).
        all_interfaces: snapshot semua interface dari get_interfaces() untuk fallback
                        packet counter delta saat monitor-traffic timeout.
    """
    global _rx_anomaly_state
    now = time.time()
    # Case-insensitive watch list agar match nama interface di router (misal LOCAL vs local)
    watch_ifaces = {x.lower() for x in (getattr(cfg, 'RX_ANOMALY_WATCH_IFACE', ['local']) or ['local'])}
    consecutive_hits = max(1, int(cfg.RX_ANOMALY_CONSECUTIVE_HITS))
    recovery_hits = max(1, int(cfg.RX_ANOMALY_RECOVERY_HITS))
    cooldown_sec = max(0, int(cfg.RX_ANOMALY_COOLDOWN_SEC))

    # Update packet counter cache dari interface snapshot untuk fallback.
    if all_interfaces:
        _update_rx_packet_counter_cache(all_interfaces)

    seen_ifaces = set()

    for iface, traffic in zip(active_ifaces, traffic_results):
        iface_name = str(iface.get('name', '')).strip()
        if not iface_name:
            continue

        # Hanya monitor interface yang masuk watch list (case-insensitive)
        if watch_ifaces and iface_name.lower() not in watch_ifaces:
            continue

        # Saat traffic timeout/error: pertahankan state counter, jangan reset.
        # Tandai interface sebagai seen agar prune logic tidak mereset counter.
        if isinstance(traffic, Exception) or not traffic:
            seen_ifaces.add(iface_name)
            # Fallback: estimasi pps dari interface counter delta.
            fallback = _estimate_pps_from_counter_delta(iface_name)
            if fallback:
                rx_pps_est, tx_pps_est = fallback
                level_est = _classify_rx_anomaly_level(rx_pps_est)
                if level_est:
                    logger.info(
                        "[RX_ANOMALY] monitor-traffic timeout untuk %s, "
                        "fallback counter delta: rx=%s pps, tx=%s pps → %s",
                        iface_name, rx_pps_est, tx_pps_est, level_est,
                    )
                    # Gunakan estimasi counter delta sebagai proxy traffic data.
                    traffic = {
                        'rx_pps': rx_pps_est,
                        'tx_pps': tx_pps_est,
                        'rx_bps': 0,
                        'tx_bps': 0,
                    }
                else:
                    logger.debug(
                        "[RX_ANOMALY] timeout %s, fallback counter delta normal: rx=%s tx=%s pps",
                        iface_name, rx_pps_est, tx_pps_est,
                    )
                    continue
            else:
                # Tidak ada fallback data: pertahankan counter, skip evaluasi siklus ini.
                logger.debug("[RX_ANOMALY] timeout %s, belum ada counter delta, state dipertahankan.", iface_name)
                continue

        seen_ifaces.add(iface_name)
        rx_pps = int(traffic.get('rx_pps', 0) or 0)
        tx_pps = int(traffic.get('tx_pps', 0) or 0)
        rx_bps = int(traffic.get('rx_bps', 0) or 0)
        tx_bps = int(traffic.get('tx_bps', 0) or 0)

        state = _rx_anomaly_state.setdefault(iface_name, {
            "warn_hits": 0,
            "crit_hits": 0,
            "recovery_hits": 0,
            "last_level": None,
            "last_alert_ts": 0.0,
            "last_seen_ts": 0.0,
        })
        state["last_seen_ts"] = now

        level = _classify_rx_anomaly_level(rx_pps)

        if level == "critical":
            state["warn_hits"] += 1
            state["crit_hits"] += 1
            state["recovery_hits"] = 0

            if state["crit_hits"] < consecutive_hits:
                continue

            is_escalation = state["last_level"] != "critical"
            cooldown_ok = (now - float(state["last_alert_ts"])) >= cooldown_sec
            if is_escalation or cooldown_ok:
                sources = await _identify_rx_anomaly_sources()
                msg = _build_rx_anomaly_alert_message(
                    iface_name, "critical", rx_pps, tx_pps, rx_bps, tx_bps,
                    state["crit_hits"], consecutive_hits, sources
                )
                # Bangun tombol block untuk sumber yang punya IP valid
                buttons = []
                for s in sources[:3]:
                    ip = s.get('ip')
                    if ip and ip != '0.0.0.0':
                        buttons.append([
                            InlineKeyboardButton(
                                f"🚫 Block {s['name']} ({ip})",
                                callback_data=f"rxblock_{ip}"
                            )
                        ])
                reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

                for admin_id in cfg.ADMIN_IDS:
                    try:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=f"🔴 [{now_timestamp()}] {msg}",
                            parse_mode='HTML',
                            reply_markup=reply_markup,
                        )
                    except Exception as send_err:
                        logger.warning("Gagal kirim RX anomaly alert ke admin %s: %s", admin_id, send_err)

                state["last_level"] = "critical"
                state["last_alert_ts"] = now
            continue

        if level == "warning":
            state["warn_hits"] += 1
            state["crit_hits"] = 0
            state["recovery_hits"] = 0

            if state["warn_hits"] < consecutive_hits:
                continue

            first_warning = state["last_level"] is None
            repeated_warning = (
                state["last_level"] == "warning" and
                (now - float(state["last_alert_ts"])) >= cooldown_sec
            )
            if first_warning or repeated_warning:
                sources = await _identify_rx_anomaly_sources()
                msg = _build_rx_anomaly_alert_message(
                    iface_name, "warning", rx_pps, tx_pps, rx_bps, tx_bps,
                    state["warn_hits"], consecutive_hits, sources
                )
                buttons = []
                for s in sources[:3]:
                    ip = s.get('ip')
                    if ip and ip != '0.0.0.0':
                        buttons.append([
                            InlineKeyboardButton(
                                f"🚫 Block {s['name']} ({ip})",
                                callback_data=f"rxblock_{ip}"
                            )
                        ])
                reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

                for admin_id in cfg.ADMIN_IDS:
                    try:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=f"🟡 [{now_timestamp()}] {msg}",
                            parse_mode='HTML',
                            reply_markup=reply_markup,
                        )
                    except Exception as send_err:
                        logger.warning("Gagal kirim RX anomaly warning ke admin %s: %s", admin_id, send_err)

                state["last_level"] = "warning"
                state["last_alert_ts"] = now
            continue

        # Normal/recovery path
        state["warn_hits"] = 0
        state["crit_hits"] = 0
        state["recovery_hits"] += 1
        if state["last_level"] and state["recovery_hits"] >= recovery_hits:
            msg = _build_rx_anomaly_recovery_message(iface_name)
            await kirim_ke_semua_admin(msg, parse_mode='HTML', severity=AlertSeverity.INFO)
            state["last_level"] = None
            state["last_alert_ts"] = 0.0

    # Prune state interface yang sudah tidak aktif/tidak dimonitor lagi
    for iface_name, state in list(_rx_anomaly_state.items()):
        if iface_name in seen_ifaces:
            continue
        if state.get("last_level"):
            state["warn_hits"] = 0
            state["crit_hits"] = 0
            state["recovery_hits"] = int(state.get("recovery_hits", 0)) + 1
            if state["recovery_hits"] >= recovery_hits:
                msg = _build_rx_anomaly_recovery_message(iface_name)
                await kirim_ke_semua_admin(msg, parse_mode='HTML', severity=AlertSeverity.INFO)
                state["last_level"] = None
                state["last_alert_ts"] = 0.0
        # Prune idle entries
        last_seen_ts = float(state.get("last_seen_ts", 0.0) or 0.0)
        if not state.get("last_level") and (now - last_seen_ts) > max(1800, cooldown_sec * 2):
            _rx_anomaly_state.pop(iface_name, None)


def now_timestamp():
    """Format timestamp sekarang untuk alert message."""
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")


# ============================================
# B10-RC1: TRAFFIC MONITOR TASK (interval: 60 detik)
# Dipisah dari task_monitor_system agar data traffic
# direkam 5x lebih sering -> chart jauh lebih granular
# ============================================


async def task_monitor_traffic():
    """Task 5: Rekam traffic metrics semua interface setiap 60 detik.

    Mengganti blok traffic recording yang sebelumnya ada di task_monitor_system()
    (interval 5 menit). Dengan interval 60 detik, chart traffic memiliki resolusi
    jauh lebih tinggi dan lebih representatif terhadap kondisi jaringan aktual.
    """
    _TRAFFIC_INTERVAL = 60  # detik - 5x lebih sering dari system task (5 menit)
    logger.info(f"[INIT] Traffic Monitor berjalan (Interval: {_TRAFFIC_INTERVAL}s)")

    while True:
        try:
            apply_runtime_reset_if_signaled()
            cfg.reload_runtime_overrides(min_interval=10)
            cfg.reload_router_env(min_interval=10)
            if await _pause_if_api_unavailable("traffic", _TRAFFIC_INTERVAL):
                continue
            interfaces = await _get_interfaces_snapshot(
                cache_ttl=max(_TRAFFIC_INTERVAL * 3, 180),
                timeout=10,
                log_key="tasks:traffic:get_interfaces",
            )
            if not interfaces:
                await _sleep_with_jitter(_TRAFFIC_INTERVAL)
                continue

            active_ifaces = [
                iface for iface in interfaces
                if iface['name'] not in cfg.MONITOR_IGNORE_IFACE and iface['running']
            ]
            if not active_ifaces:
                await _sleep_with_jitter(_TRAFFIC_INTERVAL)
                continue

            traffic_results = await _collect_interface_traffic(active_ifaces, "tasks:traffic:get_traffic")

            # Kumpulkan batch dan simpan sekali ke DB
            batch = []
            for iface, traffic in zip(active_ifaces, traffic_results):
                if isinstance(traffic, Exception) or not traffic:
                    continue
                batch.extend([
                    ('traffic_rx_bps', traffic.get('rx_bps', 0), iface['name']),
                    ('traffic_tx_bps', traffic.get('tx_bps', 0), iface['name']),
                ])

            if batch:
                await asyncio.to_thread(database.record_metrics_batch, batch)
                logger.debug(f"Traffic: {len(batch) // 2} interface(s) direkam ke DB")

            # RX Packet Anomaly Detection
            # Interface di RX watch list mungkin ada di MONITOR_IGNORE_IFACE
            # (user ingin skip traffic recording tapi tetap deteksi anomali).
            # Kumpulkan traffic interface tsb secara terpisah.
            if cfg.RX_ANOMALY_ENABLED:
                try:
                    rx_watch_set = {x.lower() for x in (getattr(cfg, 'RX_ANOMALY_WATCH_IFACE', ['local']) or ['local'])}
                    active_names_lower = {str(i.get('name', '')).strip().lower() for i in active_ifaces}
                    rx_extra_ifaces = [
                        iface for iface in interfaces
                        if iface['running']
                        and str(iface.get('name', '')).strip().lower() in rx_watch_set
                        and str(iface.get('name', '')).strip().lower() not in active_names_lower
                    ]
                    if rx_extra_ifaces:
                        # Timeout lebih panjang (20s) karena interface yang sedang anomali
                        # justru paling sering menyebabkan monitor-traffic lambat.
                        rx_extra_traffic = await _collect_interface_traffic(
                            rx_extra_ifaces, "tasks:traffic:rx_anomaly", timeout=20
                        )
                        all_rx_ifaces = list(active_ifaces) + rx_extra_ifaces
                        all_rx_traffic = list(traffic_results) + list(rx_extra_traffic)
                    else:
                        all_rx_ifaces = active_ifaces
                        all_rx_traffic = traffic_results
                    await _run_rx_anomaly_detection(
                        all_rx_ifaces, all_rx_traffic, all_interfaces=interfaces
                    )
                except Exception as rx_err:
                    logger.debug(f"RX anomaly detection error: {rx_err}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[ERR] Task Traffic Monitor: {e}")

        await _sleep_with_jitter(_TRAFFIC_INTERVAL)


async def task_monitor_top_bandwidth():
    """Task 5b: Poll top bandwidth queue lebih rapat agar burst pendek tetap terdeteksi."""
    interval = max(5, int(getattr(cfg, "TOP_BW_ALERT_INTERVAL", 15)))
    logger.info(f"[INIT] Top BW Alert Monitor berjalan (Interval: {interval}s)")

    while True:
        try:
            apply_runtime_reset_if_signaled()
            cfg.reload_runtime_overrides(min_interval=10)
            cfg.reload_router_env(min_interval=10)
            interval = max(5, int(getattr(cfg, "TOP_BW_ALERT_INTERVAL", interval)))
            if await _pause_if_api_unavailable("top_bw", interval):
                continue

            if cfg.TOP_BW_ALERT_ENABLED or cfg.TRAFFIC_LEAK_THRESHOLD_MBPS > 0:
                try:
                    await _record_top_queue_metrics_and_alerts()
                except Exception as eq:
                    logger.debug(f"Top queue metrics error: {eq}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[ERR] Task Top BW Monitor: {e}")

        await _sleep_with_jitter(interval)


async def task_monitor_alert_maintenance():
    """Task 6: Escalation + digest loop (independen dari system monitor)."""
    interval = 20
    logger.info(f"[INIT] Alert Maintenance berjalan (Interval: {interval}s)")
    while True:
        try:
            apply_runtime_reset_if_signaled()
            cfg.reload_runtime_overrides(min_interval=10)
            await check_escalation()
            await send_digest()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[ERR] Task Alert Maintenance: {e}")
        await _sleep_with_jitter(interval)

