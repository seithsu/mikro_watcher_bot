# ============================================
# TEST_SCAN - Tests for mikrotik/scan.py
# IP scan, ARP/DHCP fallback, sorting
# ============================================

import pytest
from unittest.mock import patch, MagicMock


class TestIpSorting:
    """Test IP sorting in run_ip_scan."""

    def test_sort_by_ip_numerically(self):
        """Verify results get sorted by IP numerically."""
        data = [
            {'ip': '192.168.1.10', 'mac': '-', 'hostname': '-', 'interface': 'br', 'dns': '-'},
            {'ip': '192.168.1.2', 'mac': '-', 'hostname': '-', 'interface': 'br', 'dns': '-'},
            {'ip': '192.168.1.1', 'mac': '-', 'hostname': '-', 'interface': 'br', 'dns': '-'},
            {'ip': '192.168.1.20', 'mac': '-', 'hostname': '-', 'interface': 'br', 'dns': '-'},
        ]
        # Sort same way as run_ip_scan does
        data.sort(key=lambda x: tuple(int(p) for p in x['ip'].split('.')))
        ips = [d['ip'] for d in data]
        assert ips == ['192.168.1.1', '192.168.1.2', '192.168.1.10', '192.168.1.20']

    def test_sort_empty(self):
        data = []
        data.sort(key=lambda x: tuple(int(p) for p in x['ip'].split('.')))
        assert data == []


class TestArpDhcpScan:
    """Test _arp_dhcp_scan fallback scan."""

    @patch('mikrotik.scan.pool')
    def test_fallback_returns_list(self, mock_pool):
        from mikrotik.scan import _arp_dhcp_scan

        mock_api = MagicMock()
        mock_pool.get_api.return_value = mock_api

        # Mock DHCP leases
        mock_api.path.side_effect = [
            [  # dhcp-server/lease
                {'address': '192.168.1.10', 'mac-address': 'AA:BB:CC:DD:EE:01',
                 'host-name': 'PC1', 'status': 'bound'},
            ],
            [  # ip/arp
                {'address': '192.168.1.10', 'mac-address': 'AA:BB:CC:DD:EE:01',
                 'interface': 'bridge'},
                {'address': '192.168.1.20', 'mac-address': 'AA:BB:CC:DD:EE:02',
                 'interface': 'bridge'},
            ]
        ]

        result = _arp_dhcp_scan('bridge')
        assert isinstance(result, list)
        assert len(result) >= 1

    @patch('mikrotik.scan.pool')
    def test_fallback_error_returns_empty_list(self, mock_pool):
        from mikrotik.scan import _arp_dhcp_scan
        mock_pool.get_api.side_effect = Exception("no connection")

        result = _arp_dhcp_scan('bridge')
        assert isinstance(result, list)

    @patch('mikrotik.scan.pool')
    def test_fallback_merges_dhcp_bound_not_in_arp_and_resets_on_arp_error(self, mock_pool):
        from mikrotik.scan import _arp_dhcp_scan

        mock_api = MagicMock()
        mock_pool.get_api.return_value = mock_api

        def path_side_effect(*args):
            if args == ('ip', 'dhcp-server', 'lease'):
                return [
                    {
                        'address': '192.168.1.30',
                        'mac-address': 'AA:BB:CC:DD:EE:30',
                        'host-name': '',
                        'comment': 'Printer',
                        'status': 'bound',
                    }
                ]
            if args == ('ip', 'arp'):
                raise RuntimeError("arp-fail")
            return []

        mock_api.path.side_effect = path_side_effect

        result = _arp_dhcp_scan('bridge')
        assert result == [{
            'ip': '192.168.1.30',
            'mac': 'AA:BB:CC:DD:EE:30',
            'hostname': 'Printer',
            'interface': 'bridge',
            'dns': '-',
        }]
        mock_pool.reset.assert_called()


