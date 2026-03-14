# ============================================
# MIKROTIK/NETWORK - Network queries
# interfaces, traffic, ARP, DHCP, routing
# ============================================

import logging
import ipaddress
import time
from datetime import datetime

from .connection import pool
from .decorators import with_retry, cached, to_bool, to_int, format_bytes
import core.config as cfg

logger = logging.getLogger(__name__)
_LOG_CACHE = []
_LOG_CACHE_TS = 0.0
_LOG_CACHE_TTL = 8.0
_LOG_CACHE_DEFAULT_CAP = 300


def _normalize_device_label(value):
    """Normalisasi label device agar matching hostname lebih toleran."""
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _is_device_within_monitor_window(device_name, now_dt=None):
    """Cek apakah device sedang di dalam window monitoring (jika ada)."""
    windows = dict(getattr(cfg, "CRITICAL_DEVICE_WINDOWS", {}) or {})
    if not windows:
        return True

    wanted = _normalize_device_label(device_name)
    if not wanted:
        return True

    matched = None
    for raw_name, span in windows.items():
        if _normalize_device_label(raw_name) == wanted:
            matched = span
            break

    if not matched or not isinstance(matched, (list, tuple)) or len(matched) != 2:
        return True

    try:
        start_min = int(matched[0])
        end_min = int(matched[1])
    except (TypeError, ValueError):
        return True

    now_obj = now_dt or datetime.now()
    now_min = (int(now_obj.hour) * 60) + int(now_obj.minute)

    if start_min == end_min:
        return True  # 24 jam
    if start_min < end_min:
        return start_min <= now_min < end_min
    return now_min >= start_min or now_min < end_min  # Lewat tengah malam


def get_active_critical_device_names():
    """Daftar nama critical device yang memang aktif dimonitor pada jam ini."""
    names = list(getattr(cfg, "CRITICAL_DEVICE_NAMES", []) or [])
    return [name for name in names if _is_device_within_monitor_window(name)]


def _extract_queue_target_ip(queue_item):
    """Ambil IP target pertama dari simple queue, return None jika invalid."""
    target = queue_item.get('target', '')
    first_target = (target.split(',')[0] if isinstance(target, str) else '').strip()
    ip = first_target.split('/')[0] if '/' in first_target else first_target
    if not ip:
        return None
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None
    return ip


@cached(ttl=5)
@with_retry
def get_interfaces():
    """Ambil semua interface + status."""
    api = pool.get_api()
    ifaces = list(api.path('interface'))

    results = []
    for iface in ifaces:
        results.append({
            'name': iface.get('name', ''),
            'type': iface.get('type', ''),
            'running': to_bool(iface.get('running', False)),
            'enabled': not to_bool(iface.get('disabled', False)),
            'comment': iface.get('comment', ''),
            'actual-mtu': to_int(iface.get('actual-mtu', iface.get('mtu', 0))),
            'rx': to_int(iface.get('rx-byte', 0)),
            'tx': to_int(iface.get('tx-byte', 0)),
            'rx_error': to_int(iface.get('rx-error', 0)),
            'tx_error': to_int(iface.get('tx-error', 0)),
            'rx_drop': to_int(iface.get('rx-drop', 0)),
            'tx_drop': to_int(iface.get('tx-drop', 0)),
            'link_downs': to_int(iface.get('link-downs', 0)),
            'mac': iface.get('mac-address', ''),
            'mac-address': iface.get('mac-address', ''),
        })
    return results


@cached(ttl=10)
@with_retry
def get_ip_addresses():
    """Ambil daftar IP Address router."""
    api = pool.get_api()
    return list(api.path('ip', 'address'))


@cached(ttl=5, maxsize=1)
@with_retry
def _get_interface_counter_map():
    """Fallback byte counter bersama agar get_traffic() tidak query interface berulang."""
    api = pool.get_api()
    counters = {}
    for iface in list(api.path('interface')):
        name = iface.get('name', '')
        if not name:
            continue
        counters[name] = {
            'rx-byte': to_int(iface.get('rx-byte', 0)),
            'tx-byte': to_int(iface.get('tx-byte', 0)),
        }
    return counters


