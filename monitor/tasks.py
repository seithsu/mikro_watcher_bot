# ============================================
# MONITOR/TASKS - Monitor Tasks (System, Logs, DHCP/ARP)
# ============================================

import time
import asyncio
import logging
import re
import socket
import ipaddress
from collections import deque

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import core.config as cfg
from mikrotik import (
    get_status, get_interfaces, get_traffic, get_mikrotik_log,
    get_dhcp_usage_count, get_arp_anomalies, block_ip, _pool
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
_INTERFACES_CACHE = {"ts": 0.0, "items": []}
_DHCP_USAGE_CACHE = {"ts": 0.0, "bound": 0}
_ROUTER_LOG_CACHE = {"ts": 0.0, "lines": []}
_TRAFFIC_QUERY_MIN_CONCURRENCY = 1
_TRAFFIC_QUERY_MAX_CONCURRENCY = 3
_BACKGROUND_LOG_FETCH_CAP = 60
_LAST_RUNTIME_RESET_SEEN = 0.0


def clear_runtime_state():
    """Reset cache/state in-memory task monitor."""
    global _LAST_RUNTIME_RESET_SEEN
    _LOCAL_IP_CACHE["ips"] = set()
    _LOCAL_IP_CACHE["ts"] = 0.0
    _API_HEALTH_CACHE["ts"] = 0.0
    _API_HEALTH_CACHE["healthy"] = True
    _API_HEALTH_CACHE["last_error"] = ""
    _API_PAUSE_LOG_TS.clear()
    _INTERFACES_CACHE["ts"] = 0.0
    _INTERFACES_CACHE["items"] = []
    _DHCP_USAGE_CACHE["ts"] = 0.0
    _DHCP_USAGE_CACHE["bound"] = 0
    _ROUTER_LOG_CACHE["ts"] = 0.0
    _ROUTER_LOG_CACHE["lines"] = []
    _alerted_hosts_traffic.clear()
    _top_bw_host_state.clear()
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
    now = time.time()
    if (now - float(_API_HEALTH_CACHE.get("ts", 0.0))) < max(1, int(cache_ttl)):
        return bool(_API_HEALTH_CACHE.get("healthy", False)), str(_API_HEALTH_CACHE.get("last_error", ""))

    diag = await with_timeout(
        asyncio.to_thread(_pool.connection_diagnostics),
        timeout=8,
        default={},
        log_key="tasks:connection_diagnostics",
        warn_every_sec=300,
    )
    healthy = bool(isinstance(diag, dict) and diag.get("healthy", False))
    last_error = str((diag or {}).get("last_error", "")).strip() if isinstance(diag, dict) else ""
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


async def _get_router_logs_snapshot(fetch_lines, timeout=15, cache_ttl=180):
    """Ambil tail log router dengan cap background dan fallback cache last-good."""
    requested = max(1, int(fetch_lines))
    effective_lines = min(requested, _BACKGROUND_LOG_FETCH_CAP)
    logs = await with_timeout(
        asyncio.to_thread(get_mikrotik_log, effective_lines),
        timeout=timeout,
        default=None,
        log_key="tasks:get_mikrotik_log",
        warn_every_sec=300,
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
    await asyncio.sleep(interval)
    return True


def _traffic_query_concurrency():
    """Batasi query monitor-traffic agar tidak memicu burst koneksi ke RouterOS."""
    try:
        limit = int(getattr(cfg, "MIKROTIK_MAX_CONNECTIONS", 8) or 8) // 4
    except (TypeError, ValueError):
        limit = 2
    return max(_TRAFFIC_QUERY_MIN_CONCURRENCY, min(_TRAFFIC_QUERY_MAX_CONCURRENCY, limit or 2))


async def _collect_interface_traffic(active_ifaces, log_prefix):
    """Kumpulkan traffic interface dengan concurrency terbatas untuk menekan timeout."""
    if not active_ifaces:
        return []

    semaphore = asyncio.Semaphore(_traffic_query_concurrency())

    async def _fetch(iface):
        async with semaphore:
            return await with_timeout(
                asyncio.to_thread(get_traffic, iface['name']),
                timeout=10,
                log_key=f"{log_prefix}:{iface['name']}",
                warn_every_sec=300,
            )

    tasks = [_fetch(iface) for iface in active_ifaces]
    return await asyncio.gather(*tasks, return_exceptions=True)


def _extract_login_failure_ip(message_text):
    """Ekstrak source IP dari log 'login failure ... from X.X.X.X'."""
    msg = str(message_text or "").lower()
    match = re.search(r"\bfrom\s+(\d{1,3}(?:\.\d{1,3}){3})\b", msg)
    if not match:
        return None
    return _normalize_ipv4(match.group(1))


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
                await asyncio.sleep(interval)
                continue

            await cek_cpu_ram(info)
            await cek_disk(info)
            # W2 FIX: Ambil interfaces sekali dan reuse untuk cek_interface + traffic check
            _cached_interfaces = await _get_interfaces_snapshot(cache_ttl=max(interval, 180))
            await cek_interface(_cached_interfaces)
            await cek_uptime_anomaly(info)
            await cek_firmware()
            await cek_vpn_tunnels()

            # Cek traffic alert threshold menggunakan cached interfaces
            if cfg.TRAFFIC_THRESHOLD_MBPS > 0 and _cached_interfaces:
                threshold_bps = cfg.TRAFFIC_THRESHOLD_MBPS * 1_000_000
                active_ifaces = [
                    iface for iface in _cached_interfaces
                    if iface['name'] not in cfg.MONITOR_IGNORE_IFACE and iface['running']
                ]
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
                            await kirim_ke_semua_admin(
                                f"⚠️ <b>TRAFFIC ALERT</b>\n\n"
                                f"Interface: <b>{iface['name']}</b>\n"
                                f"Traffic melampaui threshold ({cfg.TRAFFIC_THRESHOLD_MBPS} Mbps)\n"
                                f"RX: {rx_mb:.1f} Mbps\nTX: {tx_mb:.1f} Mbps",
                                parse_mode='HTML'
                            )
                            _last_alerts[alert_key] = True
                    else:
                        _last_alerts[f"traffic_{iface['name']}"] = False

            # Record top queue metrics + cek per-host traffic leak
            try:
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
                        # Pastikan q adalah dict  (fix logika getattr yang salah)
                        if not isinstance(q, dict):
                            continue
                        safe_name = q.get('name', '').replace(' ', '_')[:50]
                        total_rate = q.get('rx_rate', 0) + q.get('tx_rate', 0)
                        queue_batch.append(('bw_' + safe_name, total_rate, q.get('name', '')))
                    if queue_batch:
                        await asyncio.to_thread(database.record_metrics_batch, queue_batch)

                # Per-host traffic leak / top bandwidth alert
                if cfg.TOP_BW_ALERT_ENABLED or cfg.TRAFFIC_LEAK_THRESHOLD_MBPS > 0:
                    await _cek_per_host_traffic(top)
            except Exception as eq:
                logger.debug(f"Top queue metrics error: {eq}")

        except Exception as e:
            logger.error(f"[ERR] System Monitor: {e}")
            now = time.time()
            if now - _last_error_alert_time >= _ERROR_ALERT_COOLDOWN:
                await kirim_ke_semua_admin(
                    f"[ALERT] Router Monitor Error!\n{str(e)[:100]}"
                )
                _last_error_alert_time = now

        await asyncio.sleep(interval)


# ============ PER-HOST TRAFFIC LEAK DETECTION ============

_alerted_hosts_traffic = set()  # Tracking host yang sudah di-alert traffic leak
_top_bw_host_state = {}         # host -> state dict (engine top bandwidth baru)


def _classify_bw_level(total_mbps):
    """Klasifikasi level bandwidth berdasarkan threshold warning/critical."""
    warn = float(cfg.TOP_BW_ALERT_WARN_MBPS)
    crit = float(max(cfg.TOP_BW_ALERT_CRIT_MBPS, cfg.TOP_BW_ALERT_WARN_MBPS))
    if total_mbps >= crit:
        return "critical"
    if total_mbps >= warn:
        return "warning"
    return None


def _build_top_bw_alert_message(host_name, rank, level, total_mbps, rx_mbps, tx_mbps, hits):
    lvl = "CRITICAL" if level == "critical" else "WARNING"
    return (
        f"🚨 <b>[TOP BW {lvl}] {host_name} (#{rank})</b>\n\n"
        f"Total: <b>{total_mbps:.1f} Mbps</b>\n"
        f"RX: {rx_mbps:.1f} Mbps | TX: {tx_mbps:.1f} Mbps\n"
        f"Warn/Crit: {cfg.TOP_BW_ALERT_WARN_MBPS}/{cfg.TOP_BW_ALERT_CRIT_MBPS} Mbps\n"
        f"Consecutive hits: {hits}x"
    )


def _build_top_bw_recovery_message(host_name):
    return f"✅ <b>[TOP BW RECOVERY] {host_name}</b>\n\nTraffic kembali normal."


def _normalize_top_bw_candidates(queue_list):
    """Normalisasi queue list menjadi kandidat terurut untuk evaluasi top-N."""
    candidates = []
    for q in queue_list:
        if not isinstance(q, dict):
            continue
        name = str(q.get('name', '')).strip()
        if not name:
            continue
        if name in cfg.TRAFFIC_LEAK_WHITELIST:
            continue

        rx_bps = float(q.get('rx_rate', 0) or 0)
        tx_bps = float(q.get('tx_rate', 0) or 0)
        total_bps = rx_bps + tx_bps
        if total_bps <= 0:
            continue

        rx_mbps = rx_bps / 1_000_000
        tx_mbps = tx_bps / 1_000_000
        total_mbps = total_bps / 1_000_000
        # Filter asimetris/noise: minimal salah satu sisi melewati ambang min.
        if rx_mbps < cfg.TOP_BW_ALERT_MIN_RX_MBPS and tx_mbps < cfg.TOP_BW_ALERT_MIN_TX_MBPS:
            continue

        candidates.append({
            "name": name,
            "rx_mbps": rx_mbps,
            "tx_mbps": tx_mbps,
            "total_mbps": total_mbps,
        })

    candidates.sort(key=lambda x: x["total_mbps"], reverse=True)
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

        level = _classify_bw_level(c["total_mbps"])
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
                        c["total_mbps"], c["rx_mbps"], c["tx_mbps"], state["crit_hits"]
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
                        c["total_mbps"], c["rx_mbps"], c["tx_mbps"], state["warn_hits"]
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

        if total_rate >= threshold_bps:
            if name not in _alerted_hosts_traffic:
                rx_mb = rx_rate / 1_000_000
                tx_mb = tx_rate / 1_000_000
                total_mb = total_rate / 1_000_000
                await kirim_ke_semua_admin(
                    f"🚨 <b>[TRAFFIC LEAK] {name}</b>\n\n"
                    f"Total: <b>{total_mb:.1f} Mbps</b> (threshold: {cfg.TRAFFIC_LEAK_THRESHOLD_MBPS} Mbps)\n"
                    f"RX: {rx_mb:.1f} Mbps\n"
                    f"TX: {tx_mb:.1f} Mbps\n\n"
                    f"Kemungkinan: aktivitas tidak wajar, download massal, atau kerentanan jaringan.",
                    parse_mode='HTML',
                    severity=AlertSeverity.WARNING,
                )
                _alerted_hosts_traffic.add(name)
                logger.warning(f"[TRAFFIC LEAK] {name}: {total_mb:.1f} Mbps")
        else:
            _alerted_hosts_traffic.discard(name)


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
            logs = await _get_router_logs_snapshot(fetch_lines, timeout=15)
            if logs is None:
                await asyncio.sleep(interval)
                continue

            new_logs = []

            # Cleanup tracker brute force > 60 detik
            now = time.time()
            for ip in list(bruteforce_tracker.keys()):
                 if now - bruteforce_tracker[ip]['last_seen'] > 60:
                       del bruteforce_tracker[ip]

            # B2 FIX: Cleanup power events expired (lebih dari 5 menit)
            now_t = time.time()
            _power_events_sent_cleanup = {u: t for u, t in _power_events_sent.items() if now_t - t < _POWER_EVENT_TTL}
            _power_events_sent.clear()
            _power_events_sent.update(_power_events_sent_cleanup)
            _api_account_last_sent = {
                sig: ts for sig, ts in _api_account_last_sent.items()
                if (now_t - ts) < _api_account_dedup_window
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
                        now_t,
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
                                        del bruteforce_tracker[ip_part]

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

                    # Filter topik penting untuk alert log standar
                    if topic_tokens.intersection({'error', 'critical', 'warning', 'account'}):
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

        except Exception as e:
            logger.error(f"[ERR] Log Monitor: {e}")

        await asyncio.sleep(interval)


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
            if cfg.DHCP_POOL_SIZE > 0:
                bound = await _get_dhcp_usage_snapshot()
                pct = (bound / cfg.DHCP_POOL_SIZE) * 100

                try:
                    await asyncio.to_thread(database.record_metric, 'dhcp_usage_pct', pct)
                except Exception as metric_err:
                    logger.debug("Gagal simpan metric dhcp_usage_pct: %s", metric_err, exc_info=True)

                if pct >= cfg.DHCP_ALERT_THRESHOLD and not alerted_dhcp:
                    alerted_dhcp = True
                    msg = (f"⚠️ <b>[DHCP POOL WARNING]</b>\n\n"
                           f"Kapasitas IP hampir penuh!\n"
                           f"Terpakai: {bound}/{cfg.DHCP_POOL_SIZE} ({pct:.0f}%)\n"
                           f"Segera audit manual atau kosongkan lease agar klien baru bisa menyambung.")
                    await kirim_ke_semua_admin(msg, parse_mode='HTML')

                elif pct < cfg.DHCP_ALERT_THRESHOLD - 10 and alerted_dhcp:
                    alerted_dhcp = False

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

        except Exception as e:
            logger.error(f"[ERR] DHCP/ARP Monitor: {e}")

        await asyncio.sleep(interval)


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
                await asyncio.sleep(_TRAFFIC_INTERVAL)
                continue

            active_ifaces = [
                iface for iface in interfaces
                if iface['name'] not in cfg.MONITOR_IGNORE_IFACE and iface['running']
            ]
            if not active_ifaces:
                await asyncio.sleep(_TRAFFIC_INTERVAL)
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

        except Exception as e:
            logger.debug(f"[ERR] Traffic Monitor: {e}")

        await asyncio.sleep(_TRAFFIC_INTERVAL)


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
        except Exception as e:
            logger.warning(f"Alert maintenance error: {e}")
        await asyncio.sleep(interval)

