# ============================================
# MIKROTIK/DNS - DNS Static CRUD
# ============================================

import logging

from .connection import pool
from .decorators import with_retry, cached, to_bool

logger = logging.getLogger(__name__)


@cached(ttl=10)
@with_retry
def get_dns_static():
    """Ambil daftar DNS Static entries."""
    api = pool.get_api()
    entries = list(api.path('ip', 'dns', 'static'))
    return [
        {
            'id': e.get('.id', ''),
            'name': e.get('name', ''),
            'address': e.get('address', ''),
            'ttl': e.get('ttl', 'auto'),
            'disabled': to_bool(e.get('disabled', False)),
            'comment': e.get('comment', ''),
        }
        for e in entries
    ]


@with_retry
def add_dns_static(name: str, address: str, comment: str = ""):
    """Tambah DNS Static entry baru."""
    api = pool.get_api()
    params = {'name': name, 'address': address}
    if comment:
        params['comment'] = comment
    api.path('ip', 'dns', 'static').add(**params)
    return True


@with_retry
def remove_dns_static(entry_id: str):
    """Hapus DNS Static entry berdasarkan ID."""
    api = pool.get_api()
    api.path('ip', 'dns', 'static').remove(entry_id)
    return True
