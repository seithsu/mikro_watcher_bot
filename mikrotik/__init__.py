# ============================================
# MIKROTIK Package - Public API
# ============================================
#
# Backward-compatible exports:
# Semua `from mikrotik import X` yang ada di codebase
# tetap bekerja tanpa perubahan.
# ============================================

# -- Connection pool (used by monitor.py, bot.py, handlers/general.py) --
from .connection import pool as _pool

# -- Decorators (internal, tapi _format_bytes dipakai beberapa handler) --
from .decorators import format_bytes as _format_bytes

# -- System --
from .system import (
    get_status,
    reboot_router,
    export_router_backup,
    export_router_backup_ftp,
    get_system_routerboard,
)

# -- Network --
from .network import (
    get_interfaces,
    get_ip_addresses,
    get_traffic,
    get_dhcp_leases,
    get_dhcp_usage_count,
    get_arp_anomalies,
    get_default_gateway,
    get_mikrotik_log,
    get_monitored_aps,
    get_monitored_servers,
    get_monitored_critical_devices,
    get_active_critical_device_names,
)

# -- Scan --
from .scan import run_ip_scan

# -- Queue --
from .queue import (
    get_simple_queues,
    get_top_queues,
    remove_simple_queue,
)

# -- DNS --
from .dns import (
    get_dns_static,
    add_dns_static,
    remove_dns_static,
)

# -- Scheduler --
from .scheduler import (
    get_schedulers,
    set_scheduler_status,
)

# -- VPN --
from .vpn import get_vpn_tunnels

# -- Firewall --
from .firewall import (
    get_firewall_rules,
    toggle_firewall_rule,
    block_ip,
    unblock_ip,
)

# -- Tools --
from .tools import (
    ping_host,
    send_wol,
    find_free_ips,
)
