# ============================================
# TEST_CONNECTION - Tests for mikrotik/connection.py
# Thread-local pool, auto-reconnect, health check
# ============================================

import pytest
import time
from unittest.mock import patch, MagicMock
from types import SimpleNamespace


def _fresh_conn():
    from mikrotik.connection import MikroTikConnection

    MikroTikConnection._instance = None
    MikroTikConnection._active_connections = 0
    MikroTikConnection._reset_version = 0
    MikroTikConnection._connect_fail_count = 0
    MikroTikConnection._next_connect_allowed_ts = 0.0
    MikroTikConnection._last_connect_error = ""
    MikroTikConnection._last_limit_warning_ts = 0.0
    conn = MikroTikConnection()
    conn._local = SimpleNamespace()
    return conn


class TestMikroTikConnectionSingleton:
    """Test singleton pattern."""

    @patch('mikrotik.connection.librouteros')
    def test_singleton_same_instance(self, mock_lib):
        from mikrotik.connection import MikroTikConnection
        # Reset singleton for test
        MikroTikConnection._instance = None
        a = MikroTikConnection()
        b = MikroTikConnection()
        assert a is b

    @patch('mikrotik.connection.librouteros')
    def test_pool_is_connection(self, mock_lib):
        """Pool should be a MikroTikConnection instance."""
        from mikrotik.connection import pool, MikroTikConnection
        assert isinstance(pool, MikroTikConnection)


