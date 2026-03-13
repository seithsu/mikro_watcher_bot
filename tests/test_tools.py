import pytest
from unittest.mock import patch, MagicMock

@patch('mikrotik.tools.pool.get_api')
class TestTools:
    def test_ping_host_empty_results(self, mock_get_api):
        from mikrotik.tools import ping_host

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        mock_api.return_value = iter([])

        result = ping_host("1.1.1.1", count=3)
        assert result["sent"] == 3
        assert result["received"] == 0
        assert result["results"] == []

    def test_ping_host(self, mock_get_api):
        from mikrotik.tools import ping_host

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        
        # Simulate api('/ping', ...) call
        # RouterOS v6 returns time as string with 'ms' e.g., '10ms'
        mock_api.return_value = iter([
            {'host': '1.1.1.1', 'seq': 0, 'time': '10ms', 'status': 'ok', 'ttl': 64},
            {'host': '1.1.1.1', 'seq': 1, 'time': '20ms', 'status': 'ok', 'ttl': 64}
        ])

        result = ping_host('1.1.1.1', count=2)
        assert result['host'] == '1.1.1.1'
        assert result['sent'] == 2
        assert result['received'] == 2
        assert result['loss'] == 0
        assert result['avg_rtt'] == 15.0

    def test_ping_host_loss(self, mock_get_api):
        from mikrotik.tools import ping_host

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        
        # Simulate api('/ping', ...) call with timeout (no host/time fields)
        mock_api.return_value = iter([
            {'seq': 0, 'status': 'timeout'},
            {'seq': 1, 'status': 'timeout'}
        ])

        result = ping_host('192.0.2.1', count=2)
        assert result['sent'] == 2
        assert result['received'] == 0
        assert result['loss'] == 100.0

    def test_ping_host_ignores_summary_row(self, mock_get_api):
        from mikrotik.tools import ping_host

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api

        # Simulasi output RouterOS: 2 paket timeout + 1 baris summary.
        # Summary tidak boleh dihitung sebagai paket sukses.
        mock_api.return_value = iter([
            {'host': '192.168.3.250', 'seq': 0, 'status': 'timeout'},
            {'host': '192.168.3.250', 'seq': 1, 'status': 'timeout'},
            {'host': '192.168.3.250', 'packet-loss': '100'},
        ])

        result = ping_host('192.168.3.250', count=2)
        assert result['sent'] == 2
        assert result['received'] == 0
        assert result['loss'] == 100

    def test_ping_host_packet_loss_percent_string(self, mock_get_api):
        from mikrotik.tools import ping_host

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        mock_api.return_value = iter([
            {"packet-loss": "50%"},
        ])

        result = ping_host("192.0.2.10", count=4)
        assert result["sent"] == 4
        assert result["loss"] == 50

    def test_send_wol(self, mock_get_api):
        from mikrotik.tools import send_wol

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        mock_api.return_value = iter([{}])

        assert send_wol("AA:BB:CC:DD:EE:FF", "bridge") is True
        mock_api.assert_called_once_with("/tool/wol", interface="bridge", mac="AA:BB:CC:DD:EE:FF")

    def test_find_free_ips_invalid_network(self, mock_get_api):
        from mikrotik.tools import find_free_ips

        result = find_free_ips("bad-network")
        assert "error" in result

    def test_find_free_ips(self, mock_get_api):
        from mikrotik.tools import find_free_ips

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        
        def mock_path(*args):
            p = MagicMock()
            if args == ('ip', 'dhcp-server', 'lease'):
                return iter([{'address': '192.168.1.10'}])
            if args == ('ip', 'arp'):
                return iter([{'address': '192.168.1.11'}])
            return iter([])

        mock_api.path.side_effect = mock_path

        # Network with 4 usable IPs (.1, .2, .3, .4) - wait, /29 gives .1 to .6
        # Let's use 192.168.1.8/29, which means .9, .10, .11, .12, .13, .14
        result = find_free_ips('192.168.1.8/29')
        # .10 and .11 are used
        assert '192.168.1.9' in result['free_ips']
        assert '192.168.1.10' not in result['free_ips']
        assert '192.168.1.11' not in result['free_ips']
        assert '192.168.1.12' in result['free_ips']

    def test_find_free_ips_uses_router_and_dns_and_handles_errors(self, mock_get_api):
        from mikrotik.tools import find_free_ips

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api

        def mock_path(*args):
            if args == ("ip", "arp"):
                raise RuntimeError("arp-error")
            if args == ("ip", "dhcp-server", "lease"):
                return iter([{"address": "192.168.1.10"}, {"address": "bad-ip"}])
            if args == ("ip", "address"):
                return iter([{"address": "192.168.1.1/24"}, {"address": "bad-ip"}])
            if args == ("ip", "dns", "static"):
                return iter([{"address": "192.168.1.12"}, {"address": "bad-ip"}])
            return iter([])

        mock_api.path.side_effect = mock_path

        result = find_free_ips("192.168.1.0/28")
        assert result["used_count"] == 3
        assert "192.168.1.1" not in result["free_ips"]
        assert "192.168.1.10" not in result["free_ips"]
