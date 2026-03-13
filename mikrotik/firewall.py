# ============================================
# MIKROTIK/FIREWALL - Firewall rules & Address List
# ============================================

import logging

from .connection import pool
from .decorators import with_retry, cached, to_bool, to_int

logger = logging.getLogger(__name__)


@cached(ttl=10)
@with_retry
def get_firewall_rules(chain_type="filter"):
    """
    Ambil firewall rules.
    chain_type: 'filter' untuk /ip/firewall/filter, 'nat' untuk /ip/firewall/nat
    """
    api = pool.get_api()
    rules = list(api.path('ip', 'firewall', chain_type))
    return [
        {
            'id': r.get('.id', ''),
            'chain': r.get('chain', ''),
            'action': r.get('action', ''),
            'src_address': r.get('src-address', ''),
            'dst_address': r.get('dst-address', ''),
            'protocol': r.get('protocol', ''),
            'dst_port': r.get('dst-port', ''),
            'in_interface': r.get('in-interface', ''),
            'out_interface': r.get('out-interface', ''),
            'comment': r.get('comment', ''),
            'disabled': to_bool(r.get('disabled', False)),
            'bytes': str(r.get('bytes', '0')),
            'packets': str(r.get('packets', '0')),
        }
        for r in rules
    ]


@with_retry
def toggle_firewall_rule(rule_id: str, chain_type: str = "filter", disabled: bool = True):
    """Enable atau disable firewall rule."""
    api = pool.get_api()
    api.path('ip', 'firewall', chain_type).update(
        **{'.id': rule_id, 'disabled': str(disabled).lower()}
    )
    return True


@with_retry
def block_ip(ip_address: str, reason: str = "auto-block", list_name: str = "auto_block"):
    """
    Memasukkan IP ke IP -> Firewall -> Address List.
    List name akan menjadi 'auto_block' secara default.
    """
    api = pool.get_api()
    addr_list = api.path('ip', 'firewall', 'address-list')

    # Cek apakah sudah ada
    all_entries = list(addr_list)
    existing = [e for e in all_entries
                if e.get('address') == ip_address and e.get('list') == list_name]

    if existing:
        addr_list.update(**{'.id': existing[0].get('.id'), 'comment': reason})
        return True

    addr_list.add(list=list_name, address=ip_address, comment=reason)
    return True


@with_retry
def unblock_ip(ip_address: str, list_name: str = "auto_block"):
    """Menghapus IP dari IP -> Firewall -> Address List."""
    api = pool.get_api()
    addr_list = api.path('ip', 'firewall', 'address-list')

    all_entries = list(addr_list)
    existing = [e for e in all_entries
                if e.get('address') == ip_address and e.get('list') == list_name]

    if not existing:
        return False

    for item in existing:
        addr_list.remove(item.get('.id'))

    return True