class TestConnectionGetApi:
    """Test get_api() behavior with thread-local connections."""

    @patch('mikrotik.connection.librouteros')
    def test_creates_new_connection(self, mock_lib):
        conn = _fresh_conn()
        conn._local._api = None  # Force new connection

        mock_api = MagicMock()
        mock_lib.connect.return_value = mock_api

        result = conn.get_api()
        assert result is mock_api

    @patch('mikrotik.connection.librouteros')
    def test_reuses_healthy_connection(self, mock_lib):
        conn = _fresh_conn()

        mock_api = MagicMock()
        # Make health check pass (identity lookup)
        mock_api.path.return_value = iter([{'name': 'Router'}])
        conn._local._api = mock_api
        conn._local._connected_at = time.time()  # Mark as recently connected
        conn._local._reset_version_seen = conn._reset_version

        result = conn.get_api()
        assert result is mock_api
        mock_lib.connect.assert_not_called()  # No new connection needed

    @patch('mikrotik.connection.librouteros')
    def test_reconnects_on_dead_connection(self, mock_lib):
        conn = _fresh_conn()

        dead_api = MagicMock()
        dead_api.path.side_effect = Exception("connection lost")
        conn._local._api = dead_api
        conn._local._connected_at = time.time()

        new_api = MagicMock()
        mock_lib.connect.return_value = new_api

        result = conn.get_api()
        assert result is new_api

    @patch('mikrotik.connection.librouteros')
    def test_reconnects_on_old_connection(self, mock_lib):
        """Connection that exceeds max age should be replaced."""
        conn = _fresh_conn()

        old_api = MagicMock()
        conn._local._api = old_api
        conn._local._connected_at = time.time() - 20

        new_api = MagicMock()
        mock_lib.connect.return_value = new_api

        with patch('mikrotik.connection.cfg.MIKROTIK_CONNECTION_MAX_AGE_SEC', 5):
            result = conn.get_api()
            assert result is new_api
            old_api.close.assert_called_once()

    @patch('mikrotik.connection.librouteros')
    def test_old_connection_reused_when_max_age_disabled(self, mock_lib):
        """Ketika max-age=0, koneksi lama tetap dipakai selama health check lulus."""
        conn = _fresh_conn()

        old_api = MagicMock()
        old_api.path.return_value = iter([{'name': 'Router'}])
        conn._local._api = old_api
        conn._local._connected_at = time.time() - 3600
        conn._local._reset_version_seen = conn._reset_version

        with patch('mikrotik.connection.cfg.MIKROTIK_CONNECTION_MAX_AGE_SEC', 0):
            result = conn.get_api()
            assert result is old_api
            mock_lib.connect.assert_not_called()

    @patch('mikrotik.connection.librouteros')
    def test_get_api_handles_reload_env_failure(self, mock_lib):
        conn = _fresh_conn()

        mock_api = MagicMock()
        mock_lib.connect.return_value = mock_api
        mock_lib.exceptions.TrapError = type("TrapError", (Exception,), {})
        with patch('mikrotik.connection.cfg.reload_router_env', side_effect=[RuntimeError("reload-fail"), None]):
            assert conn.get_api() is mock_api

    @patch('mikrotik.connection.librouteros')
    def test_get_api_reconnects_when_reset_version_changes(self, mock_lib):
        conn = _fresh_conn()
        old_api = MagicMock()
        old_api.path.return_value = iter([{'name': 'Router'}])
        conn._local._api = old_api
        conn._local._connected_at = time.time()
        conn._local._reset_version_seen = 0
        conn._reset_version = 1

        new_api = MagicMock()
        mock_lib.connect.return_value = new_api

        assert conn.get_api() is new_api
        old_api.close.assert_called_once()

    @patch('mikrotik.connection.librouteros')
    def test_get_api_backoff_guard_raises(self, mock_lib):
        conn = _fresh_conn()
        conn._next_connect_allowed_ts = time.time() + 5
        conn._last_connect_error = "boom"

        with pytest.raises(RuntimeError, match="Reconnect backoff aktif"):
            conn.get_api()
        mock_lib.connect.assert_not_called()

    @patch('mikrotik.connection.time.sleep')
    @patch('mikrotik.connection.librouteros')
    def test_get_api_max_connections_guard_raises(self, mock_lib, _mock_sleep):
        conn = _fresh_conn()
        conn._active_connections = 99

        with patch.object(conn, "_max_connections", return_value=1):
            with pytest.raises(RuntimeError, match="max connections reached"):
                conn.get_api()

    @patch('mikrotik.connection.librouteros')
    def test_get_api_trap_error_registers_failure(self, mock_lib):
        import mikrotik.connection as connection

        conn = _fresh_conn()
        trap_exc = RuntimeError("trap")
        with patch.object(connection.librouteros.exceptions, "TrapError", RuntimeError):
            with patch.object(conn, "_create_connection", side_effect=trap_exc):
                with pytest.raises(RuntimeError, match="trap"):
                    conn.get_api()

        assert conn._connect_fail_count == 1
        assert conn._last_connect_error == "trap"

    @patch('mikrotik.connection.librouteros')
    def test_get_api_generic_error_registers_failure(self, mock_lib):
        conn = _fresh_conn()
        mock_lib.exceptions.TrapError = type("TrapError", (Exception,), {})

        with patch.object(conn, "_create_connection", side_effect=RuntimeError("connect-fail")):
            with pytest.raises(RuntimeError, match="connect-fail"):
                conn.get_api()

        assert conn._connect_fail_count == 1
        assert conn._last_connect_error == "connect-fail"


