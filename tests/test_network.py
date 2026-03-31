import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
import time

@patch('mikrotik.network.pool.get_api')
class TestNetwork:
    def test_get_interfaces(self, mock_get_api):
        from mikrotik.network import get_interfaces

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        mock_api.path.return_value = iter([{
            'name': 'ether1', 'type': 'ether', 'running': 'true', 
            'disabled': 'false', 'rx-byte': 1000, 'tx-byte': 500, 'mac-address': '00:11:22'
        }])

        result = get_interfaces.__wrapped__()
        assert len(result) == 1
        assert result[0]['name'] == 'ether1'
        assert result[0]['running'] is True
        assert result[0]['enabled'] is True
        assert result[0]['rx'] == 1000

    def test_get_ip_addresses(self, mock_get_api):
        from mikrotik.network import get_ip_addresses

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        mock_api.path.return_value = iter([{'address': '192.168.1.1/24', 'interface': 'bridge'}])

        result = get_ip_addresses()
        assert len(result) == 1
        assert result[0]['address'] == '192.168.1.1/24'

    def test_get_dhcp_pool_capacity_from_enabled_servers(self, mock_get_api):
        from mikrotik.network import get_dhcp_pool_capacity

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api

        def mock_path(*args):
            if args == ("ip", "dhcp-server"):
                return iter([
                    {"name": "DHCP1", "address-pool": "pool-a", "disabled": "false"},
                    {"name": "DHCP2", "address-pool": "pool-b", "disabled": "true"},
                ])
            if args == ("ip", "pool"):
                return iter([
                    {"name": "pool-a", "ranges": "192.168.3.190-192.168.3.249"},
                    {"name": "pool-b", "ranges": "192.168.4.10-192.168.4.19"},
                ])
            return iter([])

        mock_api.path.side_effect = mock_path

        assert get_dhcp_pool_capacity.__wrapped__.__wrapped__() == 60

    def test_get_dhcp_pool_capacity_counts_next_pool_once(self, mock_get_api):
        from mikrotik.network import get_dhcp_pool_capacity

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api

        def mock_path(*args):
            if args == ("ip", "dhcp-server"):
                return iter([
                    {"name": "DHCP1", "address-pool": "pool-a", "disabled": "false"},
                    {"name": "DHCP2", "address-pool": "pool-b", "disabled": "false"},
                ])
            if args == ("ip", "pool"):
                return iter([
                    {"name": "pool-a", "ranges": "192.168.3.190-192.168.3.199", "next-pool": "pool-b"},
                    {"name": "pool-b", "ranges": "192.168.3.200-192.168.3.209"},
                ])
            return iter([])

        mock_api.path.side_effect = mock_path

        assert get_dhcp_pool_capacity.__wrapped__.__wrapped__() == 20

    def test_get_traffic(self, mock_get_api):
        from mikrotik.network import get_traffic

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        
        # For the ifaces iteration used later in get_traffic
        def mock_path(*args):
            class MockPathCallable:
                def __call__(self, *a, **kw):
                    return iter([{'rx-bits-per-second': 8000, 'tx-bits-per-second': 16000}])
                def __iter__(self):
                    return iter([{'name': 'ether1', 'rx-byte': 1024, 'tx-byte': 2048}])
            
            p = MagicMock()
            if args == ('interface',):
                return MockPathCallable()
            return p
        
        mock_api.path.side_effect = mock_path

        result = get_traffic('ether1')
        assert result['name'] == 'ether1'
        assert result['rx_bps'] == 8000
        assert result['tx_bps'] == 16000
        assert result['rx_bytes'] == 1024
        assert result['tx_bytes'] == 2048

    def test_get_mikrotik_log_uses_select_minimal_payload(self, mock_get_api, monkeypatch):
        import mikrotik.network as network

        log_path = MagicMock()
        log_path.select.return_value = iter([
            {'time': '10:00:00', 'topics': ['system', 'info'], 'message': 'ok'},
        ])
        mock_api = MagicMock()
        mock_api.path.return_value = log_path
        mock_get_api.return_value = mock_api

        monkeypatch.setattr(network, "_LOG_CACHE", [], raising=False)
        monkeypatch.setattr(network, "_LOG_CACHE_TS", 0.0, raising=False)
        monkeypatch.setattr(network, "_LOG_FETCH_LAST_ERROR_TS", 0.0, raising=False)

        result = network.get_mikrotik_log.__wrapped__(1)

        assert result == [{'time': '10:00:00', 'topics': 'system,info', 'message': 'ok'}]
        log_path.select.assert_called_once_with('time', 'topics', 'message')

    def test_get_mikrotik_log_uses_stale_cache_after_fetch_failure(self, mock_get_api, monkeypatch):
        import mikrotik.network as network

        cache = [{'time': '09:59:59', 'topics': 'system,error', 'message': 'cached'}]
        log_path = MagicMock()
        log_path.select.side_effect = RuntimeError("timeout")
        mock_api = MagicMock()
        mock_api.path.return_value = log_path
        mock_get_api.return_value = mock_api

        monkeypatch.setattr(network, "_LOG_CACHE", cache, raising=False)
        monkeypatch.setattr(network, "_LOG_CACHE_TS", time.time() - 30, raising=False)
        monkeypatch.setattr(network, "_LOG_FETCH_LAST_ERROR_TS", 0.0, raising=False)
        monkeypatch.setattr(network.pool, "reset", MagicMock())

        result = network.get_mikrotik_log.__wrapped__(1)

        assert result == cache
        assert mock_get_api.call_count == 2
        network.pool.reset.assert_called_once()

    def test_get_mikrotik_log_respects_recent_error_backoff(self, mock_get_api, monkeypatch):
        import mikrotik.network as network

        cache = [{'time': '09:59:59', 'topics': 'system,error', 'message': 'cached'}]
        monkeypatch.setattr(network, "_LOG_CACHE", cache, raising=False)
        monkeypatch.setattr(network, "_LOG_CACHE_TS", time.time(), raising=False)
        monkeypatch.setattr(network, "_LOG_FETCH_LAST_ERROR_TS", time.time(), raising=False)

        result = network.get_mikrotik_log.__wrapped__(1)

        assert result == cache
        mock_get_api.assert_not_called()

    def test_monitored_queues_skip_disabled_and_invalid_target(self, mock_get_api):
        from mikrotik.network import _get_all_monitored_queues

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api

        def mock_path(*args):
            if args == ('queue', 'simple'):
                return iter([
                    {'name': 'Khanza', 'comment': 'server', 'target': '192.168.3.250/32', 'disabled': 'false'},
                    {'name': 'OldServer', 'comment': 'server', 'target': '192.168.3.251/32', 'disabled': 'true'},
                    {'name': 'AP-1', 'comment': 'ap', 'target': '192.168.3.20/32', 'disabled': 'false'},
                    {'name': 'InvalidTarget', 'comment': 'server', 'target': 'bridge-local', 'disabled': 'false'},
                ])
            return iter([])

        mock_api.path.side_effect = mock_path

        # Bypass cached/retry wrapper agar test benar-benar deterministic.
        aps, servers = _get_all_monitored_queues.__wrapped__.__wrapped__()
        assert servers == {'Khanza': '192.168.3.250'}
        assert aps == {'AP-1': '192.168.3.20'}

    @patch('mikrotik.network._get_all_monitored_queues', return_value=(
        {'AP-Q': '192.168.3.20'},
        {'SRV-Q': '192.168.3.10'},
    ))
    def test_monitored_hosts_merge_fallback_and_queue(self, mock_q, mock_get_api, monkeypatch):
        from mikrotik.network import get_monitored_aps, get_monitored_servers
        import core.config as cfg

        monkeypatch.setattr(cfg, "APS_FALLBACK", {'AP-STATIC': '192.168.3.21'}, raising=False)
        monkeypatch.setattr(cfg, "SERVERS_FALLBACK", {'SRV-STATIC': '192.168.3.11'}, raising=False)

        aps = get_monitored_aps.__wrapped__()
        servers = get_monitored_servers.__wrapped__()

        assert aps == {'AP-STATIC': '192.168.3.21', 'AP-Q': '192.168.3.20'}
        assert servers == {'SRV-STATIC': '192.168.3.11', 'SRV-Q': '192.168.3.10'}

    @patch('mikrotik.network._get_all_queue_targets', return_value={})
    @patch('mikrotik.network.get_dhcp_leases', return_value=[
        {'host-name': 'komp pendaftaran igd', 'address': '192.168.3.40'},
        {'host-name': 'komp pendaftaran poli', 'address': '192.168.3.41'},
    ])
    def test_monitored_critical_devices_from_dhcp_and_fallback(
        self, mock_leases, mock_queue, mock_get_api, monkeypatch
    ):
        from mikrotik.network import get_monitored_critical_devices
        import core.config as cfg

        monkeypatch.setattr(cfg, "CRITICAL_DEVICES_FALLBACK", {'SIMRS': '192.168.3.10'}, raising=False)
        monkeypatch.setattr(
            cfg,
            "CRITICAL_DEVICE_NAMES",
            ["KOMP PENDAFTARAN IGD", "KOMP PENDAFTARAN POLI"],
            raising=False,
        )
        monkeypatch.setattr(cfg, "CRITICAL_DEVICE_WINDOWS", {}, raising=False)

        devices = get_monitored_critical_devices.__wrapped__.__wrapped__()
        assert devices == {
            'SIMRS': '192.168.3.10',
            'KOMP PENDAFTARAN IGD': '192.168.3.40',
            'KOMP PENDAFTARAN POLI': '192.168.3.41',
        }

    @patch('mikrotik.network.get_dhcp_leases', return_value=[])
    @patch('mikrotik.network._get_all_queue_targets', return_value={
        'Q-IGD / KOMP PENDAFTARAN IGD': '192.168.3.40',
        'KOMP PENDAFTARAN POLI': '192.168.3.41',
    })
    def test_monitored_critical_devices_from_queue_names(
        self, mock_queue, mock_leases, mock_get_api, monkeypatch
    ):
        from mikrotik.network import get_monitored_critical_devices
        import core.config as cfg

        monkeypatch.setattr(cfg, "CRITICAL_DEVICES_FALLBACK", {}, raising=False)
        monkeypatch.setattr(
            cfg,
            "CRITICAL_DEVICE_NAMES",
            ["KOMP PENDAFTARAN IGD", "KOMP PENDAFTARAN POLI"],
            raising=False,
        )
        monkeypatch.setattr(cfg, "CRITICAL_DEVICE_WINDOWS", {}, raising=False)

        devices = get_monitored_critical_devices.__wrapped__.__wrapped__()
        assert devices == {
            'KOMP PENDAFTARAN IGD': '192.168.3.40',
            'KOMP PENDAFTARAN POLI': '192.168.3.41',
        }

    def test_critical_window_helper_and_active_names(self, mock_get_api, monkeypatch):
        from mikrotik.network import _is_device_within_monitor_window, get_active_critical_device_names
        import core.config as cfg

        monkeypatch.setattr(
            cfg,
            "CRITICAL_DEVICE_WINDOWS",
            {"KOMP PENDAFTARAN POLI": (7 * 60, 17 * 60)},
            raising=False,
        )
        monkeypatch.setattr(
            cfg,
            "CRITICAL_DEVICE_NAMES",
            ["KOMP PENDAFTARAN IGD", "KOMP PENDAFTARAN POLI"],
            raising=False,
        )

        assert _is_device_within_monitor_window(
            "KOMP PENDAFTARAN POLI", datetime(2026, 3, 12, 8, 30)
        ) is True
        assert _is_device_within_monitor_window(
            "KOMP PENDAFTARAN POLI", datetime(2026, 3, 12, 18, 30)
        ) is False
        assert _is_device_within_monitor_window(
            "KOMP PENDAFTARAN IGD", datetime(2026, 3, 12, 18, 30)
        ) is True

        with patch("mikrotik.network.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 12, 19, 0)
            active_names = get_active_critical_device_names()
        assert active_names == ["KOMP PENDAFTARAN IGD"]

    @patch("mikrotik.network._is_device_within_monitor_window")
    @patch('mikrotik.network._get_all_queue_targets', return_value={})
    @patch('mikrotik.network.get_dhcp_leases', return_value=[
        {'host-name': 'komp pendaftaran igd', 'address': '192.168.3.40'},
        {'host-name': 'komp pendaftaran poli', 'address': '192.168.3.41'},
    ])
    def test_monitored_critical_devices_respects_window_filter(
        self, mock_leases, mock_queue, mock_window, mock_get_api, monkeypatch
    ):
        from mikrotik.network import get_monitored_critical_devices
        import core.config as cfg

        monkeypatch.setattr(cfg, "CRITICAL_DEVICES_FALLBACK", {}, raising=False)
        monkeypatch.setattr(
            cfg,
            "CRITICAL_DEVICE_NAMES",
            ["KOMP PENDAFTARAN IGD", "KOMP PENDAFTARAN POLI"],
            raising=False,
        )

        mock_window.side_effect = lambda name, now_dt=None: name != "KOMP PENDAFTARAN POLI"
        devices = get_monitored_critical_devices.__wrapped__.__wrapped__()
        assert devices == {'KOMP PENDAFTARAN IGD': '192.168.3.40'}
