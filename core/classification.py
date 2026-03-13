# ============================================
# CLASSIFICATION - Network Status Classification
# Single source of truth untuk klasifikasi jaringan
# ============================================

_RED = "\U0001F534"
_ORANGE = "\U0001F7E0"
_YELLOW = "\U0001F7E1"
_GREEN = "\U0001F7E2"


def _collect_extra_service_downs(netwatch_state, tcp_services=None, dns_key=None):
    """Kumpulkan service-level downs (TCP/DNS) untuk klasifikasi lanjutan."""
    downs = []

    if dns_key and not netwatch_state.get(dns_key, True):
        downs.append("DNS Resolver")

    for service in tcp_services or []:
        ip = service.get("ip", "")
        port = service.get("port", "")
        if not ip or port == "":
            continue
        key = f"{ip}:{port}"
        if not netwatch_state.get(key, True):
            name = service.get("name", "TCP Service")
            downs.append(f"{name}:{port}")

    return downs


def _reverse_mapping(src):
    return {v: k for k, v in (src or {}).items()}


def classify_network_status(
    netwatch_state,
    servers,
    aps,
    router_ip,
    gw_wan,
    gw_inet,
    tcp_services=None,
    dns_key=None,
    critical_devices=None,
):
    """Menentukan kategori status jaringan berdasarkan state terkini."""
    router_up = netwatch_state.get(router_ip, True)
    gw_up = netwatch_state.get(gw_wan, True) if gw_wan else True
    inet_up = netwatch_state.get(gw_inet, True) if gw_inet else True

    server_downs = [k for k, v in (servers or {}).items() if not netwatch_state.get(v, True)]
    critical_downs = [k for k, v in (critical_devices or {}).items() if not netwatch_state.get(v, True)]
    ap_ups = sum(1 for v in (aps or {}).values() if netwatch_state.get(v, False))

    if not router_up:
        return f"{_RED} CORE DOWN (Router MikroTik tidak terjangkau)"
    if not gw_up:
        return f"{_RED} WAN GATEWAY DOWN (Cek Modem Indibiz/ONT)"
    if not inet_up:
        return f"{_RED} INTERNET UPSTREAM DOWN (Koneksi publik mati)"
    if critical_downs:
        return f"{_RED} CRITICAL DEVICE DOWN ({', '.join(critical_downs)})"
    if server_downs:
        return f"{_ORANGE} SERVER ISSUE ({', '.join(server_downs)})"
    if len(aps or {}) > 0 and ap_ups < len(aps or {}):
        return f"{_YELLOW} WIFI PARTIAL ({ap_ups}/{len(aps or {})} UP)"

    extra_downs = _collect_extra_service_downs(
        netwatch_state, tcp_services=tcp_services, dns_key=dns_key
    )
    if extra_downs:
        return f"{_ORANGE} SERVICE ISSUE ({', '.join(extra_downs)})"

    return f"{_GREEN} NORMAL"


def classify_short(
    netwatch_state,
    servers,
    aps,
    router_ip,
    gw_wan,
    gw_inet,
    tcp_services=None,
    dns_key=None,
    critical_devices=None,
):
    """Versi pendek klasifikasi (tanpa deskripsi dalam kurung)."""
    router_up = netwatch_state.get(router_ip, True)
    gw_up = netwatch_state.get(gw_wan, True) if gw_wan else True
    inet_up = netwatch_state.get(gw_inet, True) if gw_inet else True

    server_downs = [k for k, v in (servers or {}).items() if not netwatch_state.get(v, True)]
    critical_downs = [k for k, v in (critical_devices or {}).items() if not netwatch_state.get(v, True)]
    ap_ups = sum(1 for v in (aps or {}).values() if netwatch_state.get(v, False))

    if not router_up:
        return f"{_RED} CORE DOWN"
    if not gw_up:
        return f"{_RED} WAN GATEWAY DOWN"
    if not inet_up:
        return f"{_RED} INTERNET UPSTREAM DOWN"
    if critical_downs:
        return f"{_RED} CRITICAL DEVICE DOWN ({', '.join(critical_downs)})"
    if server_downs:
        return f"{_ORANGE} SERVER ISSUE ({', '.join(server_downs)})"
    if len(aps or {}) > 0 and ap_ups < len(aps or {}):
        return f"{_YELLOW} WIFI PARTIAL ({ap_ups}/{len(aps or {})} UP)"

    extra_downs = _collect_extra_service_downs(
        netwatch_state, tcp_services=tcp_services, dns_key=dns_key
    )
    if extra_downs:
        return f"{_ORANGE} SERVICE ISSUE ({', '.join(extra_downs)})"

    return f"{_GREEN} NORMAL"


def classify_host_short(
    netwatch_state,
    host_key,
    servers,
    aps,
    router_ip,
    gw_wan,
    gw_inet,
    tcp_services=None,
    dns_key=None,
    critical_devices=None,
):
    """Klasifikasi cepat yang spesifik ke host alert, bukan snapshot global."""
    router_up = netwatch_state.get(router_ip, True)
    gw_up = netwatch_state.get(gw_wan, True) if gw_wan else True
    inet_up = netwatch_state.get(gw_inet, True) if gw_inet else True
    host_up = netwatch_state.get(host_key, True)

    if not router_up:
        return f"{_RED} CORE DOWN"
    if not gw_up and host_key != router_ip:
        return f"{_RED} WAN GATEWAY DOWN"
    if not inet_up and host_key not in {router_ip, gw_wan}:
        return f"{_RED} INTERNET UPSTREAM DOWN"

    server_lookup = _reverse_mapping(servers)
    ap_lookup = _reverse_mapping(aps)
    critical_lookup = _reverse_mapping(critical_devices)
    tcp_lookup = {}
    for service in tcp_services or []:
        ip = service.get("ip", "")
        port = service.get("port", "")
        if not ip or port == "":
            continue
        name = service.get("name", "TCP Service")
        tcp_lookup[f"{ip}:{port}"] = f"{name}:{port}"

    if host_key == dns_key and not host_up:
        return f"{_ORANGE} DNS RESOLVER DOWN"
    if host_key in tcp_lookup and not host_up:
        return f"{_ORANGE} TCP SERVICE DOWN ({tcp_lookup[host_key]})"
    if host_key in critical_lookup and not host_up:
        return f"{_RED} CRITICAL DEVICE DOWN ({critical_lookup[host_key]})"
    if host_key in server_lookup and not host_up:
        return f"{_ORANGE} SERVER ISSUE ({server_lookup[host_key]})"
    if host_key in ap_lookup and not host_up:
        return f"{_YELLOW} WIFI AP DOWN ({ap_lookup[host_key]})"
    if not host_up:
        return f"{_ORANGE} HOST DOWN"
    return f"{_GREEN} NORMAL"