class TestConnectionReset:
    """Test reset() and health_check()."""

    @patch('mikrotik.connection.librouteros')
    def test_reset_clears_api(self, mock_lib):
        conn = _fresh_conn()
        mock_api = MagicMock()
        conn._local._api = mock_api

        conn.reset()
        assert getattr(conn._local, '_api', None) is None

    @patch('mikrotik.connection.librouteros')
    def test_reset_no_api_safe(self, mock_lib):
        """Reset tanpa koneksi aktif tidak error."""
        conn = _fresh_conn()
        conn._local._api = None
        conn.reset()  # Should not raise

    @patch('mikrotik.connection.librouteros')
    def test_health_check_success(self, mock_lib):
        conn = _fresh_conn()
        mock_api = MagicMock()
        mock_api.path.return_value = iter([{'name': 'test'}])
        conn._local._api = mock_api
        conn._local._connected_at = time.time()

        assert conn.health_check() is True

    @patch('mikrotik.connection.librouteros')
    def test_health_check_failure(self, mock_lib):
        conn = _fresh_conn()
        conn._local._api = None
        mock_lib.connect.side_effect = Exception("refused")

        assert conn.health_check() is False

    @patch('mikrotik.connection.librouteros')
    def test_reset_all_does_not_clear_backoff_by_default(self, _mock_lib):
        conn = _fresh_conn()
        conn._connect_fail_count = 3
        conn._next_connect_allowed_ts = time.time() + 10
        conn._last_connect_error = "boom"

        conn.reset_all()

        assert conn._connect_fail_count == 3
        assert conn._next_connect_allowed_ts > time.time()
        assert conn._last_connect_error == "boom"

    @patch('mikrotik.connection.librouteros')
    def test_close_local_swallows_close_error_and_decrements_counter(self, _mock_lib):
        conn = _fresh_conn()
        api = MagicMock()
        api.close.side_effect = RuntimeError("close-fail")
        conn._local._api = api
        conn._local._connected_at = time.time()
        conn._active_connections = 1

        conn._close_local()

        assert getattr(conn._local, "_api", None) is None
        assert conn._active_connections == 0

    @patch('mikrotik.connection.librouteros')
    def test_reset_all_with_clear_backoff(self, _mock_lib):
        conn = _fresh_conn()
        type(conn)._connect_fail_count = 2
        type(conn)._next_connect_allowed_ts = time.time() + 10
        type(conn)._last_connect_error = "boom"

        conn.reset_all(clear_backoff=True)

        assert type(conn)._connect_fail_count == 0
        assert type(conn)._next_connect_allowed_ts == 0.0
        assert type(conn)._last_connect_error == ""


