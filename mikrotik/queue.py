# ============================================
# MIKROTIK/QUEUE - Simple Queue management
# ============================================

import logging

from .connection import pool
from .decorators import with_retry, cached

logger = logging.getLogger(__name__)


def format_rate_bps(rate_bps):
    """Format bit-per-second ke satuan yang mudah dibaca."""
    try:
        value = float(rate_bps or 0)
    except (TypeError, ValueError):
        value = 0.0

    units = ("bps", "Kbps", "Mbps", "Gbps", "Tbps")
    unit_idx = 0
    while value >= 1000 and unit_idx < len(units) - 1:
        value /= 1000.0
        unit_idx += 1

    if unit_idx == 0:
        return f"{int(value)} {units[unit_idx]}"
    if value >= 100:
        return f"{value:.0f} {units[unit_idx]}"
    if value >= 10:
        return f"{value:.1f} {units[unit_idx]}"
    return f"{value:.2f} {units[unit_idx]}"


@cached(ttl=5)
@with_retry
def get_simple_queues():
    """Ambil daftar Simple Queue."""
    api = pool.get_api()
    queues = list(api.path('queue', 'simple'))

    results = []
    for q in queues:
        results.append({
            'id': q.get('.id', ''),
            '.id': q.get('.id', ''),
            'name': q.get('name', ''),
            'target': q.get('target', ''),
            'max-limit': q.get('max-limit', '0/0'),
            'rate': q.get('rate', '0/0'),
            'comment': q.get('comment', ''),
        })
    return results


@with_retry
def get_top_queues(limit=10):
    """
    Mengambil data Simple Queues, membaca rate saat ini,
    lalu mensortir berdasarkan total (TX + RX) rate tertinggi.
    """
    api = pool.get_api()
    queues = list(api.path('queue', 'simple'))

    results = []
    for q in queues:
        name = q.get('name', 'Unknown')
        target = q.get('target', '')
        rate_str = q.get('rate', '0/0')

        # rate_str bisa string "rx/tx" atau sudah di-parse
        if isinstance(rate_str, str):
            try:
                rx_rate, tx_rate = map(int, rate_str.split('/'))
            except Exception:
                rx_rate, tx_rate = 0, 0
        else:
            rx_rate, tx_rate = 0, 0

        total_rate = rx_rate + tx_rate

        if total_rate == 0:
            continue

        results.append({
            'name': name,
            'target': target,
            'rx_rate': rx_rate,
            'tx_rate': tx_rate,
            'total_rate': total_rate,
            'rx_rate_fmt': format_rate_bps(rx_rate),
            'tx_rate_fmt': format_rate_bps(tx_rate),
            'total_rate_fmt': format_rate_bps(total_rate),
        })

    results.sort(key=lambda x: x['total_rate'], reverse=True)
    return results[:limit]


@with_retry
def remove_simple_queue(queue_id):
    """Hapus queue berdasarkan ID."""
    api = pool.get_api()
    api.path('queue', 'simple').remove(queue_id)
    return True
