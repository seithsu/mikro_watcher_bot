# ============================================
# MIKROTIK/_ARP_UTILS - Shared ARP helpers
# Single source of truth untuk _truthy dan
# _is_active_arp_entry — dipakai oleh:
#   scan.py, tools.py, network.py
# ============================================

# FIND-25 FIX: Duplikasi dihapus dari scan.py, tools.py, network.py.
# Jika ada perubahan logika (misal status ARP baru dari RouterOS versi terbaru),
# cukup edit file ini — semua modul otomatis ikut.


def _truthy(value):
    """Konversi nilai RouterOS ke boolean.

    RouterOS merepresentasikan boolean sebagai string 'true'/'false',
    'yes'/'no', atau '1'/'0'. Fungsi ini menangani semua varian tsb.
    """
    return str(value).strip().lower() in {"true", "yes", "on", "1"}


# Status ARP yang dianggap tidak aktif / bukan host hidup.
_INACTIVE_ARP_STATUSES = frozenset({
    "incomplete", "failed", "stale", "delay", "probe"
})

# MAC address null yang harus diabaikan.
_NULL_MACS = frozenset({
    "00:00:00:00:00:00",
    "00-00-00-00-00-00",
})


def _is_active_arp_entry(arp):
    """Tentukan apakah entri ARP layak dianggap sebagai host aktif.

    Canonical implementation — dipakai oleh scan.py, tools.py, network.py.

    Kriteria host AKTIF:
    - Punya MAC address valid (bukan null/broadcast)
    - Status ARP bukan incomplete/failed/stale/delay/probe
    - Field 'complete' (jika ada) bernilai truthy
    - Bukan 'invalid' atau 'disabled'
    """
    mac = str(arp.get("mac-address", "") or "").strip()
    if not mac or mac in _NULL_MACS:
        return False

    status = str(arp.get("status", "") or "").strip().lower()
    if status in _INACTIVE_ARP_STATUSES:
        return False

    # Field 'complete' tidak selalu ada (tergantung versi RouterOS).
    if "complete" in arp and not _truthy(arp.get("complete")):
        return False

    if _truthy(arp.get("invalid")) or _truthy(arp.get("disabled")):
        return False

    return True
