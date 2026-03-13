import pytest
import time
from unittest.mock import patch, MagicMock

@patch('mikrotik.system.pool.get_api')
class TestGetStatus:
    def test_get_status_success(self, mock_get_api):
        from mikrotik.system import get_status

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        
        def mock_path(*args):
            if args == ('system', 'resource'):
                return iter([{'cpu-load': 10, 'free-memory': 512, 'total-memory': 1024, 'uptime': '1d', 'version': '7.0', 'board-name': 'hEX'}])
            if args == ('system', 'identity'):
                return iter([{'name': 'TestRouter'}])
            if args == ('system', 'health'):
                return iter([{'name': 'voltage', 'value': 24.5}])
            if args == ('system', 'routerboard'):
                return iter([{'model': 'RB750Gr3', 'serial-number': '12345'}])
            return iter([])

        mock_api.path.side_effect = mock_path

        result = get_status()
        
        assert result['identity'] == 'TestRouter'
        assert result['cpu'] == 10
        assert result['ram_total'] == 1024
        assert result['ram_free'] == 512
        assert result['voltage'] == 24.5
        assert result['model'] == 'RB750Gr3'

    def test_get_status_no_resource(self, mock_get_api):
        from mikrotik.system import get_status

        mock_api = MagicMock()
        mock_get_api.return_value = mock_api
        mock_api.path.return_value = iter([]) # Returns empty list
        
        # Advance time to force cache expiration
        with patch('time.time', return_value=time.time() + 10):
            result = get_status()
            
        assert result is None
