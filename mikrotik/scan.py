# ============================================
# MIKROTIK/SCAN - IP Scan (Real-time + Fallback)
# ============================================

import logging
import threading
import ssl

import librouteros

from .connection import pool, _login_auto
import core.config as cfg

logger = logging.getLogger(__name__)

_scan_lock = threading.Lock()


def _librouteros_ip_scan(interface, duration=10):
    """
    Real-time IP Scan menggunakan librouteros.

    Membuka koneksi terpisah untuk menjalankan /tool/ip-scan
    secara streaming — persis seperti di Winbox/WebFig.
    Koneksi terpisah agar tidak mengganggu pool utama.

    Returns: list of dict atau None jika gagal.
    """
    try:
        cfg.reload_router_env(min_interval=5)
        connect_kwargs = {
            'host': cfg.MIKROTIK_IP,
            'username': cfg.MIKROTIK_USER,
            'password': cfg.MIKROTIK_PASS,
            'port': int(cfg.MIKROTIK_PORT),
            'timeout': duration + 10,
            'login_method': _login_auto,  # Konsisten dengan pool utama
        }
        if cfg.MIKROTIK_USE_SSL:
            if getattr(cfg, "MIKROTIK_TLS_VERIFY", True):
                cafile = getattr(cfg, "MIKROTIK_TLS_CA_FILE", "") or None
                ctx = ssl.create_default_context(cafile=cafile)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_REQUIRED
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            connect_kwargs['ssl_wrapper'] = ctx.wrap_socket

        api = librouteros.connect(**connect_kwargs)
    except Exception as e:
        logger.warning(f"librouteros scan connect gagal: {e}")
        return None

    results = {}
    try:
        tool = api.path('tool')
        params = {
            'interface': interface,
            'duration': str(duration),
        }

        for entry in tool('ip-scan', **params):
            ip = entry.get('address', '')
            if not ip:
                continue

            mac = entry.get('mac-address', '')
            dns = entry.get('dns', '')
            hostname = entry.get('host-name', '') or dns or '-'

            results[ip] = {
                'ip': ip,
                'mac': mac or '-',
                'hostname': hostname,
                'interface': interface,
                'dns': dns or '-',
            }
    except Exception as e:
        logger.warning(f"librouteros ip-scan error: {e}")
        if not results:
            try:
                api.close()
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
            return None

    try:
        api.close()
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    return list(results.values())


def _arp_dhcp_scan(interface):
    """
    Fallback scan: ARP table + DHCP leases.
    Digunakan jika librouteros ip-scan gagal.
    """
    results_dict = {}
    dhcp_mac_map = {}
    dhcp_ip_map = {}
    dhcp_list = []

    # Ambil DHCP leases untuk mapping hostname
    try:
        api = pool.get_api()
        dhcp_list = list(api.path('ip', 'dhcp-server', 'lease'))
        for d in dhcp_list:
            mac = (d.get('mac-address') or '').upper()
            ip = d.get('address', '')
            hostname = d.get('host-name', '') or d.get('comment', '') or ''
            if mac:
                dhcp_mac_map[mac] = hostname
            if ip:
                dhcp_ip_map[ip] = hostname
    except Exception as e:
        logger.warning(f"Fallback: gagal ambil DHCP leases: {e}")
        pool.reset()

    # Ambil ARP table, filter per interface
    try:
        api = pool.get_api()
        arp_list = list(api.path('ip', 'arp'))

        for arp in arp_list:
            if (arp.get('interface') or '').lower() != interface.lower():
                continue

            ip = arp.get('address', '')
            mac = arp.get('mac-address', '')
            if not ip:
                continue

            hostname = ''
            if mac:
                hostname = dhcp_mac_map.get(mac.upper(), '')
            if not hostname:
                hostname = dhcp_ip_map.get(ip, '')

            results_dict[ip] = {
                'ip': ip,
                'mac': mac or '-',
                'hostname': hostname or '-',
                'interface': interface,
                'dns': '-',
            }
    except Exception as e:
        logger.error(f"Fallback: gagal ambil ARP: {e}")
        pool.reset()

    # Tambahkan DHCP bound leases yang belum di ARP
    for d in dhcp_list:
        ip = d.get('address', '')
        status = d.get('status', '')
        if status == 'bound' and ip and ip not in results_dict:
            hostname = d.get('host-name', '') or d.get('comment', '') or '-'
            results_dict[ip] = {
                'ip': ip,
                'mac': d.get('mac-address', '-'),
                'hostname': hostname,
                'interface': interface,
                'dns': '-',
            }

    return list(results_dict.values())


def run_ip_scan(interface, duration=10):
    """
    Scan device aktif pada interface tertentu.

    Strategi:
    1. Coba real-time /tool/ip-scan via librouteros (seperti Winbox)
    2. Jika gagal, fallback ke ARP + DHCP hybrid
    """
    with _scan_lock:
        # Ambil DHCP mapping untuk enrich hasil
        dhcp_mac_map = {}
        dhcp_ip_map = {}
        try:
            api = pool.get_api()
            dhcp_list = list(api.path('ip', 'dhcp-server', 'lease'))
            for d in dhcp_list:
                mac = (d.get('mac-address') or '').upper()
                ip = d.get('address', '')
                hostname = d.get('host-name', '') or d.get('comment', '') or ''
                if mac and hostname:
                    dhcp_mac_map[mac] = hostname
                if ip and hostname:
                    dhcp_ip_map[ip] = hostname
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
        # Step 1: Coba real-time ip-scan
        logger.info(f"IP Scan: librouteros ip-scan pada {interface} ({duration}s)...")
        results = _librouteros_ip_scan(interface, duration)

        if results is not None:
            logger.info(f"IP Scan: berhasil, {len(results)} device ditemukan")
            # Enrich hostname dari DHCP
            for device in results:
                if device['hostname'] == '-' or not device['hostname']:
                    mac = (device.get('mac') or '').upper()
                    ip = device.get('ip', '')
                    hostname = dhcp_mac_map.get(mac, '') or dhcp_ip_map.get(ip, '')
                    if hostname:
                        device['hostname'] = hostname
        else:
            # Step 2: Fallback ke ARP + DHCP
            logger.info(f"IP Scan: fallback ARP+DHCP pada {interface}...")
            results = _arp_dhcp_scan(interface)
            logger.info(f"IP Scan: fallback, {len(results)} device ditemukan")

        # Sort by IP numerically
        try:
            results.sort(key=lambda x: tuple(int(p) for p in x['ip'].split('.')))
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
        return results


