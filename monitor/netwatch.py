# ============================================
# MONITOR/NETWATCH - Network Watch (Ping, TCP, DNS)
# Advanced matrix monitor + klasifikasi root cause
# ============================================

import asyncio
import contextlib
import datetime
import json
import logging
import os
import socket
import hashlib
import math

from mikrotik import (
    get_status, get_interfaces, get_dhcp_usage_count,
    get_monitored_aps, get_monitored_servers, get_monitored_critical_devices, get_default_gateway,
    ping_host
)
from mikrotik.connection import pool
import core.config as config
from core.classification import (
    classify_network_status,
    classify_host_short,
)
from .alerts import kirim_ke_semua_admin, with_timeout, AlertSeverity, acknowledge_alert
from core import database

logger = logging.getLogger(__name__)

_ping_semaphore = None
_ping_semaphore_size = 0

# Master state arrays
_netwatch_state = {}       # host -> True/False (UP/DOWN)
_netwatch_fail = {}        # host -> fail_count
_netwatch_time_down = {}   # host -> datetime
_netwatch_db_id = {}       # host -> db_incident_id
_netwatch_recovery = {}    # host -> consecutive success count (anti-flapping)
_netwatch_up_since = {}    # host -> datetime saat mulai kandidat recovery
_netwatch_reconciled_hosts = set()
_last_state_hash = None
_api_unavailable_active = False
_netwatch_timeout_hits = 0
_topology_cache = {
    "ts": 0.0,
    "aps": {},
    "servers": {},
    "critical": {},
    "gw_wan": "",
}


async def _host_ping(host, count=2):
    """Ping menggunakan RouterOS API (lokal subprocess Windows bermasalah)."""
    global _ping_semaphore, _ping_semaphore_size
    desired = max(1, int(getattr(config, "NETWATCH_PING_CONCURRENCY", 4)))
    if _ping_semaphore is None or _ping_semaphore_size != desired:
        _ping_semaphore = asyncio.Semaphore(desired)
        _ping_semaphore_size = desired

    async with _ping_semaphore:
        try:
            # Jalankan ping_host dari mikrotik via thread agar tidak memblokir event loop
            result = await asyncio.to_thread(ping_host, host, count)
            if not isinstance(result, dict):
                return False
            sent = max(1, int(result.get('sent', count) or count or 1))
            received = max(0, int(result.get('received', 0) or 0))
            ratio = float(getattr(config, "NETWATCH_UP_MIN_SUCCESS_RATIO", 0.5) or 0.5)
            ratio = max(0.1, min(1.0, ratio))
            required = max(1, int(math.ceil(sent * ratio)))
            return received >= required
        except Exception as e:
            logger.error(f"Error ping mikrotik untuk {host}: {e}")
            err = str(e).lower()
            if any(k in err for k in ("not logged in", "not a socket", "10038")):
                return None
            return False


async def _tcp_check(host, port, timeout=2):
    try:
        coro = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(coro, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, OSError):
        return False


async def _dns_check(domains=None, timeout=3):
    # Cek DNS dari sisi router dulu, fallback ke resolver host bot.
    # Ini mengurangi false diagnosis saat hanya salah satu sisi yang bermasalah.
    candidates = domains or ["google.com"]
    if isinstance(candidates, str):
        candidates = [candidates]

    for domain in candidates:
        try:
            router_ping = await asyncio.to_thread(ping_host, domain, 1)
            if isinstance(router_ping, dict):
                # Jika resolved dan menerima reply, jelas DNS+reachability OK.
                if router_ping.get("received", 0) > 0:
                    return True
                # Jika ada indikasi resolve error, lanjut fallback local.
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
        try:
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(loop.getaddrinfo(domain, 80, family=socket.AF_INET), timeout=timeout)
            return True
        except (asyncio.TimeoutError, socket.gaierror, OSError):
            continue
    return False


def _dns_label():
    domains = list(getattr(config, "DNS_CHECK_DOMAINS", []) or [])
    if not domains:
        domains = [getattr(config, "DNS_CHECK_DOMAIN", "google.com")]
    return ", ".join(domains[:3])


