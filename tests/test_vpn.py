import pytest
import time
from unittest.mock import patch, MagicMock

@patch('mikrotik.vpn.pool.get_api')
class TestVPN:
    def test_get_vpn_tunnels(self, mock_get_api):
        from mikrotik.vpn import get_vpn_tunnels

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        
        def mock_path(*args):
            p = MagicMock()
            if args == ('interface', 'l2tp-client'):
                return iter([{'name': 'l2tp-out1', 'connect-to': '192.168.100.1', 'running': 'true', 'disabled': 'false', 'uptime': '1h'}])
            if args == ('interface', 'pptp-client'):
                return iter([])
            if args == ('interface', 'sstp-client'):
                return iter([])
            if args == ('interface', 'ovpn-client'):
                return iter([])
            
            # servers
            if args == ('interface', 'l2tp-server', 'server'):
                return iter([{'name': 'l2tp-in1', 'client-address': '10.0.0.2', 'running': 'true', 'uptime': '2h'}])
            if args == ('interface', 'pptp-server', 'server'):
                return iter([])
            if args == ('interface', 'sstp-server', 'server'):
                return iter([])
            if args == ('interface', 'ovpn-server', 'server'):
                return iter([])
                
            return iter([])

        mock_api.path.side_effect = mock_path

        result = get_vpn_tunnels()
        
        assert len(result) == 2
        
        l2tp_client = next(t for t in result if t['type'] == 'L2TP')
        assert l2tp_client['name'] == 'l2tp-out1'
        assert l2tp_client['remote'] == '192.168.100.1'
        assert l2tp_client['running'] is True
        
        l2tp_server = next(t for t in result if t['type'] == 'L2TP-S')
        assert l2tp_server['name'] == 'l2tp-in1'
        assert l2tp_server['remote'] == '10.0.0.2'
        assert l2tp_server['running'] is True

    def test_get_vpn_tunnels_error_handling(self, mock_get_api):
        from mikrotik.vpn import get_vpn_tunnels
        
        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        
        # Simulate an exception during the API call
        mock_api.path.side_effect = Exception("API Error")
        
        # Advance time to force cache expiration (ttl=10)
        with patch('time.time', return_value=time.time() + 15):
            result = get_vpn_tunnels()
            
        assert result == []  # Should return empty list, not crash
