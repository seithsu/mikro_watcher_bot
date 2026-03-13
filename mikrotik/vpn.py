# ============================================
# MIKROTIK/VPN - VPN Tunnel status
# ============================================

import logging

from .connection import pool
from .decorators import with_retry, cached, to_bool

logger = logging.getLogger(__name__)


@cached(ttl=10)
@with_retry
def get_vpn_tunnels():
    """Ambil status semua tunnel VPN (L2TP, PPTP, SSTP, OVPN, IPSec)."""
    api = pool.get_api()
    tunnels = []

    # VPN Client tunnels
    client_types = [
        ('L2TP', ('interface', 'l2tp-client')),
        ('PPTP', ('interface', 'pptp-client')),
        ('SSTP', ('interface', 'sstp-client')),
        ('OVPN', ('interface', 'ovpn-client')),
    ]

    for vpn_type, path_parts in client_types:
        try:
            for t in api.path(*path_parts):
                tunnels.append({
                    'type': vpn_type,
                    'name': t.get('name', ''),
                    'remote': t.get('connect-to', ''),
                    'running': to_bool(t.get('running', False)),
                    'disabled': to_bool(t.get('disabled', False)),
                    'uptime': t.get('uptime', ''),
                    'comment': t.get('comment', ''),
                })
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    # VPN Server active connections
    server_types = [
        ('L2TP-S', ('interface', 'l2tp-server', 'server')),
        ('PPTP-S', ('interface', 'pptp-server', 'server')),
        ('SSTP-S', ('interface', 'sstp-server', 'server')),
        ('OVPN-S', ('interface', 'ovpn-server', 'server')),
    ]

    for vpn_type, path_parts in server_types:
        try:
            for t in api.path(*path_parts):
                tunnels.append({
                    'type': vpn_type,
                    'name': t.get('name', ''),
                    'remote': t.get('client-address', t.get('caller-id', '')),
                    'running': to_bool(t.get('running', True)),
                    'disabled': False,
                    'uptime': t.get('uptime', ''),
                    'comment': t.get('comment', ''),
                })
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    return tunnels