def _alert_timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _static_monitored_hosts():
    """Host minimum yang tetap bisa ditampilkan saat API RouterOS tidak tersedia."""
    hosts = [config.MIKROTIK_IP]
    if getattr(config, "GW_WAN", ""):
        hosts.append(config.GW_WAN)
    if getattr(config, "GW_INET", ""):
        hosts.append(config.GW_INET)
    hosts.extend(config.SERVERS_FALLBACK.values())
    hosts.extend(config.APS_FALLBACK.values())
    hosts.extend(config.CRITICAL_DEVICES_FALLBACK.values())
    hosts.extend(f"{s['ip']}:{s['port']}" for s in config.TCP_SERVICES)
    hosts.append("DNS_Resolv")
    seen = set()
    result = []
    for host in hosts:
        if host and host not in seen:
            seen.add(host)
            result.append(host)
    return result


def _build_state_dump(
    kategori,
    hosts,
    fails,
    api_connected=True,
    api_error="",
    monitor_degraded=False,
    degraded_reason="",
):
    return {
        "last_update": datetime.datetime.now().isoformat(),
        "kategori": kategori,
        "hosts": hosts,
        "fails": fails,
        "api_connected": bool(api_connected),
        "api_error": str(api_error or ""),
        "monitor_degraded": bool(monitor_degraded),
        "degraded_reason": str(degraded_reason or ""),
    }


async def _load_monitored_topology(refresh_ttl=180):
    """Load host inventory dengan cache last-good agar netwatch tidak query berat tiap tick."""
    now_ts = datetime.datetime.now().timestamp()
    cached_age = now_ts - float(_topology_cache.get("ts", 0.0) or 0.0)
    if cached_age < max(15, int(refresh_ttl)):
        return (
            dict(_topology_cache.get("aps", {}) or {}),
            dict(_topology_cache.get("servers", {}) or {}),
            dict(_topology_cache.get("critical", {}) or {}),
            str(_topology_cache.get("gw_wan", "") or ""),
        )

    current_aps = await with_timeout(
        asyncio.to_thread(get_monitored_aps),
        timeout=10,
        default=None,
        log_key="netwatch:get_monitored_aps",
        warn_every_sec=300,
    )
    current_servers = await with_timeout(
        asyncio.to_thread(get_monitored_servers),
        timeout=10,
        default=None,
        log_key="netwatch:get_monitored_servers",
        warn_every_sec=300,
    )
    current_critical = await with_timeout(
        asyncio.to_thread(get_monitored_critical_devices),
        timeout=10,
        default=None,
        log_key="netwatch:get_monitored_critical_devices",
        warn_every_sec=300,
    )
    current_gw_wan = await with_timeout(
        asyncio.to_thread(get_default_gateway),
        timeout=10,
        default=None,
        log_key="netwatch:get_default_gateway",
        warn_every_sec=300,
    )

    if any(value is not None for value in (current_aps, current_servers, current_critical, current_gw_wan)):
        _topology_cache["ts"] = now_ts
        if isinstance(current_aps, dict):
            _topology_cache["aps"] = dict(current_aps)
        if isinstance(current_servers, dict):
            _topology_cache["servers"] = dict(current_servers)
        if isinstance(current_critical, dict):
            _topology_cache["critical"] = dict(current_critical)
        if current_gw_wan:
            _topology_cache["gw_wan"] = str(current_gw_wan)

    return (
        dict(_topology_cache.get("aps", {}) or {}),
        dict(_topology_cache.get("servers", {}) or {}),
        dict(_topology_cache.get("critical", {}) or {}),
        str(_topology_cache.get("gw_wan", "") or ""),
    )


async def _persist_state_dump(state_dump):
    """Tulis state.json secara atomik hanya jika ada perubahan."""
    try:
        state_file = config.DATA_DIR / "state.json"

        def _write_state():
            global _last_state_hash
            new_hash = hashlib.md5(json.dumps(state_dump, sort_keys=True).encode()).hexdigest()
            if new_hash != _last_state_hash:
                import tempfile
                tmp_fd, tmp_path = tempfile.mkstemp(dir=str(config.DATA_DIR), suffix='.tmp')
                try:
                    with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                        json.dump(state_dump, f)
                    os.replace(tmp_path, str(state_file))
                except Exception as write_err:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    logger.debug("State write temp-file cleanup triggered: %s", write_err)
                    raise
                _last_state_hash = new_hash

        await asyncio.to_thread(_write_state)
    except Exception as ex:
        logger.error(f"[ERR] Gagal write state.json: {ex}")


def _clear_false_down_alerts():
    """Hapus pending alert DOWN lama saat API unavailable agar tidak terus escalation."""
    for host in list(_netwatch_state.keys()) + _static_monitored_hosts():
        try:
            acknowledge_alert(f"down_{host}")
        except Exception as e:
            logger.debug("Gagal acknowledge stale down alert %s: %s", host, e)


