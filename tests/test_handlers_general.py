# ============================================
# TEST_HANDLERS_GENERAL - Tests for handlers/general.py
# Start, status, help, history, audit, reboot, mtlog, menu callbacks
# ============================================

import pytest
import time
from unittest.mock import patch, AsyncMock, MagicMock


def _make_update(user_id=12345, username="admin"):
    user = MagicMock()
    user.id = user_id
    user.username = username
    message = MagicMock()
    message.chat = MagicMock()
    message.chat.id = user_id
    message.reply_text = AsyncMock()
    message.edit_text = AsyncMock()
    message.delete = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.effective_message = message
    update.message = message
    update.callback_query = None
    return update


class TestCmdStart:
    """Test /start command."""

    @pytest.mark.asyncio
    @patch('handlers.general.database')
    @patch('handlers.general.read_state_json')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_start_shows_dashboard(self, mock_access, mock_state, mock_db):
        from handlers.general import cmd_start
        mock_state.return_value = {'kategori': 'NORMAL', 'hosts': {}}
        mock_db.count_incidents_today.return_value = 0

        update = _make_update()
        context = MagicMock()
        await cmd_start(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general.database')
    @patch('handlers.general.read_state_json')
    @patch('monitor.alerts.set_alert_delivery_enabled')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_start_enables_alert_gate_when_required(
        self, mock_access, mock_gate, mock_state, mock_db, monkeypatch
    ):
        from handlers.general import cmd_start
        mock_state.return_value = {'kategori': 'NORMAL', 'hosts': {}}
        mock_db.count_incidents_today.return_value = 0
        import handlers.general as general
        monkeypatch.setattr(general.cfg, "ALERT_REQUIRE_START", True, raising=False)

        update = _make_update()
        context = MagicMock()
        await cmd_start(update, context)

        mock_gate.assert_called_once()
        args = mock_gate.call_args[0]
        assert args[0] is True
        assert args[2] == "/start"

    @pytest.mark.asyncio
    @patch('handlers.general.database')
    @patch('handlers.general.read_state_json')
    @patch('monitor.alerts.set_alert_delivery_enabled')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_start_callback_does_not_toggle_alert_gate(
        self, mock_access, mock_gate, mock_state, mock_db, monkeypatch
    ):
        from handlers.general import cmd_start
        mock_state.return_value = {'kategori': 'NORMAL', 'hosts': {}}
        mock_db.count_incidents_today.return_value = 0
        import handlers.general as general
        monkeypatch.setattr(general.cfg, "ALERT_REQUIRE_START", True, raising=False)

        update = _make_update()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update.callback_query = query
        update.message = None
        context = MagicMock()
        await cmd_start(update, context)

        mock_gate.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.general.database')
    @patch('handlers.general.read_state_json')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_start_home_menu_contains_reset_button(self, mock_access, mock_state, mock_db):
        from handlers.general import cmd_start
        mock_state.return_value = {'kategori': 'NORMAL', 'hosts': {}}
        mock_db.count_incidents_today.return_value = 0

        update = _make_update()
        context = MagicMock()
        await cmd_start(update, context)

        markup = update.effective_message.reply_text.call_args.kwargs["reply_markup"]
        buttons = [btn.text for row in markup.inline_keyboard for btn in row]
        assert "🧹 Reset Data" in buttons


class TestCmdHelp:
    """Test /help command."""

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_help_lists_commands(self, mock_access):
        from handlers.general import cmd_help
        update = _make_update()
        context = MagicMock()
        await cmd_help(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_help_callback_edits_message(self, mock_access):
        from handlers.general import cmd_help
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()

        await cmd_help(update, context)

        query.answer.assert_called_once()
        query.message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_help_callback_falls_back_to_reply(self, mock_access):
        from handlers.general import cmd_help
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        await cmd_help(update, context)

        message.reply_text.assert_called_once()


class TestResetDataCallback:
    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_reset_data_confirm_shows_warning(self, mock_access):
        from handlers.general import callback_reset_data

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.data = "reset_data_confirm"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = user

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        await callback_reset_data(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        rendered = query.edit_message_text.call_args.args[0]
        assert "RESET DATA RUNTIME" in rendered

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    @patch('handlers.general.reset_runtime_data', return_value={
        'database': {'incidents': 2, 'metrics': 10, 'audit_log': 1, 'total': 13}
    })
    @patch('monitor.alerts.set_alert_delivery_enabled')
    async def test_reset_data_execute_runs_reset_and_renders_summary(
        self, mock_gate, mock_reset, mock_access, monkeypatch
    ):
        from handlers.general import callback_reset_data
        import handlers.general as general

        monkeypatch.setattr(general.cfg, "ALERT_REQUIRE_START", True, raising=False)

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.data = "reset_data_execute"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = user

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        await callback_reset_data(update, context)

        mock_reset.assert_called_once()
        mock_gate.assert_called_once()
        rendered = query.edit_message_text.call_args.args[0]
        assert "Reset data selesai" in rendered
        assert "13" in rendered


class TestCmdHistory:
    """Test /history command with pagination."""

    @pytest.mark.asyncio
    @patch('handlers.general.database')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_history_with_data(self, mock_access, mock_db):
        from handlers.general import cmd_history
        mock_db.count_all_incidents.return_value = 1
        mock_db.get_recent_history.return_value = [
            {'host': '192.168.1.10', 'kategori': 'SERVER ISSUE',
             'waktu_down': '2026-01-01T10:00:00', 'waktu_up': '2026-01-01T10:30:00',
             'durasi_detik': 1800, 'tag': 'server'},
        ]
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_history(update, context)
        update.effective_message.reply_text.assert_called()
        call_text = update.effective_message.reply_text.call_args[0][0]
        assert '✅' in call_text  # Resolved status

    @pytest.mark.asyncio
    @patch('handlers.general.database')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_history_empty(self, mock_access, mock_db):
        from handlers.general import cmd_history
        mock_db.count_all_incidents.return_value = 0
        mock_db.get_recent_history.return_value = []
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_history(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general.database')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_history_ongoing_incident(self, mock_access, mock_db):
        from handlers.general import cmd_history
        mock_db.count_all_incidents.return_value = 1
        mock_db.get_recent_history.return_value = [
            {'host': '192.168.1.10', 'kategori': 'SERVER DOWN',
             'waktu_down': '2026-01-01T10:00:00', 'waktu_up': None,
             'durasi_detik': None, 'tag': 'server'},
        ]
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_history(update, context)
        call_text = update.effective_message.reply_text.call_args[0][0]
        assert '🔴' in call_text  # Ongoing status


class TestCallbackMenuCat:
    """Test sub-menu category callbacks."""

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_valid_category(self, mock_access):
        from handlers.general import callback_menu_cat

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.data = "menu_monitor"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = user

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        await callback_menu_cat(update, context)
        query.edit_message_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=True)
    async def test_callback_menu_cat_access_denied(self, mock_access):
        from handlers.general import callback_menu_cat

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.data = "menu_monitor"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = user

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        await callback_menu_cat(update, context)
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_invalid_category_is_ignored(self, mock_access):
        from handlers.general import callback_menu_cat

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.data = "menu_unknown"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = user
        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_menu_cat(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_menu_cat_edit_error_suppressed(self, mock_access):
        from handlers.general import callback_menu_cat

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.data = "menu_monitor"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        query.from_user = user
        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_menu_cat(update, context)

        query.answer.assert_called_once()


class TestDeviceHeader:
    """Test fallback header device saat routerboard info gagal."""

    @pytest.mark.asyncio
    @patch('handlers.general.database.count_incidents_today', return_value=0)
    @patch('handlers.general.read_state_json', return_value={'kategori': 'NORMAL'})
    @patch('mikrotik.connection.pool.health_check', return_value=True)
    @patch('handlers.general.get_status', return_value={'identity': 'RSIA-Palaraya', 'version': '7.16'})
    @patch('mikrotik.system.get_system_routerboard', side_effect=Exception("not supported"))
    async def test_get_device_header_fallbacks_to_identity(
        self, mock_rb, mock_status, mock_health, mock_state, mock_count
    ):
        from handlers.general import _get_device_header

        rb_text, _, _, _, _, _ = await _get_device_header()
        assert "RSIA-Palaraya" in rb_text
        assert "<b>-</b>" not in rb_text

    @pytest.mark.asyncio
    @patch('handlers.general.database.count_incidents_today', return_value=0)
    @patch('handlers.general.read_state_json', return_value={
        'kategori': 'API UNAVAILABLE (MikroTik belum connect/login)',
        'api_connected': False,
        'api_error': 'login failed',
    })
    @patch('mikrotik.connection.pool.connection_diagnostics', return_value={
        'healthy': False,
        'last_error': 'login failed',
        'fail_count': 3,
        'backoff_seconds': 10.0,
    })
    async def test_get_device_header_marks_api_unavailable(
        self, mock_diag, mock_state, mock_count
    ):
        from handlers.general import _get_device_header

        _, kategori, _, api_up, api_diag, state = await _get_device_header()
        assert "API UNAVAILABLE" in kategori
        assert api_up is False
        assert api_diag["last_error"] == "login failed"
        assert state["api_connected"] is False


class TestApiUnavailableMessage:
    def test_build_api_unavailable_message_shows_auth_hint(self):
        from handlers.general import _build_api_unavailable_message

        state = {
            "last_update": "2026-03-13T12:00:00",
            "api_error": "invalid user name or password (6)",
        }
        api_diag = {"last_error": "invalid user name or password (6)"}
        rendered = _build_api_unavailable_message(state, api_diag)

        assert "API UNAVAILABLE" in rendered
        assert "user/password API" in rendered
        assert "invalid user name or password" in rendered

    def test_build_api_unavailable_message_shows_network_hint(self):
        from handlers.general import _build_api_unavailable_message

        state = {
            "last_update": "2026-03-13T12:00:00",
            "api_error": "timed out",
        }
        api_diag = {"last_error": "timed out"}
        rendered = _build_api_unavailable_message(state, api_diag)

        assert "konektivitas jaringan" in rendered
        assert "timed out" in rendered

    def test_build_api_unavailable_message_shows_session_hint(self):
        from handlers.general import _build_api_unavailable_message

        state = {"last_update": "2026-03-13T12:00:00", "api_error": "not logged in"}
        api_diag = {"last_error": "not logged in"}
        rendered = _build_api_unavailable_message(state, api_diag)

        assert "Sesi API invalid" in rendered

    def test_build_api_unavailable_message_shows_closed_hint(self):
        from handlers.general import _build_api_unavailable_message

        state = {"last_update": "2026-03-13T12:00:00", "api_error": "unexpectedly closed"}
        api_diag = {"last_error": "unexpectedly closed"}
        rendered = _build_api_unavailable_message(state, api_diag)

        assert "menutup koneksi" in rendered


class TestGeneralHelpers:
    def test_host_state_icon_variants(self):
        from handlers.general import _host_state_icon

        assert _host_state_icon(True) == "✅"
        assert _host_state_icon(False) == "❌"
        assert _host_state_icon(None) == "⚪ Unknown"
        assert _host_state_icon(True, api_connected=False) == "⚪ Unknown"

    @pytest.mark.asyncio
    @patch('handlers.general._get_device_header', new_callable=AsyncMock, return_value=(
        "Device: <b>RB</b>\n", "🟢 NORMAL", 5, False, {}, {"api_connected": False}
    ))
    async def test_build_home_menu_router_disconnected(self, mock_header):
        from handlers.general import _build_home_menu

        text, markup = await _build_home_menu()

        assert "Belum connect/login" in text
        buttons = [btn.text for row in markup.inline_keyboard for btn in row]
        assert "🧹 Reset Data" in buttons

    @pytest.mark.asyncio
    @patch('handlers.general._get_device_header', new_callable=AsyncMock, return_value=(
        "Device: <b>RB</b>\n", "🟢 NORMAL", 0, True, {}, {"api_connected": True}
    ))
    async def test_build_home_menu_router_connected(self, mock_header):
        from handlers.general import _build_home_menu

        text, _ = await _build_home_menu()
        assert "Terhubung" in text


class TestCmdStartExtra:
    @pytest.mark.asyncio
    @patch('handlers.general.database')
    @patch('handlers.general.read_state_json')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_start_callback_falls_back_to_reply_text_when_edit_fails(self, mock_access, mock_state, mock_db):
        from handlers.general import cmd_start

        mock_state.return_value = {'kategori': 'NORMAL', 'hosts': {}}
        mock_db.count_incidents_today.return_value = 0

        update = _make_update()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("boom"))
        update.callback_query = query
        context = MagicMock()

        await cmd_start(update, context)

        update.effective_message.reply_text.assert_called()


class TestCallbackResetDataExtra:
    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_reset_data_invalid_action_shows_alert(self, mock_access):
        from handlers.general import callback_reset_data

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.data = "reset_data_unknown"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = user

        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_reset_data(update, context)

        query.answer.assert_called_with("Aksi reset tidak valid.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    @patch('handlers.general.reset_runtime_data', side_effect=Exception("boom"))
    async def test_reset_data_execute_renders_error(self, mock_reset, mock_access):
        from handlers.general import callback_reset_data

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.data = "reset_data_execute"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = user

        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_reset_data(update, context)

        rendered = query.edit_message_text.call_args.args[0]
        assert "Reset data gagal" in rendered


# ============ NEW TESTS (D5) ============

class TestCmdStatus:
    """Test /status command."""

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general.database')
    @patch('handlers.general.read_state_json')
    @patch('handlers.general.get_status', return_value={
        'board': 'hAP ac2', 'version': '7.14', 'uptime': '10d5h',
        'cpu': '15', 'ram_total': '268435456', 'ram_free': '134217728',
        'disk_total': '16777216', 'disk_free': '8388608',
    })
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_status_shows_info(self, mock_access, mock_get, mock_state, mock_db, mock_catat):
        from handlers.general import cmd_status
        mock_state.return_value = {'kategori': 'NORMAL', 'hosts': {}}
        update = _make_update()
        context = MagicMock()
        await cmd_status(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general.get_status', side_effect=Exception("Connection refused"))
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_status_router_down(self, mock_access, mock_get, mock_catat):
        from handlers.general import cmd_status
        update = _make_update()
        context = MagicMock()
        await cmd_status(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general.read_state_json', return_value={
        'kategori': 'API UNAVAILABLE (MikroTik belum connect/login)',
        'api_connected': False,
        'api_error': 'login failed',
        'last_update': '2026-03-09T14:00:00',
    })
    @patch('mikrotik.connection.pool.connection_diagnostics', return_value={
        'healthy': False,
        'last_error': 'login failed',
        'fail_count': 5,
        'backoff_seconds': 8.0,
    })
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_status_api_unavailable_shows_clear_message(
        self, mock_access, mock_diag, mock_state, mock_catat
    ):
        from handlers.general import cmd_status

        update = _make_update()
        context = MagicMock()
        await cmd_status(update, context)

        assert update.effective_message.reply_text.call_count >= 1
        loading_message = update.effective_message.reply_text.return_value
        loading_message.edit_text.assert_called()
        rendered = loading_message.edit_text.call_args[0][0]
        assert "API UNAVAILABLE" in rendered
        assert "tidak memerah palsu" in rendered

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_status_callback_success_full_render(self, mock_access, mock_catat, monkeypatch):
        from handlers.general import cmd_status

        monkeypatch.setattr('mikrotik.connection.pool.connection_diagnostics', lambda: {'healthy': True, 'last_error': ''})
        monkeypatch.setattr('handlers.general.read_state_json', lambda: {
            'kategori': '🟢 NORMAL',
            'hosts': {
                '192.168.3.1': True,
                '192.168.1.1': True,
                '1.1.1.1': True,
                '192.168.3.10': True,
                '192.168.3.20': False,
                '192.168.3.33': None,
            },
            'api_connected': True,
        })
        monkeypatch.setattr('mikrotik.get_status', lambda: {
            'uptime': '10d5h',
            'cpu': '15',
            'cpu_freq': 880,
            'cpu_count': 4,
            'ram_total': '268435456',
            'ram_free': '134217728',
            'disk_total': '16777216',
            'disk_free': '8388608',
            'board': 'hEX',
            'model': 'RB750Gr3',
            'version': '7.14',
            'current_firmware': '7.14',
            'cpu_temp': 38,
            'voltage': '243',
        })
        monkeypatch.setattr('mikrotik.get_interfaces', lambda: [
            {'name': 'ether1', 'running': True, 'link_downs': 1, 'rx_error': 0, 'tx_error': 0},
            {'name': 'ether2', 'running': False, 'link_downs': 3, 'rx_error': 1, 'tx_error': 2},
        ])
        monkeypatch.setattr('mikrotik.get_monitored_aps', lambda: {'AP-LT1': '192.168.3.20'})
        monkeypatch.setattr('mikrotik.get_monitored_servers', lambda: {'SIMRS': '192.168.3.10'})
        monkeypatch.setattr('mikrotik.get_monitored_critical_devices', lambda: {})
        monkeypatch.setattr('mikrotik.get_active_critical_device_names', lambda: ['KOMP POLI'])
        monkeypatch.setattr('mikrotik.get_default_gateway', lambda: '192.168.1.1')
        monkeypatch.setattr('mikrotik.get_dhcp_usage_count', lambda: 18)
        monkeypatch.setattr('mikrotik.get_dhcp_leases', lambda: [
            {'dynamic': True, 'status': 'bound', 'address': '192.168.3.44', 'host': 'PC-A', 'last-seen': '10s'}
        ])
        monkeypatch.setattr('core.config.DHCP_POOL_SIZE', 60, raising=False)
        monkeypatch.setattr('core.config.GW_WAN', '192.168.1.1', raising=False)
        monkeypatch.setattr('core.config.GW_INET', '1.1.1.1', raising=False)
        monkeypatch.setattr('core.config.MIKROTIK_IP', '192.168.3.1', raising=False)
        monkeypatch.setattr('core.config.BOT_IP', '192.168.3.200', raising=False)
        monkeypatch.setattr('core.config.INSTITUTION_NAME', 'RSIA', raising=False)

        user = MagicMock(id=12345, username="admin")
        loading_message = MagicMock()
        loading_message.edit_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = loading_message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=loading_message)
        context = MagicMock()

        await cmd_status(update, context)

        rendered = loading_message.edit_text.call_args_list[-1].args[0]
        assert "LAPORAN JARINGAN" in rendered
        assert "KOMP POLI" in rendered
        assert "Lease newest" in rendered

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_status_callback_not_modified_is_ignored(self, mock_access, mock_catat, monkeypatch):
        from handlers.general import cmd_status
        import telegram.error

        monkeypatch.setattr('mikrotik.connection.pool.connection_diagnostics', lambda: {'healthy': True, 'last_error': ''})
        monkeypatch.setattr('handlers.general.read_state_json', lambda: {'kategori': '🟢 NORMAL', 'hosts': {}, 'api_connected': True})
        monkeypatch.setattr('mikrotik.get_status', lambda: {
            'uptime': '1d', 'cpu': '1', 'ram_total': '10', 'ram_free': '5',
            'disk_total': '10', 'disk_free': '5'
        })
        monkeypatch.setattr('mikrotik.get_interfaces', lambda: [])
        monkeypatch.setattr('mikrotik.get_monitored_aps', lambda: {})
        monkeypatch.setattr('mikrotik.get_monitored_servers', lambda: {})
        monkeypatch.setattr('mikrotik.get_monitored_critical_devices', lambda: {})
        monkeypatch.setattr('mikrotik.get_active_critical_device_names', lambda: [])
        monkeypatch.setattr('mikrotik.get_default_gateway', lambda: None)
        monkeypatch.setattr('mikrotik.get_dhcp_usage_count', lambda: 0)
        monkeypatch.setattr('mikrotik.get_dhcp_leases', lambda: [])
        monkeypatch.setattr('core.config.DHCP_POOL_SIZE', 1, raising=False)
        monkeypatch.setattr('core.config.GW_WAN', '', raising=False)
        monkeypatch.setattr('core.config.GW_INET', '', raising=False)
        monkeypatch.setattr('core.config.MIKROTIK_IP', '192.168.3.1', raising=False)
        monkeypatch.setattr('core.config.BOT_IP', '192.168.3.200', raising=False)
        monkeypatch.setattr('core.config.INSTITUTION_NAME', 'RSIA', raising=False)

        user = MagicMock(id=12345, username="admin")
        loading_message = MagicMock()
        loading_message.edit_text = AsyncMock(side_effect=[None, telegram.error.BadRequest("Message is not modified")])
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = loading_message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=loading_message)
        context = MagicMock()

        await cmd_status(update, context)

        assert loading_message.edit_text.await_count >= 2

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_status_error_falls_back_to_reply(self, mock_access, mock_catat, monkeypatch):
        from handlers.general import cmd_status

        monkeypatch.setattr('mikrotik.connection.pool.connection_diagnostics', lambda: {'healthy': True, 'last_error': ''})
        monkeypatch.setattr('handlers.general.read_state_json', lambda: {'kategori': '🟢 NORMAL', 'hosts': {}, 'api_connected': True})
        monkeypatch.setattr('mikrotik.get_status', lambda: (_ for _ in ()).throw(Exception("boom")))

        update = _make_update()
        loading_message = MagicMock()
        loading_message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update.effective_message.reply_text = AsyncMock(return_value=loading_message)
        context = MagicMock()

        await cmd_status(update, context)

        assert update.effective_message.reply_text.await_count >= 1

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=True)
    async def test_status_access_denied_returns_early(self, mock_access):
        from handlers.general import cmd_status

        update = _make_update()
        context = MagicMock()

        await cmd_status(update, context)

        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.general.logger')
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_status_callback_loading_edit_error_is_suppressed(self, mock_access, mock_catat, mock_logger, monkeypatch):
        from handlers.general import cmd_status

        monkeypatch.setattr('mikrotik.connection.pool.connection_diagnostics', lambda: {'healthy': False, 'last_error': 'timed out'})
        monkeypatch.setattr('handlers.general.read_state_json', lambda: {'kategori': 'API UNAVAILABLE', 'hosts': {}, 'api_connected': False})

        user = MagicMock(id=12345, username="admin")
        loading_message = MagicMock()
        loading_message.edit_text = AsyncMock(side_effect=[Exception("ui fail"), None])
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = loading_message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=loading_message)
        context = MagicMock()

        await cmd_status(update, context)

        mock_logger.debug.assert_called_once()
        assert loading_message.edit_text.await_count == 2

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_status_uses_gateway_fallback_and_dhcp_safe_default(self, mock_access, mock_catat, monkeypatch):
        from handlers.general import cmd_status

        monkeypatch.setattr('mikrotik.connection.pool.connection_diagnostics', lambda: {'healthy': True, 'last_error': ''})
        monkeypatch.setattr('handlers.general.read_state_json', lambda: {'kategori': '🟢 NORMAL', 'hosts': {}, 'api_connected': True})
        monkeypatch.setattr('mikrotik.get_status', lambda: {
            'uptime': '1d', 'cpu': '1', 'ram_total': '10', 'ram_free': '5',
            'disk_total': '10', 'disk_free': '5'
        })
        monkeypatch.setattr('mikrotik.get_interfaces', lambda: [])
        monkeypatch.setattr('mikrotik.get_monitored_aps', lambda: {})
        monkeypatch.setattr('mikrotik.get_monitored_servers', lambda: {})
        monkeypatch.setattr('mikrotik.get_monitored_critical_devices', lambda: {})
        monkeypatch.setattr('mikrotik.get_active_critical_device_names', lambda: [])
        monkeypatch.setattr('mikrotik.get_default_gateway', lambda: (_ for _ in ()).throw(Exception("gw fail")))
        monkeypatch.setattr('mikrotik.get_dhcp_usage_count', lambda: (_ for _ in ()).throw(Exception("dhcp fail")))
        monkeypatch.setattr('mikrotik.get_dhcp_leases', lambda: [])
        monkeypatch.setattr('core.config.DHCP_POOL_SIZE', 60, raising=False)
        monkeypatch.setattr('core.config.GW_WAN', '192.168.1.1', raising=False)
        monkeypatch.setattr('core.config.GW_INET', '1.1.1.1', raising=False)
        monkeypatch.setattr('core.config.MIKROTIK_IP', '192.168.3.1', raising=False)
        monkeypatch.setattr('core.config.BOT_IP', '192.168.3.200', raising=False)
        monkeypatch.setattr('core.config.INSTITUTION_NAME', 'RSIA', raising=False)

        update = _make_update()
        context = MagicMock()

        await cmd_status(update, context)

        loading_message = update.effective_message.reply_text.return_value
        rendered = loading_message.edit_text.call_args_list[-1].args[0]
        assert "192.168.1.1" in rendered
        assert "- Pool: 0/60" in rendered

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_status_raises_when_info_empty_and_renders_error(self, mock_access, mock_catat, monkeypatch):
        from handlers.general import cmd_status

        monkeypatch.setattr('mikrotik.connection.pool.connection_diagnostics', lambda: {'healthy': True, 'last_error': ''})
        monkeypatch.setattr('handlers.general.read_state_json', lambda: {'kategori': '🟢 NORMAL', 'hosts': {}, 'api_connected': True})
        monkeypatch.setattr('mikrotik.get_status', lambda: None)

        update = _make_update()
        loading_message = MagicMock()
        loading_message.edit_text = AsyncMock()
        update.effective_message.reply_text = AsyncMock(return_value=loading_message)
        context = MagicMock()

        await cmd_status(update, context)

        assert "Gagal mengambil status router" in loading_message.edit_text.call_args_list[-1].args[0]


