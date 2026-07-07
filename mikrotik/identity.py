# ============================================
# MIKROTIK/IDENTITY - Router Device Identity
# Identifikasi perangkat MikroTik berdasarkan MAC Address
# ============================================

import logging
import time

from .connection import pool
from .decorators import with_retry, cached
import core.config as cfg

logger = logging.getLogger(__name__)

# Cache identity agar tidak query berulang setiap render UI
_identity_cache = {
    "label": None,
    "mac": None,
    "device_num": None,
    "ts": 0.0,
}
_IDENTITY_CACHE_TTL = 300.0  # 5 menit


def _find_primary_mac(interfaces):
    """Cari MAC Address dari interface utama router (prioritas ether1 > bridge > ether2).

    Return MAC string uppercase atau None.
    """
    priority_keywords = ["ether1", "bridge", "local", "ether2"]

    for keyword in priority_keywords:
        for iface in interfaces:
            name = str(iface.get("name", "")).lower()
            if keyword in name:
                mac = str(iface.get("mac-address", "") or iface.get("mac", "") or "").strip().upper()
                if mac and mac != "00:00:00:00:00:00":
                    return mac

    # Fallback: ambil MAC pertama yang valid
    for iface in interfaces:
        mac = str(iface.get("mac-address", "") or iface.get("mac", "") or "").strip().upper()
        if mac and mac != "00:00:00:00:00:00":
            return mac

    return None


def _match_device(mac, devices_map):
    """Cocokkan MAC dengan mapping MIKROTIK_DEVICES.

    Return (label, device_number) atau (None, None).
    """
    if not mac or not devices_map:
        return None, None

    mac_upper = mac.strip().upper()

    # Cari exact match
    label = devices_map.get(mac_upper)
    if label:
        # Hitung nomor device (urutan di mapping)
        keys = list(devices_map.keys())
        try:
            device_num = keys.index(mac_upper) + 1
        except ValueError:
            device_num = None
        return label, device_num

    return None, None


@cached(ttl=60)
@with_retry
def _fetch_interface_macs():
    """Ambil daftar interface dengan MAC address dari router."""
    api = pool.get_api()
    ifaces = list(api.path('interface'))
    results = []
    for iface in ifaces:
        results.append({
            'name': iface.get('name', ''),
            'type': iface.get('type', ''),
            'mac-address': iface.get('mac-address', ''),
            'mac': iface.get('mac-address', ''),
        })
    return results


def get_router_identity_label():
    """Identifikasi perangkat MikroTik yang sedang terhubung.

    Return dict:
        {
            "label": "MikroTik 1 (Baru)" atau None,
            "mac": "AA:BB:CC:DD:EE:FF" atau None,
            "device_num": 1 atau None,
            "known": True/False,
        }
    """
    now = time.time()

    # Gunakan cache jika masih segar
    if (
        _identity_cache["ts"] > 0
        and (now - _identity_cache["ts"]) < _IDENTITY_CACHE_TTL
        and _identity_cache["mac"] is not None
    ):
        devices_map = dict(getattr(cfg, "MIKROTIK_DEVICES", {}) or {})
        label, device_num = _match_device(_identity_cache["mac"], devices_map)
        return {
            "label": label,
            "mac": _identity_cache["mac"],
            "device_num": device_num,
            "known": label is not None,
        }

    try:
        interfaces = _fetch_interface_macs()
        mac = _find_primary_mac(interfaces)
    except Exception as e:
        logger.debug("Gagal ambil MAC untuk identity: %s", e)
        mac = None

    if mac:
        _identity_cache["mac"] = mac
        _identity_cache["ts"] = now

    devices_map = dict(getattr(cfg, "MIKROTIK_DEVICES", {}) or {})
    label, device_num = _match_device(mac, devices_map)

    _identity_cache["label"] = label
    _identity_cache["device_num"] = device_num

    return {
        "label": label,
        "mac": mac,
        "device_num": device_num,
        "known": label is not None,
    }


def invalidate_identity_cache():
    """Invalidate cache identity (dipanggil saat .env berubah/hot-swap)."""
    _identity_cache["label"] = None
    _identity_cache["mac"] = None
    _identity_cache["device_num"] = None
    _identity_cache["ts"] = 0.0


def format_identity_line(identity=None, prefix="🔖"):
    """Format satu baris teks identity untuk tampilan Telegram HTML.

    Return string HTML atau kosong jika MAC tidak tersedia.
    """
    if identity is None:
        try:
            identity = get_router_identity_label()
        except Exception:
            return ""

    mac = identity.get("mac")
    if not mac:
        return ""

    label = identity.get("label")
    if label:
        return f"{prefix} <b>{label}</b> [<code>{mac}</code>]"
    else:
        return f"{prefix} MikroTik: <i>Tidak dikenal</i> [<code>{mac}</code>]"