def _api_error_hint(api_error):
    """Hint operator singkat untuk error API yang umum."""
    err = str(api_error or "").lower()
    if "invalid user name or password" in err:
        return "Kemungkinan user/password API di router tidak cocok dengan .env."
    if "not logged in" in err:
        return "Sesi API invalid atau policy login user router berubah."
    if "unreachable" in err or "timed out" in err:
        return "Cek konektivitas host bot ke MikroTik, IP service API, dan firewall."
    if "forcibly closed" in err or "unexpectedly closed" in err:
        return "Router menutup koneksi. Cek stabilitas jaringan dan service API."
    return "Cek kredensial, policy API, allow-list IP service API, dan jaringan host bot."


async def _enter_api_unavailable_state(api_error):
    """Masuk ke mode API unavailable tanpa memerah-merahkan host."""
    global _api_unavailable_active
    if not _api_unavailable_active:
        _api_unavailable_active = True
        _clear_false_down_alerts()
        await kirim_ke_semua_admin(
            "⚠️ <b>MIKROTIK API UNAVAILABLE</b>\n"
            f"Router {config.MIKROTIK_IP} belum connect/login atau command API inti gagal.\n"
            "Netwatch host detail dipause agar tidak memerah palsu.\n\n"
            f"Detail: <code>{api_error or 'health check gagal'}</code>\n"
            f"Saran: {_api_error_hint(api_error)}",
            parse_mode='HTML',
            severity=AlertSeverity.WARNING,
            alert_key="api_unavailable",
        )

    unavailable_hosts = {}
    unavailable_fails = {}
    for host in set(_static_monitored_hosts()) | set(_netwatch_state.keys()):
        unavailable_hosts[host] = None
        unavailable_fails[host] = 0

    await _persist_state_dump(
        _build_state_dump(
            "🟠 API UNAVAILABLE (MikroTik belum connect/login)",
            unavailable_hosts,
            unavailable_fails,
            api_connected=False,
            api_error=api_error,
            monitor_degraded=False,
            degraded_reason="",
        )
    )


def _generate_snapshot():
    """Mengambil snapshot parameter kritikal saat down besar terjadi."""
    try:
        info = get_status()
        ifaces = get_interfaces()

        cpu = info.get('cpu', '?')
        total = int(info.get('ram_total', 0))
        free = int(info.get('ram_free', 0))
        ram_free_mb = free / (1024*1024) if total > 0 else 0

        dhcp_count = get_dhcp_usage_count()
        pool_pct = (dhcp_count / config.DHCP_POOL_SIZE) * 100 if config.DHCP_POOL_SIZE > 0 else 0

        inet_err = "0/0"
        loc_err = "0/0"
        for i in ifaces:
            iname = i['name'].lower()
            if any(kw in iname for kw in config.WAN_IFACE_KEYWORDS):
                inet_err = f"{i.get('rx_error', '?')}/{i.get('tx_error', '?')}"
            if any(kw in iname for kw in config.LAN_IFACE_KEYWORDS):
                loc_err = f"{i.get('rx_error', '?')}/{i.get('tx_error', '?')}"

        return (f"CPU: {cpu}% | RAM free: {ram_free_mb:.1f}MB | DHCP: {pool_pct:.0f}%\n"
                f"Err INDIBIZ: {inet_err} | Err LOCAL: {loc_err}")
    except Exception as e:
        return f"Snapshot gagal: {e}"


async def _cleanup_stale_hosts(all_hosts):
    """Hapus host stale dari state + tutup incident + clear pending alert key."""
    stale_hosts = set(_netwatch_state.keys()) - set(all_hosts)
    for h in stale_hosts:
        # Close incident jika host stale terakhir berstatus DOWN.
        if not _netwatch_state.get(h, True):
            try:
                await asyncio.to_thread(database.log_incident_up, h)
            except Exception as e:
                logger.debug(f"Failed to close ghost incident for {h}: {e}")

        # Host sudah tidak dimonitor: drop pending ACK agar tidak terus escalation.
        try:
            acknowledge_alert(f"down_{h}")
        except Exception as e:
            logger.debug(f"Failed to acknowledge stale alert for {h}: {e}")

        _netwatch_state.pop(h, None)
        _netwatch_fail.pop(h, None)
        _netwatch_time_down.pop(h, None)
        _netwatch_db_id.pop(h, None)
        _netwatch_recovery.pop(h, None)
        _netwatch_up_since.pop(h, None)
        _netwatch_reconciled_hosts.discard(h)
        logger.info(f"[PRUNE] Host '{h}' dihapus dari state (incident/alert cleaned).")


