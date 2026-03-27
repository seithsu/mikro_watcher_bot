# ============================================
# MIKROTIK/TOOLS - Ping, WoL, Free IP finder
# ============================================

import logging
import ipaddress

from .connection import pool
from .decorators import with_retry, to_int
import core.config as cfg

logger = logging.getLogger(__name__)


def _truthy(value):
    return str(value).strip().lower() in {"true", "yes", "on", "1"}


def _is_active_arp_entry(arp):
    mac = str(arp.get('mac-address', '') or '').strip()
    if not mac or mac in {"00:00:00:00:00:00", "00-00-00-00-00-00"}:
        return False

    status = str(arp.get('status', '') or '').strip().lower()
    if status in {"incomplete", "failed", "stale", "delay", "probe"}:
        return False

    if 'complete' in arp and not _truthy(arp.get('complete')):
        return False

    if _truthy(arp.get('invalid')) or _truthy(arp.get('disabled')):
        return False

    return True


def _extract_queue_target_ip(queue_item):
    target = str(queue_item.get('target', '') or '').strip()
    if not target:
        return None
    first_target = target.split(',')[0].strip()
    ip = first_target.split('/')[0].strip()
    if not ip:
        return None
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None
    return ip


def _add_used_ip_if_in_network(used_ips, network, ip_str):
    ip_text = str(ip_str or '').strip()
    if not ip_text:
        return
    try:
        ip_obj = ipaddress.ip_address(ip_text)
        if ip_obj in network:
            used_ips.add(ip_text)
    except ValueError:
        return


def _iter_reserved_inventory_ips():
    """IP inventaris statis yang harus tetap dianggap reserved walau device sedang mati."""
    for mapping in (
        getattr(cfg, 'SERVERS_FALLBACK', {}) or {},
        getattr(cfg, 'APS_FALLBACK', {}) or {},
        getattr(cfg, 'CRITICAL_DEVICES_FALLBACK', {}) or {},
    ):
        for ip in mapping.values():
            yield ip


@with_retry
def ping_host(address, count=4):
    """Ping ke host dari router via RouterOS API.

    RouterOS v6.40: /ping harus dipanggil via api('/ping', ...),
    bukan api.path('tool')('ping', ...) — tested 7 syntaxes,
    hanya api() direct call yang jalan.
    """
    api = pool.get_api()

    # Direct API call — satu-satunya syntax yang bekerja
    # di RouterOS v6.40.9 (bugfix)
    results = list(api('/ping', address=address, count=str(count)))

    if not results:
        return {
            'host': address,
            'sent': count,
            'received': 0,
            'loss': 100,
            'avg_rtt': 0,
            'results': [],
        }

    ping_results = []
    total_time = 0
    received = 0
    sent = 0

    for r in results:
        # Abaikan baris summary (biasanya tidak punya seq) agar tidak
        # dihitung sebagai paket sukses dan memicu false-recovery.
        if 'seq' not in r:
            continue

        seq = to_int(r.get('seq', 0))
        sent += 1
        # RouterOS returns time as string like '0ms' or '1ms'
        time_val = r.get('time', '0')
        if isinstance(time_val, str):
            time_val = time_val.replace('ms', '').strip()
        rtt = to_int(time_val)
        status = str(r.get('status', '')).strip().lower()

        # Hitung sukses hanya untuk echo-reply nyata (paket dengan seq).
        if 'time' in r and status != 'timeout':
            received += 1
            total_time += rtt

        ping_results.append({
            'seq': seq,
            'time': rtt,
            'status': status or 'ok',
            'ttl': to_int(r.get('ttl', 0)),
        })

    # Fallback jika device tidak mengembalikan baris per paket.
    if sent == 0:
        sent = count

    # RouterOS juga menyediakan packet-loss di response terakhir
    last = results[-1] if results else {}
    loss_from_router = last.get('packet-loss')
    if loss_from_router is not None:
        loss = to_int(str(loss_from_router).replace('%', '').strip())
    else:
        loss = round((1 - received / sent) * 100, 1) if sent else 100

    avg_rtt = round(total_time / received, 1) if received else 0

    return {
        'host': address,
        'sent': sent,
        'received': received,
        'loss': loss,
        'avg_rtt': avg_rtt,
        'results': ping_results,
    }