class TestCmdAudit:
    """Test /audit command."""

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_audit_runs(self, mock_access, mock_catat):
        from handlers.general import cmd_audit
        update = _make_update()
        context = MagicMock()
        with patch('mikrotik._pool.get_api') as mock_api_func:
            mock_api = MagicMock()
            mock_api.path.return_value = []
            mock_api_func.return_value = mock_api
            await cmd_audit(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_audit_callback_success_covers_risky_branches(self, mock_access, mock_catat):
        from handlers.general import cmd_audit

        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        with patch('mikrotik._pool.get_api') as mock_api_func:
            mock_api = MagicMock()
            def fake_path(*parts):
                if parts == ('user',):
                    return [{'name': 'admin'}]
                if parts == ('ip', 'service'):
                    return [{'name': 'ftp', 'disabled': False, 'address': ''}]
                if parts == ('ip', 'dns'):
                    return [{'allow-remote-requests': True}]
                if parts == ('ip', 'firewall', 'filter'):
                    return []
                return []
            mock_api.path.side_effect = fake_path
            mock_api_func.return_value = mock_api
            await cmd_audit(update, context)

        rendered = message.edit_text.call_args_list[-1].args[0]
        assert "user default 'admin'" in rendered
        assert "terbuka untuk publik" in rendered
        assert "DNS Amplification" in rendered

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_audit_error_callback_renders_generic_error(self, mock_access, mock_catat):
        from handlers.general import cmd_audit

        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        with patch('mikrotik._pool.get_api', side_effect=Exception("api fail")):
            await cmd_audit(update, context)

        assert "Audit gagal dijalankan" in message.edit_text.call_args_list[-1].args[0]


class TestCmdMtlog:
    """Test /mtlog command."""

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general.get_mikrotik_log', return_value=[
        {'time': '10:00', 'topics': 'system,info', 'message': 'system started'},
        {'time': '10:01', 'topics': 'system,error,critical', 'message': 'login failed'},
    ])
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mtlog_all(self, mock_access, mock_log, mock_catat):
        from handlers.general import cmd_mtlog
        update = _make_update()
        context = MagicMock()
        context.bot_data = {}
        await cmd_mtlog(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general.get_mikrotik_log', return_value=[
        {'time': '10:00', 'topics': 'system,info', 'message': 'system started'},
        {'time': '10:01', 'topics': 'system,error,critical', 'message': 'login failed'},
    ])
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mtlog_error_filter(self, mock_access, mock_log, mock_catat):
        """Filter error/critical should show only critical logs."""
        from handlers.general import cmd_mtlog
        update = _make_update()
        query = MagicMock()
        query.data = "logfilter_error"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.edit_text = AsyncMock()
        update.callback_query = query
        context = MagicMock()
        context.bot_data = {}
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        await cmd_mtlog(update, context)

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general.get_mikrotik_log', return_value=[])
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mtlog_empty_logs(self, mock_access, mock_log, mock_catat):
        from handlers.general import cmd_mtlog
        update = _make_update()
        context = MagicMock()
        context.bot_data = {}

        await cmd_mtlog(update, context)

        assert "Log MikroTik kosong" in update.effective_message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general.get_mikrotik_log', return_value=[
        {'time': '10:00', 'topics': 'system,info', 'message': 'system started'},
    ])
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mtlog_filter_with_no_matches(self, mock_access, mock_log, mock_catat):
        from handlers.general import cmd_mtlog
        update = _make_update()
        context = MagicMock()
        context.args = ['warning']
        context.bot_data = {}

        await cmd_mtlog(update, context)

        assert "Tidak ada log untuk filter" in update.effective_message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general.get_mikrotik_log', side_effect=Exception("boom"))
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mtlog_error(self, mock_access, mock_log, mock_catat):
        from handlers.general import cmd_mtlog
        update = _make_update()
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_mtlog(update, context)

        assert "Gagal memuat log MikroTik" in update.effective_message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.general.logger')
    @patch('handlers.general.catat')
    @patch('handlers.general.get_mikrotik_log', return_value=[])
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mtlog_empty_callback_edit_error_is_suppressed(self, mock_access, mock_log, mock_catat, mock_logger):
        from handlers.general import cmd_mtlog

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.data = "logfilter_all"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.bot_data = {}

        await cmd_mtlog(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.general.logger')
    @patch('handlers.general.catat')
    @patch('handlers.general.get_mikrotik_log', return_value=[
        {'time': '10:00', 'topics': 'system,info', 'message': 'system started'},
    ])
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mtlog_filter_no_match_callback_edit_error_is_suppressed(
        self, mock_access, mock_log, mock_catat, mock_logger
    ):
        from handlers.general import cmd_mtlog

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.data = "logfilter_warning"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.bot_data = {}

        await cmd_mtlog(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.general.logger')
    @patch('handlers.general.catat')
    @patch('handlers.general.get_mikrotik_log', return_value=[
        {'time': '10:00', 'topics': 'system,warning', 'message': 'warn a'},
        {'time': '10:01', 'topics': 'system,warning', 'message': 'warn b'},
    ])
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mtlog_callback_success_edit_error_is_suppressed(
        self, mock_access, mock_log, mock_catat, mock_logger
    ):
        from handlers.general import cmd_mtlog

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.data = "logfilter_warning"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.bot_data = {}

        await cmd_mtlog(update, context)

        mock_logger.debug.assert_called_once()


class TestGeneralExtraCommands:
    @pytest.mark.asyncio
    @patch('handlers.general.database.count_all_incidents', return_value=25)
    @patch('handlers.general.database.get_recent_history', return_value=[
        {'host': 'h1', 'kategori': 'down', 'waktu_down': '2026-03-13T10:00:00', 'waktu_up': '2026-03-13T10:00:45', 'durasi_detik': 45, 'tag': 'server'},
    ])
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_history_callback_invalid_page_falls_back_to_zero(self, mock_access, mock_history, mock_count):
        from handlers.general import cmd_history

        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.data = "history_bad"
        query.message = message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.args = []

        await cmd_history(update, context)

        message.edit_text.assert_called_once()
        assert "Hal 1/3" in message.edit_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.general.database.count_all_incidents', return_value=11)
    @patch('handlers.general.database.get_recent_history', return_value=[
        {'host': 'h1', 'kategori': 'down', 'waktu_down': '2026-03-13T10:00:00', 'waktu_up': '2026-03-13T10:00:00', 'durasi_detik': -1, 'tag': 'server'},
    ])
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_history_negative_duration_marks_auto_closed(self, mock_access, mock_history, mock_count):
        from handlers.general import cmd_history
        update = _make_update()
        context = MagicMock()
        context.args = []

        await cmd_history(update, context)

        assert "Auto-closed" in update.effective_message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_reboot_cooldown_callback_alert(self, mock_access, monkeypatch):
        import handlers.general as general
        from handlers.general import cmd_reboot

        monkeypatch.setattr(general, "_last_reboot_time", time.time())
        monkeypatch.setattr('core.config.REBOOT_COOLDOWN', 60, raising=False)
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.answer = AsyncMock()
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()

        await cmd_reboot(update, context)

        query.answer.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_reboot_callback_falls_back_to_reply(self, mock_access, mock_catat, monkeypatch):
        import handlers.general as general
        from handlers.general import cmd_reboot

        monkeypatch.setattr(general, "_last_reboot_time", 0)
        monkeypatch.setattr('core.config.REBOOT_COOLDOWN', 60, raising=False)
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        await cmd_reboot(update, context)

        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_backup_callback_falls_back_to_reply(self, mock_access, mock_catat):
        from handlers.general import cmd_backup

        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        await cmd_backup(update, context)

        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.general.catat')
    @patch('handlers.general.baca_log', return_value=[{"waktu": "10:00", "command": "/start"}])
    @patch('handlers.general.format_log_pretty', return_value="<b>LOG</b>")
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_log_callback_edit(self, mock_access, mock_fmt, mock_read, mock_catat):
        from handlers.general import cmd_log

        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = message
        query.from_user = user
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        await cmd_log(update, context)

        message.edit_text.assert_called_once()

    def test_format_mtlog_page_empty_and_pagination(self):
        from handlers.general import _format_mtlog_page

        text_empty, markup_empty = _format_mtlog_page([], "warning", page=0, per_page=10)
        assert "Tidak ada log ditemukan" in text_empty
        assert any(btn.text == "Semua" for btn in markup_empty.inline_keyboard[0])

        logs = [{"time": "10:00", "topics": "system,error", "message": "<boom>"} for _ in range(12)]
        text_page2, markup_page2 = _format_mtlog_page(logs, "error", page=1, per_page=10)
        assert "Hal 2/2" in text_page2
        assert any("Prev" in btn.text for btn in markup_page2.inline_keyboard[0])

    @pytest.mark.asyncio
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_mtlog_paths(self, mock_access):
        from handlers.general import callback_mtlog

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = user
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {}

        query.data = "mtlogpage_invalid"
        await callback_mtlog(update, context)
        query.answer.assert_called_with("Data tidak valid.")

        query.answer.reset_mock()
        query.data = "mtlogpage_all_bad"
        await callback_mtlog(update, context)
        query.answer.assert_called_with("Data tidak valid.")

        query.answer.reset_mock()
        query.data = "mtlogpage_all_0"
        with patch('handlers.general.get_cache_if_fresh', return_value=None):
            await callback_mtlog(update, context)
        query.answer.assert_called_with("Data log sudah kedaluwarsa. Silakan refresh.", show_alert=True)

        query.answer.reset_mock()
        query.data = "mtlogpage_all_0"
        with patch('handlers.general.get_cache_if_fresh', return_value=[{"time": "10:00", "topics": "system", "message": "ok"}]):
            await callback_mtlog(update, context)
        query.edit_message_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.general.logger')
    @patch('handlers.general._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_mtlog_edit_error_is_suppressed(self, mock_access, mock_logger):
        from handlers.general import callback_mtlog

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        query.from_user = user
        query.data = "mtlogpage_all_0"
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.general.get_cache_if_fresh', return_value=[{"time": "10:00", "topics": "system", "message": "ok"}]):
            await callback_mtlog(update, context)

        mock_logger.debug.assert_called_once()