async def task_monitor_netwatch():
    """Task 3: Monitor Matrix Lanjutan (Ping & TCP) + Klasifikasi Root Cause."""
    global _api_unavailable_active, _netwatch_timeout_hits
    interval = int(getattr(config, "NETWATCH_INTERVAL", 15))
    logger.info(f"[INIT] Advanced Matrix Monitor berjalan (Interval: {interval}s)")
    _last_full_timeout_alert = 0.0

    while True:
        try:
            config.reload_runtime_overrides(min_interval=10)
            config.reload_router_env(min_interval=10)
            interval = int(getattr(config, "NETWATCH_INTERVAL", interval))
            api_diag = await asyncio.to_thread(pool.connection_diagnostics)
            api_error = api_diag.get("last_error", "").strip()
            api_healthy = bool(api_diag.get("healthy", False))

            if not api_healthy:
                await _enter_api_unavailable_state(api_error or "health check gagal")
                await asyncio.sleep(interval)
                continue

            if _api_unavailable_active:
                _api_unavailable_active = False
                acknowledge_alert("api_unavailable")
                await kirim_ke_semua_admin(
                    f"✅ <b>MIKROTIK API RECOVERY</b>\nRouter {config.MIKROTIK_IP} kembali connect/login.",
                    parse_mode='HTML',
                    severity=AlertSeverity.INFO,
                )

            current_aps, current_servers, current_critical, current_gw_wan = await _load_monitored_topology()
            if not current_gw_wan:
                current_gw_wan = config.GW_WAN

            all_icmp = [('Router', config.MIKROTIK_IP, 'CORE')]
            if current_gw_wan: all_icmp.append(('WAN_GW', current_gw_wan, 'WAN'))
            if config.GW_INET: all_icmp.append(('Internet', config.GW_INET, 'INET'))
            for name, ip in current_servers.items(): all_icmp.append((name, ip, 'SERVER'))
            for name, ip in current_aps.items(): all_icmp.append((name, ip, 'AP'))
            for name, ip in current_critical.items(): all_icmp.append((name, ip, 'CRITICAL'))
            critical_ips = set(current_critical.values())

            # Inisialisasi state awal
            all_hosts = [h[1] for h in all_icmp] + [f"{s['ip']}:{s['port']}" for s in config.TCP_SERVICES] + ["DNS_Resolv"]
            for h in all_hosts:
                if h not in _netwatch_state:
                    _netwatch_state[h] = True
                    _netwatch_fail[h] = 0
                    _netwatch_time_down[h] = None
                    _netwatch_recovery[h] = 0
                    _netwatch_up_since[h] = None

            # Bersihkan ghost hosts (close orphan incident + stale pending ack).
            await _cleanup_stale_hosts(all_hosts)

            # Pengecekan konkuren asinkron
            async def cek_icmp(tup):
                ping_count = max(1, min(10, int(getattr(config, "PING_COUNT", 3))))
                return (tup, await _host_ping(tup[1], ping_count))

            async def cek_tcp(srv):
                return (srv, await _tcp_check(srv['ip'], srv['port']))

            async def cek_dns():
                return ("DNS_Resolv", await _dns_check(getattr(config, "DNS_CHECK_DOMAINS", None)))

            all_checks = asyncio.gather(
                asyncio.gather(*[cek_icmp(x) for x in all_icmp], return_exceptions=True),
                asyncio.gather(*[cek_tcp(x) for x in config.TCP_SERVICES], return_exceptions=True),
                cek_dns()
            )

            timeout_s = max(30, min(180, 10 + (len(all_hosts) * 3)))
            results = await with_timeout(
                all_checks,
                timeout=timeout_s,
                log_key="netwatch:all_checks",
                warn_every_sec=300,
            )
            if results is None:
                if hasattr(all_checks, "done"):
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await all_checks
                _netwatch_timeout_hits += 1
                timeout_threshold = max(1, int(getattr(config, "NETWATCH_CYCLE_TIMEOUT_THRESHOLD", 2) or 2))
                degraded_reason = (
                    f"Netwatch timeout total {timeout_s}s "
                    f"({_netwatch_timeout_hits}/{timeout_threshold} berturut-turut)."
                )
                logger.warning(
                    "Netwatch check timed out entirely; preserving previous state. streak=%s/%s",
                    _netwatch_timeout_hits,
                    timeout_threshold,
                )
                now_t = datetime.datetime.now().timestamp()
                degraded_cooldown = max(
                    30,
                    int(getattr(config, "NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC", 300) or 300),
                )
                if (
                    _netwatch_timeout_hits >= timeout_threshold
                    and (now_t - _last_full_timeout_alert) > degraded_cooldown
                ):
                    _last_full_timeout_alert = now_t
                    await kirim_ke_semua_admin(
                        "⚠️ <b>NETWATCH DEGRADED</b>\n"
                        "Siklus netwatch timeout total. Status host dipertahankan dari tick terakhir agar tidak false DOWN.\n\n"
                        f"Detail: <code>{degraded_reason}</code>",
                        parse_mode='HTML',
                        severity=AlertSeverity.WARNING,
                    )
                await _persist_state_dump(
                    _build_state_dump(
                        "🟡 NETWATCH DEGRADED (timeout siklus monitor)",
                        dict(_netwatch_state),
                        dict(_netwatch_fail),
                        api_connected=True,
                        api_error="",
                        monitor_degraded=True,
                        degraded_reason=degraded_reason,
                    )
                )
                await asyncio.sleep(interval)
                continue
            else:
                _netwatch_timeout_hits = 0
                icmp_results, tcp_results, dns_result = results

                # Kumpulkan status terkini; exception per-host diperlakukan sebagai fail.
                current_status = {}
                for tup, res in zip(all_icmp, icmp_results):
                    if isinstance(res, Exception):
                        current_status[tup[1]] = False
                    else:
                        current_status[tup[1]] = res[1]
                for srv, res in zip(config.TCP_SERVICES, tcp_results):
                    key = f"{srv['ip']}:{srv['port']}"
                    if isinstance(res, Exception):
                        current_status[key] = False
                    else:
                        current_status[key] = bool(res[1])
                if isinstance(dns_result, Exception):
                    current_status["DNS_Resolv"] = False
                else:
                    current_status["DNS_Resolv"] = bool(dns_result[1])

            if current_status.get(config.MIKROTIK_IP) is None:
                await _enter_api_unavailable_state("RouterOS API ping command gagal: not logged in/session invalid")
                await asyncio.sleep(interval)
                continue

            # Setelah restart proses, incident DB bisa masih open walau host sudah UP.
            # Rekonsiliasi satu kali per host agar histori tidak nyangkut merah palsu.
            for host, is_up in current_status.items():
                if not is_up or host in _netwatch_reconciled_hosts:
                    continue
                try:
                    was_closed = await asyncio.to_thread(database.log_incident_up, host, "reconciled")
                    if was_closed:
                        logger.info("[RECONCILE] Closed stale open incident for %s after restart/reconnect.", host)
                except Exception as e:
                    logger.debug("Gagal reconcile incident host %s: %s", host, e)
                _netwatch_reconciled_hosts.add(host)

            alerts_to_send = []
            recoveries_to_send = []

            # Evaluasi state
            for host, is_up in current_status.items():
                if is_up:
                    _netwatch_fail[host] = 0
                    if not _netwatch_state[host]:
                        # Host was DOWN — require multiple consecutive successes before RECOVERY
                        now_dt = datetime.datetime.now()
                        if _netwatch_up_since.get(host) is None:
                            _netwatch_up_since[host] = now_dt
                        _netwatch_recovery[host] = _netwatch_recovery.get(host, 0) + 1
                        up_for_sec = int((now_dt - _netwatch_up_since[host]).total_seconds())
                        min_up_sec = max(0, int(getattr(config, "RECOVERY_MIN_UP_SECONDS", 90) or 0))
                        confirm_count = int(getattr(config, "RECOVERY_CONFIRM_COUNT", 2))
                        if host in critical_ips:
                            min_up_sec = max(
                                min_up_sec,
                                int(getattr(config, "CRITICAL_RECOVERY_MIN_UP_SECONDS", 180) or 180),
                            )
                            confirm_count = max(
                                confirm_count,
                                int(getattr(config, "CRITICAL_RECOVERY_CONFIRM_COUNT", 3) or 3),
                            )
                        if (
                            _netwatch_recovery[host] >= confirm_count
                            and up_for_sec >= min_up_sec
                        ):
                            _netwatch_state[host] = True
                            _netwatch_recovery[host] = 0
                            _netwatch_up_since[host] = None
                            tdown = _netwatch_time_down[host]
                            dur_str = "Unknown"
                            if tdown:
                                dur = (datetime.datetime.now() - tdown).total_seconds()
                                dur_str = f"{int(dur//60)}m {int(dur%60)}s"

                            await asyncio.to_thread(database.log_incident_up, host)
                            recoveries_to_send.append((host, dur_str))
                            _netwatch_time_down[host] = None
                        else:
                            logger.info(
                                "Recovery pending for %s: %s/%s hits, up_for=%ss/%ss",
                                host,
                                _netwatch_recovery[host],
                                confirm_count,
                                up_for_sec,
                                min_up_sec,
                            )
                    else:
                        _netwatch_recovery[host] = 0  # Reset if host is already UP
                        _netwatch_up_since[host] = None
                else:
                    _netwatch_fail[host] += 1
                    _netwatch_recovery[host] = 0  # Reset recovery counter on fail
                    _netwatch_up_since[host] = None
                    if _netwatch_fail[host] == config.PING_FAIL_THRESHOLD and _netwatch_state[host]:
                        _netwatch_state[host] = False
                        _netwatch_time_down[host] = datetime.datetime.now()
                        alerts_to_send.append(host)

            # Klasifikasi global status jaringan (untuk state dashboard)
            kategori = classify_network_status(
                _netwatch_state, current_servers, current_aps,
                config.MIKROTIK_IP, current_gw_wan, config.GW_INET,
                tcp_services=config.TCP_SERVICES,
                dns_key="DNS_Resolv",
                critical_devices=current_critical,
            )
            # Kirim alert dan recovery
            if alerts_to_send or recoveries_to_send:
                if alerts_to_send:
                    snapshot = await asyncio.to_thread(_generate_snapshot)

                for h in alerts_to_send:
                    host_kategori_short = classify_host_short(
                        _netwatch_state,
                        h,
                        current_servers,
                        current_aps,
                        config.MIKROTIK_IP,
                        current_gw_wan,
                        config.GW_INET,
                        tcp_services=config.TCP_SERVICES,
                        dns_key="DNS_Resolv",
                        critical_devices=current_critical,
                    )

                    await asyncio.to_thread(database.log_incident_down, h, host_kategori_short, snapshot)

                    waktu = _alert_timestamp()
                    host_label = h
                    if h == "DNS_Resolv":
                        host_label = f"DNS Resolver ({_dns_label()})"
                    for tup in all_icmp:
                        if tup[1] == h: host_label = f"{tup[0]} ({tup[2]})"
                    for srv in config.TCP_SERVICES:
                        if f"{srv['ip']}:{srv['port']}" == h: host_label = f"TCP {srv['name']} ({srv['port']})"

                    msg = (f"🚨 <b>DOWN — {host_label}</b>\n"
                           f"IP/Target: {h}\n"
                           f"Waktu: {waktu}\n"
                           f"Gagal Ping: {config.PING_FAIL_THRESHOLD}x berturut-turut\n\n"
                           f"Klasifikasi Cepat: {host_kategori_short}\n\n"
                           f"[Snapshot]\n{snapshot}")
                    await kirim_ke_semua_admin(
                        msg, parse_mode='HTML',
                        severity=AlertSeverity.CRITICAL,
                        alert_key=f"down_{h}"
                    )

                for h, dur in recoveries_to_send:
                    waktu = _alert_timestamp()
                    host_label = h
                    if h == "DNS_Resolv":
                        host_label = f"DNS Resolver ({_dns_label()})"
                    for tup in all_icmp:
                        if tup[1] == h: host_label = f"{tup[0]} ({tup[2]})"
                    for srv in config.TCP_SERVICES:
                        if f"{srv['ip']}:{srv['port']}" == h: host_label = f"TCP {srv['name']} ({srv['port']})"

                    msg = (f"✅ <b>RECOVERY — {host_label}</b>\n"
                           f"IP/Target: {h}\n"
                           f"Waktu: {waktu}\n"
                           f"Durasi DOWN: {dur}")
                    acknowledge_alert(f"down_{h}")  # Auto-clear ack saat recovery
                    await kirim_ke_semua_admin(msg, parse_mode='HTML', severity=AlertSeverity.INFO)

            await _persist_state_dump(
                _build_state_dump(
                    kategori,
                    _netwatch_state,
                    _netwatch_fail,
                    api_connected=True,
                    api_error="",
                    monitor_degraded=False,
                    degraded_reason="",
                )
            )

        except Exception as e:
            logger.error(f"[ERR] Matrix Monitor: {e}")

        await asyncio.sleep(interval)