@cached(ttl=3, maxsize=128)
@with_retry
def get_traffic(interface_name):
    """Ambil traffic RX/TX per interface."""
    api = pool.get_api()

    try:
        result = list(api.path('interface')('monitor-traffic', interface=interface_name, once=''))
        if result:
            data = result[0]
            rx_bps = to_int(data.get('rx-bits-per-second', 0))
            tx_bps = to_int(data.get('tx-bits-per-second', 0))

            # W2 FIX: ambil total byte dari monitor-traffic 'rx-byte' jika tersedia,
            # fallback ke query interface sekali lagi hanya jika tidak ada.
            rx_bytes = to_int(data.get('rx-byte', 0))
            tx_bytes = to_int(data.get('tx-byte', 0))

            if rx_bytes == 0 and tx_bytes == 0:
                counters = _get_interface_counter_map()
                if interface_name in counters:
                    rx_bytes = to_int(counters[interface_name].get('rx-byte', 0))
                    tx_bytes = to_int(counters[interface_name].get('tx-byte', 0))

            return {
                'name': interface_name,
                'rx_bps': rx_bps,
                'tx_bps': tx_bps,
                'rx': format_bytes(rx_bps // 8) + 'ps',
                'tx': format_bytes(tx_bps // 8) + 'ps',
                'rx_fmt': format_bytes(rx_bps // 8) + 'ps',
                'tx_fmt': format_bytes(tx_bps // 8) + 'ps',
                'rx_bytes': rx_bytes,
                'tx_bytes': tx_bytes,
            }
    except Exception as e:
        logger.warning(f"Traffic monitor error: {e}")

    return {
        'name': interface_name, 'rx_bps': 0, 'tx_bps': 0,
        'rx': '0 Bps', 'tx': '0 Bps', 'rx_fmt': '0 Bps', 'tx_fmt': '0 Bps',
        'rx_bytes': 0, 'tx_bytes': 0,
    }


@cached(ttl=60)
@with_retry
def get_default_gateway():
    """
    Auto-detect WAN Gateway dari routing table MikroTik.
    Membaca default route (0.0.0.0/0) dan return IP gateway-nya.
    """
    api = pool.get_api()
    routes = list(api.path('ip', 'route'))

    for route in routes:
        dst = route.get('dst-address', '')
        if dst == '0.0.0.0/0':
            gw = route.get('gateway', '')
            if gw:
                return gw
    return None


@cached(ttl=10)
@with_retry
def get_dhcp_leases():
    """Ambil DHCP client."""
    api = pool.get_api()
    leases = list(api.path('ip', 'dhcp-server', 'lease'))

    results = []
    for d in leases:
        hostname = d.get('host-name', '') or d.get('comment', '') or ''
        results.append({
            'address': d.get('address', ''),
            'mac-address': d.get('mac-address', ''),
            'mac': d.get('mac-address', ''),
            'host-name': hostname,
            'host': hostname or 'unknown',
            'status': d.get('status', ''),
            'server': d.get('server', ''),
            'expires-after': d.get('expires-after', ''),
            'comment': d.get('comment', ''),
            'active-address': d.get('active-address', ''),
            'active-mac-address': d.get('active-mac-address', ''),
            'disabled': to_bool(d.get('disabled', False)),
            'dynamic': to_bool(d.get('dynamic', True)),
        })
    return results


@cached(ttl=15)
@with_retry
def get_dhcp_usage_count():
    """Menghitung total lease bound dengan cepat."""
    api = pool.get_api()
    leases = list(api.path('ip', 'dhcp-server', 'lease'))
    bound = sum(1 for d in leases if d.get('status') == 'bound')
    return bound


@with_retry
def get_arp_anomalies(critical_macs):
    """
    Format critical_macs: { '192.168.3.10': '00:11:22:33:44:55', ... }
    Mendeteksi IP krusial namun MAC-nya berubah dari baseline.
    Return list of dictionary berisi IP bermasalah.
    """
    api = pool.get_api()
    arp_list = list(api.path('ip', 'arp'))

    anomalies = []
    for ip, expected_mac in critical_macs.items():
        for arp in arp_list:
            if arp.get('address') == ip:
                current_mac = arp.get('mac-address', '')
                if current_mac and current_mac.upper() != expected_mac.upper():
                    anomalies.append({
                        'ip': ip,
                        'expected_mac': expected_mac,
                        'current_mac': current_mac,
                        'interface': arp.get('interface', ''),
                    })
                break
    return anomalies


@with_retry
def get_mikrotik_log(lines=20):
    """Ambil tail log router dengan payload minimum + cache pendek."""
    global _LOG_CACHE, _LOG_CACHE_TS
    req_lines = max(1, int(lines))
    now = time.time()

    # Cache pendek untuk mencegah query berulang dari task monitor + command bot.
    if _LOG_CACHE and (now - _LOG_CACHE_TS) <= _LOG_CACHE_TTL and req_lines <= len(_LOG_CACHE):
        return _LOG_CACHE[-req_lines:]

    api = pool.get_api()
    try:
        all_logs = list(api.path('log')('print', **{'.proplist': 'time,topics,message'}))
    except Exception as e:
        logger.debug("Fallback get_mikrotik_log setelah print gagal: %s", e)
        pool.reset()
        api = pool.get_api()
        all_logs = list(api.path('log'))

    # Normalize: pastikan setiap entry punya 'topics', 'message', 'time'
    normalized = []
    for log in all_logs:
        topics = log.get('topics', '')
        if isinstance(topics, (list, tuple)):
            topics = ",".join(str(x) for x in topics if x is not None)
        normalized.append({
            'time': log.get('time', ''),
            'topics': topics,
            'message': log.get('message', ''),
        })

    cache_cap = max(_LOG_CACHE_DEFAULT_CAP, min(req_lines, 500))
    if len(normalized) > cache_cap:
        normalized = normalized[-cache_cap:]
    _LOG_CACHE = normalized
    _LOG_CACHE_TS = now

    return normalized[-req_lines:] if len(normalized) > req_lines else normalized


@cached(ttl=300)
@with_retry
def _get_all_monitored_queues():
    """W3 FIX: Shared internal helper — query antrean sekali untuk AP dan Server.

    Mengembalikan semua simple queues yang punya comment 'ap' atau 'server'.
    Di-cache 60 detik sehingga get_monitored_aps() dan get_monitored_servers()
    tidak masing-masing query ke router.
    """
    api = pool.get_api()
    queues = list(api.path('queue', 'simple'))
    aps = {}
    servers = {}
    for q in queues:
        # Queue disabled dianggap tidak aktif untuk monitoring host.
        if to_bool(q.get('disabled', False)):
            continue

        comment_raw = (q.get('comment') or '').strip().lower()
        name = q.get('name', 'Unknown')
        ip = _extract_queue_target_ip(q)
        if not ip:
            continue

        if comment_raw == 'ap':
            aps[name] = ip
        elif comment_raw == 'server':
            servers[name] = ip
    return aps, servers


@cached(ttl=300)
@with_retry
def _get_all_queue_targets():
    """Ambil semua target IP simple queue enabled sebagai map name->ip."""
    api = pool.get_api()
    queues = list(api.path('queue', 'simple'))
    targets = {}
    for q in queues:
        if to_bool(q.get('disabled', False)):
            continue
        name = str(q.get('name') or '').strip()
        if not name:
            continue
        ip = _extract_queue_target_ip(q)
        if not ip:
            continue
        targets[name] = ip
    return targets


@with_retry
def get_monitored_aps():
    """
    Ambil daftar AP dari Simple Queues berdasarkan field 'comment'.
    Set comment = 'ap' di queue MikroTik.
    Return: dict {nama_queue: ip}
    """
    fallback = dict(getattr(cfg, "APS_FALLBACK", {}) or {})
    try:
        aps, _ = _get_all_monitored_queues()
        merged = dict(fallback)
        merged.update(aps)
        return merged
    except Exception as e:
        logger.warning("get_monitored_aps fallback ke config statis: %s", e)
        return fallback


@with_retry
def get_monitored_servers():
    """
    Ambil daftar Server dari Simple Queues berdasarkan field 'comment'.
    Set comment = 'server' di queue MikroTik.
    Return: dict {nama_queue: ip}
    """
    fallback = dict(getattr(cfg, "SERVERS_FALLBACK", {}) or {})
    try:
        _, servers = _get_all_monitored_queues()
        merged = dict(fallback)
        merged.update(servers)
        return merged
    except Exception as e:
        logger.warning("get_monitored_servers fallback ke config statis: %s", e)
        return fallback


@cached(ttl=180)
@with_retry
def get_monitored_critical_devices():
    """Resolve device penting dari fallback statis + hostname DHCP.

    - `CRITICAL_DEVICES` (name:ip) dipakai sebagai sumber statis utama.
    - `CRITICAL_DEVICE_NAMES` dipakai untuk lookup otomatis di DHCP lease host-name/comment.
    """
    devices = dict(getattr(cfg, "CRITICAL_DEVICES_FALLBACK", {}) or {})
    critical_names = get_active_critical_device_names()
    if not critical_names:
        return devices

    queue_targets = {}
    try:
        queue_targets = _get_all_queue_targets()
    except Exception as e:
        logger.debug("get_monitored_critical_devices fallback tanpa simple queue: %s", e)

    # get_dhcp_leases sudah cached + retry, aman dipanggil dari sini.
    leases = []
    try:
        leases = get_dhcp_leases()
    except Exception as e:
        logger.debug("get_monitored_critical_devices fallback tanpa DHCP lease: %s", e)

    for device_name in critical_names:
        if device_name in devices:
            continue

        wanted = _normalize_device_label(device_name)
        if not wanted:
            continue

        # Prioritas 1: matching nama queue static (simple queue).
        for queue_name, queue_ip in queue_targets.items():
            queue_norm = _normalize_device_label(queue_name)
            if not queue_norm:
                continue
            if queue_norm == wanted or wanted in queue_norm:
                devices[device_name] = queue_ip
                break
        if device_name in devices:
            continue

        # Prioritas 2: fallback ke lookup DHCP lease.
        for lease in leases:
            lease_label = (
                lease.get('host-name')
                or lease.get('comment')
                or lease.get('host')
                or ""
            )
            lease_norm = _normalize_device_label(lease_label)
            if not lease_norm:
                continue
            if lease_norm == wanted or wanted in lease_norm:
                ip = str(lease.get('address') or lease.get('active-address') or '').strip()
                if ip:
                    devices[device_name] = ip
                    break

    filtered = {}
    for name, ip in devices.items():
        if _is_device_within_monitor_window(name):
            filtered[name] = ip
    return filtered
