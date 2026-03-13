import pytest
from core.classification import (
    _collect_extra_service_downs,
    _reverse_mapping,
    classify_network_status,
    classify_short,
    classify_host_short,
)

def test_classify_network_status_all_up():
    """Test ketika semua host UP."""
    netwatch_state = {
        '192.168.1.1': True,
        '1.1.1.1': True,
        '8.8.8.8': True,
        '192.168.1.10': True,
        '192.168.1.20': True
    }
    servers = {'Server A': '192.168.1.10'}
    aps = {'AP 1': '192.168.1.20'}
    
    result = classify_network_status(
        netwatch_state, servers, aps,
        router_ip='192.168.1.1',
        gw_wan='1.1.1.1',
        gw_inet='8.8.8.8'
    )
    assert result == "🟢 NORMAL", f"Expected NORMAL, got {result}"

def test_classify_network_status_core_down():
    """Test ketika Router (Core) DOWN."""
    netwatch_state = {
        '192.168.1.1': False,  # Core down
        '1.1.1.1': False,
        '8.8.8.8': False
    }
    servers = {}
    aps = {}
    
    result = classify_network_status(
        netwatch_state, servers, aps,
        router_ip='192.168.1.1',
        gw_wan='1.1.1.1',
        gw_inet='8.8.8.8'
    )
    assert "CORE DOWN" in result
    
    # Short version
    result_short = classify_short(
        netwatch_state, servers, aps,
        router_ip='192.168.1.1',
        gw_wan='1.1.1.1',
        gw_inet='8.8.8.8'
    )
    assert result_short == "🔴 CORE DOWN"

def test_classify_network_status_server_down():
    """Test ketika Server DOWN tapi router dan koneksi UP."""
    netwatch_state = {
        '192.168.1.1': True,
        '1.1.1.1': True,
        '8.8.8.8': True,
        '192.168.1.10': False  # Server down
    }
    servers = {'Server A': '192.168.1.10'}
    aps = {}
    
    result = classify_network_status(
        netwatch_state, servers, aps,
        router_ip='192.168.1.1',
        gw_wan='1.1.1.1',
        gw_inet='8.8.8.8'
    )
    assert "SERVER ISSUE" in result
    assert "Server A" in result

def test_classify_network_status_wifi_partial():
    """Test ketika 1 dari 2 AP DOWN."""
    netwatch_state = {
        '192.168.1.1': True,
        '1.1.1.1': True,
        '8.8.8.8': True,
        '192.168.1.20': True,   # AP 1 UP
        '192.168.1.21': False   # AP 2 DOWN
    }
    servers = {}
    aps = {'AP 1': '192.168.1.20', 'AP 2': '192.168.1.21'}
    
    result = classify_network_status(
        netwatch_state, servers, aps,
        router_ip='192.168.1.1',
        gw_wan='1.1.1.1',
        gw_inet='8.8.8.8'
    )
    assert "WIFI PARTIAL" in result
    assert "1/2 UP" in result


def test_classify_network_status_service_issue_tcp_dns():
    """Test service issue ketika hanya TCP/DNS yang down."""
    netwatch_state = {
        '192.168.1.1': True,
        '1.1.1.1': True,
        '8.8.8.8': True,
        '10.10.10.10:443': False,
        'DNS_Resolv': False,
    }

    result = classify_network_status(
        netwatch_state, {}, {},
        router_ip='192.168.1.1',
        gw_wan='1.1.1.1',
        gw_inet='8.8.8.8',
        tcp_services=[{'name': 'API', 'ip': '10.10.10.10', 'port': 443}],
        dns_key='DNS_Resolv',
    )
    assert "SERVICE ISSUE" in result
    assert "API:443" in result
    assert "DNS Resolver" in result


def test_classify_network_status_critical_device_down():
    """Critical device DOWN harus tidak pernah diklasifikasikan NORMAL."""
    netwatch_state = {
        '192.168.1.1': True,
        '1.1.1.1': True,
        '8.8.8.8': True,
        '192.168.1.33': False,  # critical down
    }

    result = classify_network_status(
        netwatch_state, {}, {},
        router_ip='192.168.1.1',
        gw_wan='1.1.1.1',
        gw_inet='8.8.8.8',
        critical_devices={'KOMP PENDAFTARAN POLI': '192.168.1.33'},
    )
    assert "CRITICAL DEVICE DOWN" in result


def test_classify_host_short_critical_host_specific():
    """Klasifikasi host-spesifik harus menandai host critical sebagai critical down."""
    netwatch_state = {
        '192.168.1.1': True,
        '1.1.1.1': True,
        '8.8.8.8': True,
        '192.168.1.33': False,
    }

    result = classify_host_short(
        netwatch_state,
        host_key='192.168.1.33',
        servers={},
        aps={},
        router_ip='192.168.1.1',
        gw_wan='1.1.1.1',
        gw_inet='8.8.8.8',
        critical_devices={'KOMP PENDAFTARAN POLI': '192.168.1.33'},
    )
    assert "CRITICAL DEVICE DOWN" in result