@with_retry
def send_wol(mac_address: str, interface: str):
    """
    Mengirim Magic Packet Wake-on-LAN ke target MAC Address
    melalui Interface tertentu via RouterOS /tool/wol.

    Menggunakan direct API call (sama seperti /ping fix).
    """
    api = pool.get_api()
    tuple(api('/tool/wol', interface=interface, mac=mac_address))
    return True


@with_retry
def find_free_ips(network_with_cidr):
    """
    Mencari IP yang belum terpakai dalam subnet tertentu.
    network_with_cidr: misal '192.168.1.0/24'
    """
    api = pool.get_api()

    try:
        network = ipaddress.ip_network(network_with_cidr, strict=False)
    except ValueError:
        return {'error': f'Invalid network: {network_with_cidr}'}

    # Kumpulkan IP yang sudah terpakai dari berbagai sumber
    used_ips = set()

    # ARP table
    try:
        arp_list = list(api.path('ip', 'arp'))
        for arp in arp_list:
            if not _is_active_arp_entry(arp):
                continue
            ip_str = arp.get('address', '')
            if ip_str:
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                    if ip_obj in network:
                        used_ips.add(ip_str)
                except ValueError:
                    pass
    except Exception as e:
        logger.warning(f"find_free_ips: gagal baca ARP: {e}")

    # DHCP leases
    try:
        dhcp_list = list(api.path('ip', 'dhcp-server', 'lease'))
        for d in dhcp_list:
            status = str(d.get('status', '') or '').strip().lower()
            is_static = not _truthy(d.get('dynamic', True))
            if status != 'bound' and not is_static:
                continue
            if _truthy(d.get('disabled')):
                continue
            ip_str = d.get('address', '')
            if ip_str:
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                    if ip_obj in network:
                        used_ips.add(ip_str)
                except ValueError:
                    pass
    except Exception as e:
        logger.warning(f"find_free_ips: gagal baca DHCP: {e}")

    # IP address router
    try:
        ip_addrs = list(api.path('ip', 'address'))
        for addr in ip_addrs:
            ip_str = addr.get('address', '')
            if '/' in ip_str:
                ip_str = ip_str.split('/')[0]
            _add_used_ip_if_in_network(used_ips, network, ip_str)
    except Exception as e:
        logger.warning(f"find_free_ips: gagal baca IP address: {e}")

    # DNS static
    try:
        dns_entries = list(api.path('ip', 'dns', 'static'))
        for d in dns_entries:
            ip_str = d.get('address', '')
            _add_used_ip_if_in_network(used_ips, network, ip_str)
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)

    # Simple queue targets
    try:
        queues = list(api.path('queue', 'simple'))
        for q in queues:
            if _truthy(q.get('disabled')):
                continue
            ip_str = _extract_queue_target_ip(q)
            _add_used_ip_if_in_network(used_ips, network, ip_str)
    except Exception as e:
        logger.warning(f"find_free_ips: gagal baca simple queue: {e}")

    # Inventaris statis known device dari config bot.
    for ip_str in _iter_reserved_inventory_ips():
        _add_used_ip_if_in_network(used_ips, network, ip_str)

    # Hitung free IPs (skip network & broadcast)
    free_ips = []
    actual_used_count = 0
    for host in network.hosts():
        ip_str = str(host)
        if ip_str in used_ips:
            actual_used_count += 1
        else:
            free_ips.append(ip_str)

    return {
        'network': network_with_cidr,
        'total_hosts': network.num_addresses - 2,
        'used_count': actual_used_count,
        'free_count': len(free_ips),
        'free_ips': free_ips
    }
