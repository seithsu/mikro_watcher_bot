import pytest
import time
from unittest.mock import patch, MagicMock

from mikrotik.decorators import with_retry

class TestWithRetry:
    def test_success_first_try(self):
        mock_func = MagicMock(return_value="success")
        mock_func.__name__ = "mock_func"
        decorated = with_retry(mock_func)
        
        # Patch time.sleep and mikrotik.connection.pool.reset
        with patch('time.sleep') as mock_sleep, patch('mikrotik.connection.pool.reset') as mock_reset:
            result = decorated("arg1", kwarg="test")
            
        assert result == "success"
        mock_func.assert_called_once_with("arg1", kwarg="test")
        mock_sleep.assert_not_called()
        mock_reset.assert_not_called()

    def test_success_second_try(self):
        mock_func = MagicMock(side_effect=[Exception("fail"), "success"])
        mock_func.__name__ = "mock_func"
        decorated = with_retry(mock_func)
        
        with patch('time.sleep') as mock_sleep, patch('mikrotik.connection.pool.reset') as mock_reset:
            result = decorated()
            
        assert result == "success"
        assert mock_func.call_count == 2
        assert mock_reset.call_count == 1
        assert mock_sleep.call_count == 1

    def test_fails_all_retries(self):
        mock_func = MagicMock(side_effect=[Exception("fail1"), Exception("fail2"), Exception("fail3")])
        mock_func.__name__ = "mock_func"
        decorated = with_retry(mock_func)
        
        with patch('time.sleep') as mock_sleep, patch('mikrotik.connection.pool.reset') as mock_reset:
            with pytest.raises(Exception, match="fail3"):
                decorated()
            
        assert mock_func.call_count == 3
        assert mock_reset.call_count == 3
        assert mock_sleep.call_count == 2

    def test_connection_issue_throttles_reset_all(self):
        mock_func = MagicMock(side_effect=[
            Exception("not logged in"), "ok-1",
            Exception("not logged in"), "ok-2",
        ])
        mock_func.__name__ = "mock_func"
        decorated = with_retry(mock_func)

        with (
            patch('time.sleep') as _mock_sleep,
            patch('time.time', side_effect=[100.0, 105.0]),
            patch('mikrotik.decorators.cfg.MIKROTIK_RESET_ALL_COOLDOWN_SEC', 15),
            patch('mikrotik.connection.pool.reset') as mock_reset,
            patch('mikrotik.connection.pool.reset_all') as mock_reset_all,
        ):
            assert decorated() == "ok-1"
            assert decorated() == "ok-2"

        # Attempt pertama: reset_all dipanggil.
        # Attempt kedua masih dalam cooldown (5s < 15s): fallback ke reset local.
        assert mock_reset_all.call_count == 1
        assert mock_reset.call_count >= 1

    def test_connection_issue_retry_warning_is_throttled(self):
        from mikrotik import decorators as dec

        dec._retry_warning_state.clear()
        mock_func = MagicMock(side_effect=[Exception("timed out"), "ok-1", Exception("timed out"), "ok-2"])
        mock_func.__name__ = "mock_timeout_func"
        decorated = with_retry(mock_func)

        with (
            patch('time.sleep'),
            patch('time.time', side_effect=[100.0, 100.0, 105.0, 105.0]),
            patch('mikrotik.connection.pool.reset'),
            patch('mikrotik.connection.pool.reset_all'),
            patch.object(dec, 'logger') as mock_logger,
        ):
            assert decorated() == "ok-1"
            assert decorated() == "ok-2"

        mock_logger.warning.assert_called_once()

    def test_timeout_issue_does_not_trigger_reset_all(self):
        mock_func = MagicMock(side_effect=[Exception("timed out"), "ok"])
        mock_func.__name__ = "mock_timeout_reset_scope"
        decorated = with_retry(mock_func)

        with (
            patch('time.sleep'),
            patch('mikrotik.connection.pool.reset') as mock_reset,
            patch('mikrotik.connection.pool.reset_all') as mock_reset_all,
        ):
            assert decorated() == "ok"

        mock_reset.assert_called_once()
        mock_reset_all.assert_not_called()

    def test_ping_host_session_issue_does_not_trigger_reset_all(self):
        mock_func = MagicMock(side_effect=[Exception("not logged in"), "ok"])
        mock_func.__name__ = "ping_host"
        decorated = with_retry(mock_func)

        with (
            patch('time.sleep'),
            patch('mikrotik.connection.pool.reset') as mock_reset,
            patch('mikrotik.connection.pool.reset_all') as mock_reset_all,
        ):
            assert decorated("1.1.1.1", 3) == "ok"

        mock_reset.assert_called_once()
        mock_reset_all.assert_not_called()