def test_collect_extra_service_downs_skips_invalid_entries_and_marks_down():
    downs = _collect_extra_service_downs(
        {
            "DNS_Resolv": False,
            "10.0.0.10:443": False,
            "10.0.0.11:80": True,
        },
        tcp_services=[
            {"name": "API", "ip": "10.0.0.10", "port": 443},
            {"name": "WEB", "ip": "10.0.0.11", "port": 80},
            {"name": "BROKEN-NO-IP", "port": 22},
            {"name": "BROKEN-NO-PORT", "ip": "10.0.0.12", "port": ""},
        ],
        dns_key="DNS_Resolv",
    )

    assert downs == ["DNS Resolver", "API:443"]


def test_reverse_mapping_handles_none_and_regular_dict():
    assert _reverse_mapping(None) == {}
    assert _reverse_mapping({"Server A": "10.0.0.1"}) == {"10.0.0.1": "Server A"}


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"router": True, "wan": False, "inet": True}, "WAN GATEWAY DOWN"),
        ({"router": True, "wan": True, "inet": False}, "INTERNET UPSTREAM DOWN"),
        ({"router": True, "wan": True, "inet": True, "10.0.0.50": False}, "CRITICAL DEVICE DOWN"),
        ({"router": True, "wan": True, "inet": True, "10.0.0.60": False}, "SERVER ISSUE"),
        ({"router": True, "wan": True, "inet": True, "10.0.0.70": False}, "WIFI PARTIAL"),
    ],
)
def test_classify_short_additional_branches(state, expected):
    result = classify_short(
        state,
        servers={"SIMRS": "10.0.0.60"},
        aps={"AP-LT1": "10.0.0.70"},
        router_ip="router",
        gw_wan="wan",
        gw_inet="inet",
        critical_devices={"KOMP IGD": "10.0.0.50"},
    )
    assert expected in result


def test_classify_short_service_issue_and_normal():
    result_service = classify_short(
        {"router": True, "wan": True, "inet": True, "svc:443": False},
        servers={},
        aps={},
        router_ip="router",
        gw_wan="wan",
        gw_inet="inet",
        tcp_services=[{"name": "API", "ip": "svc", "port": 443}],
    )
    assert "SERVICE ISSUE" in result_service

    result_normal = classify_short(
        {"router": True, "wan": True, "inet": True},
        servers={},
        aps={},
        router_ip="router",
        gw_wan="wan",
        gw_inet="inet",
    )
    assert "NORMAL" in result_normal


@pytest.mark.parametrize(
    ("host_key", "state", "expected"),
    [
        ("10.0.0.2", {"router": True, "wan": False, "inet": True, "10.0.0.2": False}, "WAN GATEWAY DOWN"),
        ("10.0.0.3", {"router": True, "wan": True, "inet": False, "10.0.0.3": False}, "INTERNET UPSTREAM DOWN"),
        ("DNS_Resolv", {"router": True, "wan": True, "inet": True, "DNS_Resolv": False}, "DNS RESOLVER DOWN"),
        ("10.0.0.10:443", {"router": True, "wan": True, "inet": True, "10.0.0.10:443": False}, "TCP SERVICE DOWN"),
        ("10.0.0.60", {"router": True, "wan": True, "inet": True, "10.0.0.60": False}, "SERVER ISSUE"),
        ("10.0.0.70", {"router": True, "wan": True, "inet": True, "10.0.0.70": False}, "WIFI AP DOWN"),
        ("10.0.0.88", {"router": True, "wan": True, "inet": True, "10.0.0.88": False}, "HOST DOWN"),
        ("10.0.0.99", {"router": True, "wan": True, "inet": True, "10.0.0.99": True}, "NORMAL"),
    ],
)
def test_classify_host_short_branch_matrix(host_key, state, expected):
    result = classify_host_short(
        state,
        host_key=host_key,
        servers={"SIMRS": "10.0.0.60"},
        aps={"AP-LT1": "10.0.0.70"},
        router_ip="router",
        gw_wan="wan",
        gw_inet="inet",
        tcp_services=[
            {"name": "API", "ip": "10.0.0.10", "port": 443},
            {"name": "BROKEN", "ip": "", "port": 22},
            {"name": "BROKEN2", "ip": "10.0.0.12", "port": ""},
        ],
        dns_key="DNS_Resolv",
        critical_devices={"KOMP IGD": "10.0.0.50"},
    )
    assert expected in result