class TestConnectionHelpers:
    @patch('mikrotik.connection.plain')
    @patch('mikrotik.connection.token')
    def test_login_auto_uses_token_then_stops(self, mock_token, mock_plain):
        from mikrotik.connection import _login_auto

        api = MagicMock()
        api.return_value = iter([{'name': 'Router'}])
        _login_auto(api, "admin", "secret")

        mock_token.assert_called_once()
        mock_plain.assert_not_called()

    @patch('mikrotik.connection.plain', side_effect=RuntimeError("plain-fail"))
    @patch('mikrotik.connection.token', side_effect=RuntimeError("token-fail"))
    def test_login_auto_raises_last_exception(self, _mock_token, _mock_plain):
        from mikrotik.connection import _login_auto

        with pytest.raises(RuntimeError, match="plain-fail"):
            _login_auto(MagicMock(), "admin", "secret")

    def test_connection_max_age_and_max_connections_fallbacks(self):
        from mikrotik.connection import MikroTikConnection

        with patch('mikrotik.connection.cfg.MIKROTIK_CONNECTION_MAX_AGE_SEC', "bad"):
            assert MikroTikConnection._connection_max_age_sec() == 0
        with patch('mikrotik.connection.cfg.MIKROTIK_MAX_CONNECTIONS', "bad"):
            assert MikroTikConnection._max_connections() == MikroTikConnection._MAX_CONNECTIONS

    @patch('mikrotik.connection.threading.enumerate', return_value=[SimpleNamespace(ident=1)])
    def test_prune_stale_counter(self, _mock_enum):
        from mikrotik.connection import MikroTikConnection

        MikroTikConnection._active_connections = 5
        MikroTikConnection._prune_stale_counter()
        assert MikroTikConnection._active_connections == 1

    def test_register_and_clear_backoff(self):
        from mikrotik.connection import MikroTikConnection

        MikroTikConnection._connect_fail_count = 0
        MikroTikConnection._register_connect_failure(RuntimeError("boom"))
        assert MikroTikConnection._connect_fail_count == 1
        assert MikroTikConnection._last_connect_error == "boom"
        assert MikroTikConnection._next_connect_allowed_ts > time.time()
        MikroTikConnection._clear_connect_backoff()
        assert MikroTikConnection._connect_fail_count == 0

    def test_warn_limit_throttled(self):
        from mikrotik.connection import MikroTikConnection

        MikroTikConnection._last_limit_warning_ts = 0
        with patch('mikrotik.connection.logger.warning') as mock_warn:
            with patch('mikrotik.connection.time.time', side_effect=[100, 110, 140]):
                MikroTikConnection._warn_limit_throttled(3)
                MikroTikConnection._warn_limit_throttled(3)
                MikroTikConnection._warn_limit_throttled(3)
        assert mock_warn.call_count == 2

    @patch('mikrotik.connection.librouteros.connect')
    def test_create_connection_without_ssl(self, mock_connect):
        from mikrotik.connection import MikroTikConnection

        api = MagicMock()
        api.path.return_value = iter([{'name': 'Router'}])
        mock_connect.return_value = api
        with patch('mikrotik.connection.cfg.reload_router_env'):
            with patch('mikrotik.connection.cfg.MIKROTIK_USE_SSL', False):
                result = MikroTikConnection._create_connection()
        assert result is api

    @patch('mikrotik.connection.ssl.create_default_context')
    @patch('mikrotik.connection.librouteros.connect')
    def test_create_connection_with_verified_ssl(self, mock_connect, mock_ctx_factory):
        from mikrotik.connection import MikroTikConnection

        ctx = MagicMock()
        mock_ctx_factory.return_value = ctx
        api = MagicMock()
        api.path.return_value = iter([{'name': 'Router'}])
        mock_connect.return_value = api
        with patch('mikrotik.connection.cfg.reload_router_env'):
            with patch('mikrotik.connection.cfg.MIKROTIK_USE_SSL', True), \
                 patch('mikrotik.connection.cfg.MIKROTIK_TLS_VERIFY', True), \
                 patch('mikrotik.connection.cfg.MIKROTIK_TLS_CA_FILE', 'ca.pem'):
                MikroTikConnection._create_connection()
        assert mock_connect.call_args.kwargs['ssl_wrapper'] == ctx.wrap_socket

    @patch('mikrotik.connection.ssl.create_default_context')
    @patch('mikrotik.connection.librouteros.connect')
    def test_create_connection_with_insecure_ssl(self, mock_connect, mock_ctx_factory):
        from mikrotik.connection import MikroTikConnection

        ctx = MagicMock()
        mock_ctx_factory.return_value = ctx
        api = MagicMock()
        api.path.return_value = iter([{'name': 'Router'}])
        mock_connect.return_value = api
        with patch('mikrotik.connection.cfg.reload_router_env'):
            with patch('mikrotik.connection.cfg.MIKROTIK_USE_SSL', True), \
                 patch('mikrotik.connection.cfg.MIKROTIK_TLS_VERIFY', False):
                MikroTikConnection._create_connection()
        assert mock_connect.call_args.kwargs['ssl_wrapper'] == ctx.wrap_socket

    @pytest.mark.asyncio
    async def test_execute_async_and_connection_diagnostics(self):
        conn = _fresh_conn()
        api = MagicMock()
        api.path.return_value = MagicMock(return_value=iter([{"ok": True}]))

        with patch.object(conn, "get_api", return_value=api):
            result = await conn.execute_async(("system", "resource"), "print")
        assert result == [{"ok": True}]

        with patch.object(conn, "health_check", return_value=True):
            conn._connect_fail_count = 2
            conn._next_connect_allowed_ts = time.time() + 5
            conn._last_connect_error = "boom"
            diag = conn.connection_diagnostics()
        assert diag["healthy"] is True
        assert diag["fail_count"] == 2
        assert diag["last_error"] == "boom"