class TestLibrouterosIpScan:
    @patch('mikrotik.scan.librouteros.connect', side_effect=RuntimeError("connect-fail"))
    def test_connect_error_returns_none(self, _mock_connect):
        from mikrotik.scan import _librouteros_ip_scan

        assert _librouteros_ip_scan('bridge', duration=3) is None

    @patch('mikrotik.scan.librouteros.connect')
    def test_collects_results_and_enriches_defaults(self, mock_connect):
        from mikrotik.scan import _librouteros_ip_scan

        mock_api = MagicMock()
        mock_connect.return_value = mock_api
        tool = MagicMock()
        tool.return_value = iter([
            {'address': '192.168.1.10', 'mac-address': 'AA', 'dns': 'pc1.local'},
            {'address': '192.168.1.11', 'mac-address': '', 'host-name': 'PC2'},
            {'address': ''},
        ])
        mock_api.path.return_value = tool

        result = _librouteros_ip_scan('bridge', duration=3)
        assert result == [
            {'ip': '192.168.1.10', 'mac': 'AA', 'hostname': 'pc1.local', 'interface': 'bridge', 'dns': 'pc1.local'},
            {'ip': '192.168.1.11', 'mac': '-', 'hostname': 'PC2', 'interface': 'bridge', 'dns': '-'},
        ]
        mock_api.close.assert_called_once()

    @patch('mikrotik.scan.librouteros.connect')
    def test_partial_results_survive_scan_error(self, mock_connect):
        from mikrotik.scan import _librouteros_ip_scan

        class BrokenTool:
            def __call__(self, *_args, **_kwargs):
                yield {'address': '192.168.1.10', 'mac-address': 'AA', 'dns': ''}
                raise RuntimeError("scan-stop")

        mock_api = MagicMock()
        mock_api.path.return_value = BrokenTool()
        mock_connect.return_value = mock_api

        result = _librouteros_ip_scan('bridge', duration=3)
        assert result == [
            {'ip': '192.168.1.10', 'mac': 'AA', 'hostname': '-', 'interface': 'bridge', 'dns': '-'},
        ]

    @patch('mikrotik.scan.ssl.create_default_context')
    @patch('mikrotik.scan.librouteros.connect')
    def test_ssl_path_uses_wrapper(self, mock_connect, mock_ctx_factory, monkeypatch):
        import mikrotik.scan as scan

        ctx = MagicMock()
        mock_ctx_factory.return_value = ctx
        monkeypatch.setattr(scan.cfg, "MIKROTIK_USE_SSL", True, raising=False)
        monkeypatch.setattr(scan.cfg, "MIKROTIK_TLS_VERIFY", False, raising=False)

        mock_api = MagicMock()
        mock_api.path.return_value = MagicMock(return_value=iter([]))
        mock_connect.return_value = mock_api

        scan._librouteros_ip_scan('bridge', duration=3)
        assert mock_connect.call_args.kwargs["ssl_wrapper"] == ctx.wrap_socket


class TestRunIpScan:
    """Test run_ip_scan main function."""

    @patch('mikrotik.scan._arp_dhcp_scan')
    @patch('mikrotik.scan._librouteros_ip_scan')
    @patch('mikrotik.scan.pool')
    def test_scan_uses_librouteros_first(self, mock_pool, mock_ipscan, mock_fallback):
        from mikrotik.scan import run_ip_scan

        mock_api = MagicMock()
        mock_pool.get_api.return_value = mock_api
        mock_api.path.return_value = []

        mock_ipscan.return_value = [
            {'ip': '192.168.1.1', 'mac': 'AA:BB:CC:DD:EE:00',
             'hostname': 'router', 'interface': 'bridge', 'dns': '-'},
        ]

        result = run_ip_scan('bridge', duration=5)
        assert isinstance(result, list)
        assert len(result) == 1
        mock_ipscan.assert_called_once()
        mock_fallback.assert_not_called()

    @patch('mikrotik.scan._arp_dhcp_scan')
    @patch('mikrotik.scan._librouteros_ip_scan')
    @patch('mikrotik.scan.pool')
    def test_scan_falls_back_on_error(self, mock_pool, mock_ipscan, mock_fallback):
        from mikrotik.scan import run_ip_scan

        mock_api = MagicMock()
        mock_pool.get_api.return_value = mock_api
        mock_api.path.return_value = []

        mock_ipscan.return_value = None  # ip-scan failed
        mock_fallback.return_value = [
            {'ip': '192.168.1.10', 'mac': '-', 'hostname': '-',
             'interface': 'bridge', 'dns': '-'},
        ]

        result = run_ip_scan('bridge')
        assert isinstance(result, list)
        mock_fallback.assert_called_once()

    @patch('mikrotik.scan._librouteros_ip_scan')
    @patch('mikrotik.scan.pool')
    def test_scan_empty_results(self, mock_pool, mock_ipscan):
        from mikrotik.scan import run_ip_scan

        mock_api = MagicMock()
        mock_pool.get_api.return_value = mock_api
        mock_api.path.return_value = []
        mock_ipscan.return_value = []

        result = run_ip_scan('ether1')
        assert isinstance(result, list)
        assert len(result) == 0

    @patch('mikrotik.scan._arp_dhcp_scan')
    @patch('mikrotik.scan._librouteros_ip_scan')
    @patch('mikrotik.scan.pool')
    def test_scan_enriches_from_dhcp_and_suppresses_sort_error(self, mock_pool, mock_ipscan, _mock_fallback):
        from mikrotik.scan import run_ip_scan

        mock_api = MagicMock()
        mock_pool.get_api.return_value = mock_api
        mock_api.path.return_value = [
            {'address': '192.168.1.20', 'mac-address': 'AA:BB', 'host-name': 'HostA'},
        ]
        mock_ipscan.return_value = [
            {'ip': 'bad-ip', 'mac': 'AA:BB', 'hostname': '-', 'interface': 'bridge', 'dns': '-'},
        ]

        result = run_ip_scan('bridge')
        assert result[0]['hostname'] == 'HostA'
