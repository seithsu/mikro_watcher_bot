# ============================================
# TEST_HANDLERS_TOOLS - Tests for handlers/tools.py
# Ping, DNS, Firewall, Schedule, VPN, Uptime, Config
# ============================================

import pytest
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


# ============ /ping ============

class TestPingCommand:
    """Test /ping command."""

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools._get_ping_hosts')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_ping_shows_host_menu(self, mock_access, mock_hosts, mock_catat):
        from handlers.tools import cmd_ping
        mock_hosts.return_value = {'Router': '192.168.1.1', 'Server': '10.0.0.1'}

        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_ping(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.ping_host', return_value="Reply from 8.8.8.8: bytes=32 time=5ms TTL=119")
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_ping_with_ip_arg(self, mock_access, mock_ping, mock_catat):
        from handlers.tools import cmd_ping
        update = _make_update()
        context = MagicMock()
        context.args = ['8.8.8.8']
        await cmd_ping(update, context)
        assert update.effective_message.reply_text.called or update.effective_message.edit_text.called

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.ping_host', return_value="Reply from 192.168.1.1: bytes=32 time=1ms")
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_ping_executes(self, mock_access, mock_ping, mock_catat):
        from handlers.tools import callback_ping

        update = _make_update()
        query = MagicMock()
        query.data = "ping_192.168.1.1"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.edit_text = AsyncMock()
        update.callback_query = query
        update.effective_user = MagicMock(id=12345, username="admin")

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        await callback_ping(update, context)

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.ping_host', side_effect=Exception("timeout"))
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_ping_failure_handled(self, mock_access, mock_ping, mock_catat):
        from handlers.tools import cmd_ping
        update = _make_update()
        context = MagicMock()
        context.args = ['192.168.99.99']
        await cmd_ping(update, context)
        assert update.effective_message.reply_text.called or update.effective_message.edit_text.called

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.ping_host', return_value={
        "host": "192.168.1.1", "sent": 3, "received": 0, "loss": 100, "avg_rtt": 0
    })
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_execute_ping_falls_back_to_reply_when_edit_loading_fails(self, mock_access, mock_ping, mock_catat):
        from handlers.tools import _execute_ping
        update = _make_update()
        update.effective_message.edit_text = AsyncMock(side_effect=Exception("boom"))
        reply_message = MagicMock()
        reply_message.edit_text = AsyncMock()
        update.effective_message.reply_text = AsyncMock(return_value=reply_message)
        context = MagicMock()

        await _execute_ping(update, context, "192.168.1.1")

        update.effective_message.reply_text.assert_called()
        reply_message.edit_text.assert_called()


class TestConfigResetCallback:
    @pytest.mark.asyncio
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_config_reset_confirm_renders_warning(self, mock_access):
        from handlers.tools import callback_config_reset

        query = MagicMock()
        query.data = "config_reset_confirm"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = MagicMock(id=12345, username="admin")
        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_config_reset(update, context)

        query.edit_message_text.assert_called()
        assert "KONFIRMASI RESET SEMUA DATA" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.database.reset_all_data')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_config_reset_execute_success(self, mock_access, mock_reset, mock_catat):
        from handlers.tools import callback_config_reset

        query = MagicMock()
        query.data = "config_reset_execute"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = MagicMock(id=12345, username="admin")
        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_config_reset(update, context)

        mock_reset.assert_called_once()
        assert "Reset Berhasil" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.database.reset_all_data', side_effect=Exception("boom"))
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_config_reset_execute_error(self, mock_access, mock_reset, mock_catat):
        from handlers.tools import callback_config_reset

        query = MagicMock()
        query.data = "config_reset_execute"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user = MagicMock(id=12345, username="admin")
        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_config_reset(update, context)

        assert "Reset data gagal" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_config_reset_confirm_edit_error_is_suppressed(self, mock_access, mock_logger):
        from handlers.tools import callback_config_reset

        query = MagicMock()
        query.data = "config_reset_confirm"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        query.from_user = MagicMock(id=12345, username="admin")
        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_config_reset(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.database.reset_all_data', side_effect=Exception("boom"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_config_reset_execute_edit_error_is_suppressed(self, mock_access, mock_catat, mock_reset, mock_logger):
        from handlers.tools import callback_config_reset

        query = MagicMock()
        query.data = "config_reset_execute"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        query.from_user = MagicMock(id=12345, username="admin")
        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_config_reset(update, context)

        mock_logger.debug.assert_called_once()


# ============ /dns ============

class TestDnsCommand:
    """Test /dns command."""

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_dns_static', return_value=[
        {'.id': '*1', 'name': 'server.local', 'address': '192.168.1.10', 'disabled': 'false'},
        {'.id': '*2', 'name': 'db.local', 'address': '192.168.1.11', 'disabled': 'false'},
    ])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dns_list(self, mock_access, mock_dns, mock_catat):
        from handlers.tools import cmd_dns
        update = _make_update()
        context = MagicMock()
        context.bot_data = {}
        context.args = []
        await cmd_dns(update, context)
        update.effective_message.reply_text.assert_called()
        assert context.bot_data['dns_entries']

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_dns_static', return_value=[])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dns_empty(self, mock_access, mock_dns, mock_catat):
        from handlers.tools import cmd_dns
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_dns(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_dns_static', side_effect=Exception("boom"))
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dns_error(self, mock_access, mock_dns, mock_catat):
        from handlers.tools import cmd_dns
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_dns(update, context)
        assert "Gagal memuat DNS static" in update.effective_message.reply_text.call_args.args[0]


# ============ /firewall ============

class TestFirewallCommand:
    """Test /firewall command."""

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_firewall_rules', return_value=[
        {'.id': '*1', 'chain': 'forward', 'action': 'drop', 'disabled': 'false',
         'src-address': '10.0.0.0/24', 'dst-address': '', 'comment': 'Block subnet'},
    ])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_firewall_filter_list(self, mock_access, mock_fw, mock_catat):
        from handlers.tools import cmd_firewall
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_firewall(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_firewall_rules', return_value=[])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_firewall_empty(self, mock_access, mock_fw, mock_catat):
        from handlers.tools import cmd_firewall
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_firewall(update, context)
        update.effective_message.reply_text.assert_called()


# ============ /schedule ============

class TestScheduleCommand:
    """Test /schedule command."""

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_schedulers', return_value=[
        {'.id': '*1', 'name': 'reboot-nightly', 'start-time': '03:00:00',
         'interval': '1d', 'disabled': 'false', 'on-event': '/system reboot'},
    ])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_schedule_list(self, mock_access, mock_sched, mock_catat):
        from handlers.tools import cmd_schedule
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_schedule(update, context)
        update.effective_message.reply_text.assert_called()


# ============ /vpn ============

class TestVpnCommand:
    """Test /vpn command."""

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_vpn_tunnels', return_value=[
        {'name': 'vpn-user1', 'type': 'l2tp', 'remote': '10.0.0.2', 'uptime': '2h30m', 'comment': '', 'running': True, 'disabled': False},
    ])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_vpn_with_tunnels(self, mock_access, mock_vpn, mock_catat):
        from handlers.tools import cmd_vpn
        update = _make_update()
        context = MagicMock()
        await cmd_vpn(update, context)
        update.effective_message.reply_text.assert_called()
        assert "vpn-user1" in update.effective_message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_vpn_tunnels', return_value=[])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_vpn_empty(self, mock_access, mock_vpn, mock_catat):
        from handlers.tools import cmd_vpn
        update = _make_update()
        context = MagicMock()
        await cmd_vpn(update, context)
        update.effective_message.reply_text.assert_called()


# ============ /uptime ============

class TestUptimeCommand:
    """Test /uptime command."""

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.database.get_uptime_stats', return_value={
        '192.168.1.1': {
            'uptime_pct': 99.9, 'incident_count': 1,
            'total_downtime_sec': 60, 'total_downtime_str': '1m 0s',
        },
    })
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_uptime_7d(self, mock_access, mock_stats, mock_catat):
        from handlers.tools import cmd_uptime
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_uptime(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.database.get_uptime_stats', return_value={})
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_uptime_empty(self, mock_access, mock_stats, mock_catat):
        from handlers.tools import cmd_uptime
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_uptime(update, context)
        update.effective_message.reply_text.assert_called()


# ============ /config ============

class TestConfigCommand:
    """Test /config command."""

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_config_show_all(self, mock_access, mock_catat):
        from handlers.tools import cmd_config
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_config(update, context)
        update.effective_message.reply_text.assert_called()
        call_text = update.effective_message.reply_text.call_args[0][0]
        # Should show config values
        assert 'CPU' in call_text or 'config' in call_text.lower()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('services.config_manager.set_config', return_value=(True, "✅ Updated"))
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_config_set_valid(self, mock_access, mock_set, mock_catat):
        from handlers.tools import cmd_config
        update = _make_update()
        context = MagicMock()
        context.args = ['set', 'CPU_THRESHOLD', '90']
        await cmd_config(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('services.config_manager.reset_config', return_value=(True, "✅ Reset"))
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_config_reset(self, mock_access, mock_reset, mock_catat):
        from handlers.tools import cmd_config
        update = _make_update()
        context = MagicMock()
        context.args = ['reset', 'CPU_THRESHOLD']
        await cmd_config(update, context)
        update.effective_message.reply_text.assert_called()


class TestToolsFormattersAndCallbacks:
    def test_get_ping_hosts_merges_queue_and_defaults(self):
        from handlers.tools import _get_ping_hosts

        with patch('handlers.tools.get_simple_queues', return_value=[
            {'target': '192.168.3.10/32', 'name': 'SIMRS-Q'},
            {'target': '192.168.3.20/32', 'name': 'AP-Q'},
        ]), patch('handlers.tools.get_monitored_aps', return_value={'AP-LABEL': '192.168.3.20'}), patch(
            'handlers.tools.get_monitored_servers', return_value={'SERVER-LABEL': '192.168.3.10'}
        ):
            hosts = _get_ping_hosts()

        assert hosts['SIMRS-Q'] == '192.168.3.10'
        assert hosts['AP-Q'] == '192.168.3.20'
        assert hosts['Internet (1.1.1.1)'] == '1.1.1.1'

    def test_get_ping_hosts_handles_queue_fetch_failure(self):
        from handlers.tools import _get_ping_hosts

        with patch('handlers.tools.get_simple_queues', side_effect=Exception("boom")), patch(
            'handlers.tools.get_monitored_aps', return_value={'AP-LABEL': '192.168.3.20'}
        ), patch('handlers.tools.get_monitored_servers', return_value={'SERVER-LABEL': '192.168.3.10'}):
            hosts = _get_ping_hosts()

        assert hosts['SERVER-LABEL'] == '192.168.3.10'
        assert hosts['AP-LABEL'] == '192.168.3.20'
        assert hosts['DNS Google (8.8.8.8)'] == '8.8.8.8'

    def test_dns_schedule_firewall_page_formatters(self):
        from handlers.tools import _format_dns_page, _format_schedule_page, _format_firewall_page

        dns_text, dns_markup = _format_dns_page(
            [{'id': '*1', 'name': 'simrs.local', 'address': '192.168.3.10', 'disabled': False, 'comment': 'srv'}],
            page=0,
            per_page=10,
        )
        assert "DNS Static Entries" in dns_text
        assert dns_markup.inline_keyboard[-1][0].text == "🔄 Refresh"

        sched_text, sched_markup = _format_schedule_page(
            [{
                'id': '*A',
                'name': 'nightly-backup',
                'disabled': False,
                'interval': '1d',
                'on_event': '/system backup save name=nightly-backup-file',
                'run_count': '42',
            }],
            page=0,
            per_page=10,
        )
        assert "RouterOS Scheduler" in sched_text
        assert sched_markup.inline_keyboard[-1][0].text == "🔄 Refresh"

        fw_text, fw_markup = _format_firewall_page(
            [{
                'id': '*F',
                'disabled': False,
                'comment': 'allow',
                'action': 'accept',
                'src_address': '192.168.3.0/24',
                'dst_address': '',
                'protocol': 'tcp',
                'dst_port': '80',
                'bytes': '1024',
                'chain': 'filter',
            }],
            chain_type='filter',
            page=0,
            per_page=8,
        )
        assert "Firewall FILTER Rules" in fw_text
        assert any("Switch to NAT" in btn.text for btn in fw_markup.inline_keyboard[-1])

    @pytest.mark.asyncio
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_schedule_invalid_page_and_expired(self, mock_access):
        from handlers.tools import callback_schedule

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot_data = {}

        query.data = "schedpage_invalid"
        await callback_schedule(update, context)
        query.answer.assert_called_with("Data tidak valid.", show_alert=True)

        query.answer.reset_mock()
        query.data = "schedpage_0"
        await callback_schedule(update, context)
        query.answer.assert_called_with("Data expired. Silakan /schedule lagi.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_firewall_invalid_payload(self, mock_access):
        from handlers.tools import callback_firewall

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot_data = {}

        query.data = "fwtoggle_onlychain"
        await callback_firewall(update, context)
        query.answer.assert_called_with("Data tidak valid.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_dns_prompt_and_expired(self, mock_access):
        from handlers.tools import callback_dns
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot_data = {}
        context.user_data = {}

        query.data = "dnspage_0"
        await callback_dns(update, context)
        query.answer.assert_called_with("Data expired. Silakan /dns lagi.", show_alert=True)

        query.answer.reset_mock()
        query.data = "dns_add_prompt"
        await callback_dns(update, context)
        assert context.user_data.get("awaiting_dns_add") is True
        query.edit_message_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_dns_static', return_value=[])
    @patch('handlers.tools.remove_dns_static')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_dns_delete_success_empty_after_refresh(self, mock_access, mock_remove, mock_get, mock_catat):
        from handlers.tools import callback_dns

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {"dns_entries": [{"id": "*1", "name": "a", "address": "1.1.1.1", "disabled": False, "comment": ""}]}
        context.user_data = {}

        query.data = "dnsdel_*1"
        await callback_dns(update, context)

        mock_remove.assert_called_once_with("*1")
        assert "Tidak ada entry tersisa" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.remove_dns_static', side_effect=Exception("boom"))
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_dns_delete_error(self, mock_access, mock_remove):
        from handlers.tools import callback_dns

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {"dns_entries": [{"id": "*1", "name": "a", "address": "1.1.1.1", "disabled": False, "comment": ""}]}
        context.user_data = {}

        query.data = "dnsdel_*1"
        await callback_dns(update, context)

        assert "Gagal menghapus DNS" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_dns_static', return_value=[{"id": "*1", "name": "simrs.local", "address": "192.168.3.10", "disabled": False, "comment": ""}])
    @patch('handlers.tools.add_dns_static')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_dns_add_confirm_success(self, mock_access, mock_add, mock_get, mock_catat):
        from handlers.tools import callback_dns

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {}
        context.user_data = {"pending_dns": {"name": "simrs.local", "address": "192.168.3.10"}, "awaiting_dns_add": True}

        query.data = "dns_add_confirm"
        await callback_dns(update, context)

        mock_add.assert_called_once()
        assert "ditambahkan" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.add_dns_static', side_effect=Exception("boom"))
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_dns_add_confirm_error(self, mock_access, mock_add):
        from handlers.tools import callback_dns

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {}
        context.user_data = {"pending_dns": {"name": "simrs.local", "address": "192.168.3.10"}}

        query.data = "dns_add_confirm"
        await callback_dns(update, context)

        assert "Gagal menambah DNS" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    async def test_handle_dns_add_paths(self, monkeypatch):
        from handlers.tools import handle_dns_add

        msg = MagicMock()
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.message = msg
        update.effective_user = MagicMock(id=12345, username="admin")
        context = MagicMock()
        context.user_data = {}

        # Not awaiting -> ignore
        assert await handle_dns_add(update, context) is False

        context.user_data = {"awaiting_dns_add": True}
        monkeypatch.setattr("handlers.tools.cek_admin", lambda _uid: True)
        update.message.text = "invalidformat"
        assert await handle_dns_add(update, context) is True
        msg.reply_text.assert_called()

        msg.reply_text.reset_mock()
        update.message.text = "simrs.local 192.168.3.10"
        assert await handle_dns_add(update, context) is True
        assert context.user_data["pending_dns"]["name"] == "simrs.local"
        msg.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_handle_dns_add_non_admin_ignored(self, monkeypatch):
        from handlers.tools import handle_dns_add

        msg = MagicMock()
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.message = msg
        update.message.text = "simrs.local 192.168.3.10"
        update.effective_user = MagicMock(id=12345, username="admin")
        context = MagicMock()
        context.user_data = {"awaiting_dns_add": True}

        monkeypatch.setattr("handlers.tools.cek_admin", lambda _uid: False)
        assert await handle_dns_add(update, context) is False
        msg.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_schedulers', return_value=[
        {'id': '*1', 'name': 'sched1', 'disabled': False, 'interval': '1d', 'on_event': '/log info test', 'run_count': '1'},
    ])
    @patch('handlers.tools.set_scheduler_status')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_schedule_toggle_and_exec(self, mock_access, mock_set, mock_get, mock_catat):
        from handlers.tools import callback_schedule

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {
            "schedulers": [{'id': '*1', 'name': 'sched1', 'disabled': False, 'interval': '1d', 'on_event': '/log info test', 'run_count': '1'}]
        }

        query.data = "schedtoggle_*1"
        await callback_schedule(update, context)
        query.edit_message_text.assert_called()

        query.data = "schedexec_*1"
        await callback_schedule(update, context)
        mock_set.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.get_firewall_rules', return_value=[])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_firewall_switch_empty_rules(self, mock_access, mock_rules):
        from handlers.tools import callback_firewall

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {}

        query.data = "fwswitch_nat"
        await callback_firewall(update, context)
        query.edit_message_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.tools.toggle_firewall_rule')
    @patch('handlers.tools.get_firewall_rules', return_value=[{
        'id': '*1', 'disabled': True, 'comment': 'allow', 'action': 'accept',
        'src_address': '', 'dst_address': '', 'protocol': 'tcp', 'dst_port': '80', 'bytes': '0', 'chain': 'filter'
    }])
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_firewall_exec_success(self, mock_access, mock_catat, mock_rules, mock_toggle):
        from handlers.tools import callback_firewall

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {'fw_filter': [{
            'id': '*1', 'disabled': False, 'comment': 'allow', 'action': 'accept',
            'src_address': '', 'dst_address': '', 'protocol': 'tcp', 'dst_port': '80', 'bytes': '0', 'chain': 'filter'
        }]}

        query.data = "fwexec_filter_*1"
        await callback_firewall(update, context)

        mock_toggle.assert_called_once()
        query.edit_message_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.tools._get_ping_hosts', return_value={'Router': '192.168.1.1'})
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_ping_callback_answers_and_edits(self, mock_access, mock_hosts):
        from handlers.tools import cmd_ping
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []

        await cmd_ping(update, context)

        query.answer.assert_called_once()
        query.message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.ping_host', return_value={
        "host": "192.168.1.1", "sent": 3, "received": 3, "loss": 0, "avg_rtt": 1
    })
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_execute_ping_final_edit_error_is_suppressed(self, mock_access, mock_ping, mock_catat):
        from handlers.tools import _execute_ping
        update = _make_update()
        update.effective_message.edit_text = AsyncMock(side_effect=[None, Exception("ui fail")])
        context = MagicMock()

        await _execute_ping(update, context, "192.168.1.1")

        assert update.effective_message.edit_text.await_count == 2

    @pytest.mark.asyncio
    @patch('handlers.tools.get_dns_static', return_value=[])
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dns_callback_empty_uses_edit(self, mock_access, mock_catat, mock_dns):
        from handlers.tools import cmd_dns
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []

        await cmd_dns(update, context)

        query.answer.assert_called_once()
        query.message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.get_dns_static', return_value=[])
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dns_callback_empty_edit_error_is_suppressed(self, mock_access, mock_catat, mock_dns, mock_logger):
        from handlers.tools import cmd_dns
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_dns(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.get_dns_static', return_value=[
        {'.id': '*1', 'name': 'server.local', 'address': '192.168.1.10', 'disabled': 'false'},
    ])
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dns_callback_success_edit_error_is_suppressed(self, mock_access, mock_catat, mock_dns, mock_logger):
        from handlers.tools import cmd_dns
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_dns(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.catat')
    @patch('handlers.tools.get_dns_static', return_value=[
        {'id': '*1', 'name': 'server.local', 'address': '192.168.1.10', 'disabled': False, 'comment': 'srv'},
    ])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dns_list_success_with_runtime_schema(self, mock_access, mock_dns, mock_catat):
        from handlers.tools import cmd_dns
        update = _make_update()
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_dns(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "DNS Static Entries" in update.effective_message.reply_text.call_args.args[0]
        assert context.bot_data["dns_entries"][0]["id"] == "*1"

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.get_dns_static', return_value=[
        {'id': '*1', 'name': 'server.local', 'address': '192.168.1.10', 'disabled': False, 'comment': 'srv'},
    ])
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dns_callback_success_with_runtime_schema_edit_error_suppressed(
        self, mock_access, mock_catat, mock_dns, mock_logger
    ):
        from handlers.tools import cmd_dns
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_dns(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.get_dns_static', side_effect=Exception("boom"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dns_callback_error_edit_error_is_suppressed(self, mock_access, mock_catat, mock_dns, mock_logger):
        from handlers.tools import cmd_dns
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_dns(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.get_schedulers', return_value=[])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_schedule_callback_empty(self, mock_access, mock_sched):
        from handlers.tools import cmd_schedule
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()

        await cmd_schedule(update, context)

        query.answer.assert_called_once()
        query.message.edit_text.assert_called_once()
        assert "Tidak ada scheduler entry" in query.message.edit_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.get_schedulers', return_value=[])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_schedule_callback_empty_edit_error_is_suppressed(self, mock_access, mock_sched, mock_logger):
        from handlers.tools import cmd_schedule
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()

        await cmd_schedule(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.get_schedulers', side_effect=Exception("boom"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_schedule_error_reply(self, mock_access, mock_catat, mock_sched):
        from handlers.tools import cmd_schedule
        update = _make_update()
        context = MagicMock()

        await cmd_schedule(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "Gagal memuat scheduler" in update.effective_message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_schedule_not_found_and_error_paths(self, mock_access):
        from handlers.tools import callback_schedule

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {"schedulers": [{'id': '*1', 'name': 'sched1', 'disabled': False, 'interval': '1d', 'on_event': '/log info test', 'run_count': '1'}]}

        query.data = "schedtoggle_*404"
        await callback_schedule(update, context)
        query.answer.assert_called_with("Entry tidak ditemukan.", show_alert=True)

        query.answer.reset_mock()
        query.data = "schedexec_*404"
        await callback_schedule(update, context)
        query.answer.assert_called_with("Entry tidak ditemukan.", show_alert=True)

        query.answer.reset_mock()
        query.data = "schedexec_*1"
        with patch('handlers.tools.set_scheduler_status', side_effect=Exception("boom")):
            await callback_schedule(update, context)
        assert "Gagal mengubah scheduler" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_schedule_page_and_confirm_edit_errors_are_suppressed(self, mock_access, mock_logger):
        from handlers.tools import callback_schedule

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=[Exception("ui1"), Exception("ui2")])
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {
            "schedulers": [{'id': '*1', 'name': 'sched1', 'disabled': False, 'interval': '1d', 'on_event': '/log info test', 'run_count': '1'}]
        }

        query.data = "schedpage_0"
        await callback_schedule(update, context)

        query.data = "schedtoggle_*1"
        await callback_schedule(update, context)

        assert mock_logger.debug.call_count == 2

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.get_schedulers', return_value=[
        {'id': '*1', 'name': 'sched1', 'disabled': False, 'interval': '1d', 'on_event': '/log info test', 'run_count': '1'},
    ])
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_schedule_callback_edit_error_is_suppressed(self, mock_access, mock_catat, mock_sched, mock_logger):
        from handlers.tools import cmd_schedule
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()

        await cmd_schedule(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.get_vpn_tunnels', side_effect=Exception("boom"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_vpn_error(self, mock_access, mock_catat, mock_vpn):
        from handlers.tools import cmd_vpn
        update = _make_update()
        context = MagicMock()

        await cmd_vpn(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "Gagal memuat status VPN" in update.effective_message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.get_vpn_tunnels', return_value=[
        {'name': 'vpn-a', 'type': 'l2tp', 'remote': '10.0.0.2', 'uptime': '', 'comment': '', 'running': False, 'disabled': True},
        {'name': 'vpn-b', 'type': 'ovpn', 'remote': '10.0.0.3', 'uptime': '1h', 'comment': 'branch', 'running': True, 'disabled': False},
    ])
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_vpn_callback_edit(self, mock_access, mock_catat, mock_vpn):
        from handlers.tools import cmd_vpn
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()

        await cmd_vpn(update, context)

        query.answer.assert_called_once()
        query.message.edit_text.assert_called_once()
        assert "vpn-b" in query.message.edit_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.get_vpn_tunnels', return_value={})
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_vpn_callback_empty_edit_error_is_suppressed(self, mock_access, mock_catat, mock_vpn, mock_logger):
        from handlers.tools import cmd_vpn
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()

        await cmd_vpn(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.get_vpn_tunnels', side_effect=Exception("boom"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_vpn_callback_error_edit_error_is_suppressed(self, mock_access, mock_catat, mock_vpn, mock_logger):
        from handlers.tools import cmd_vpn
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()

        await cmd_vpn(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.get_firewall_rules', return_value=[])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_firewall_callback_empty(self, mock_access, mock_rules):
        from handlers.tools import cmd_firewall
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_firewall(update, context)

        query.message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.get_firewall_rules', return_value=[])
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_firewall_callback_empty_edit_error_is_suppressed(self, mock_access, mock_rules, mock_logger):
        from handlers.tools import cmd_firewall
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_firewall(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.get_firewall_rules', side_effect=Exception("boom"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_firewall_error_reply(self, mock_access, mock_catat, mock_rules):
        from handlers.tools import cmd_firewall
        update = _make_update()
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_firewall(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "Gagal memuat firewall" in update.effective_message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_firewall_more_paths(self, mock_access):
        from handlers.tools import callback_firewall

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {
            'fw_filter': [{'id': '*1', 'disabled': False, 'comment': 'allow', 'action': 'accept', 'src_address': '', 'dst_address': '', 'protocol': 'tcp', 'dst_port': '80', 'bytes': '0', 'chain': 'filter'}]
        }

        query.data = "fwpage_filter_0"
        await callback_firewall(update, context)
        query.answer.assert_called()

        query.answer.reset_mock()
        query.data = "fwswitch_filter"
        with patch('handlers.tools.get_firewall_rules', side_effect=Exception("boom")):
            await callback_firewall(update, context)
        assert "Gagal memuat rule firewall" in query.edit_message_text.call_args.args[0]

        query.answer.reset_mock()
        query.data = "fwtoggle_filter_*404"
        await callback_firewall(update, context)
        query.answer.assert_called_with("Rule tidak ditemukan.", show_alert=True)

        query.answer.reset_mock()
        query.data = "fwexec_filter_*404"
        await callback_firewall(update, context)
        query.answer.assert_called_with("Rule tidak ditemukan.", show_alert=True)

        query.answer.reset_mock()
        query.data = "fwexec_invalid"
        await callback_firewall(update, context)
        query.answer.assert_called_with("Data tidak valid.", show_alert=True)

        query.answer.reset_mock()
        query.data = "fwexec_filter_*1"
        with patch('handlers.tools.toggle_firewall_rule', side_effect=Exception("boom")):
            await callback_firewall(update, context)
        assert "Gagal mengubah firewall rule" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_firewall_toggle_confirm_and_edit_error(self, mock_access):
        from handlers.tools import callback_firewall

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot_data = {
            'fw_filter': [{'id': '*1', 'disabled': False, 'comment': 'allow', 'action': 'accept', 'src_address': '', 'dst_address': '', 'protocol': 'tcp', 'dst_port': '80', 'bytes': '0', 'chain': 'filter'}]
        }

        with patch('handlers.tools.logger') as mock_logger:
            query.data = "fwtoggle_filter_*1"
            await callback_firewall(update, context)

        query.answer.assert_called()
        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.database.get_uptime_stats', return_value={
        'critical-host': {'uptime_pct': 94.5, 'incident_count': 2, 'total_downtime_str': '2h', 'total_downtime_sec': 7200},
        'warn-host': {'uptime_pct': 97.5, 'incident_count': 1, 'total_downtime_str': '1h', 'total_downtime_sec': 3600},
    })
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_uptime_callback_with_invalid_arg_defaults(self, mock_access, mock_catat, mock_stats):
        from handlers.tools import cmd_uptime
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = ["bad"]

        await cmd_uptime(update, context)

        query.answer.assert_called_once()
        query.message.edit_text.assert_called_once()
        text = query.message.edit_text.call_args.args[0]
        assert "warn-host" in text
        assert "critical-host" in text

    @pytest.mark.asyncio
    @patch('handlers.tools.database.get_uptime_stats', side_effect=Exception("boom"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_uptime_error_callback(self, mock_access, mock_catat, mock_stats):
        from handlers.tools import cmd_uptime
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []

        await cmd_uptime(update, context)

        assert "Gagal memuat laporan uptime" in query.message.edit_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('handlers.tools.database.get_uptime_stats', return_value={})
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_uptime_callback_empty_edit_error_is_suppressed(self, mock_access, mock_catat, mock_stats, mock_logger):
        from handlers.tools import cmd_uptime
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.args = []

        await cmd_uptime(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.cmd_uptime', new_callable=AsyncMock)
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_uptime_dispatches_days(self, mock_access, mock_cmd_uptime):
        from handlers.tools import callback_uptime

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "uptime_30"
        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_uptime(update, context)

        assert context.args == ["30"]
        mock_cmd_uptime.assert_awaited_once_with(update, context)

    @pytest.mark.asyncio
    @patch('handlers.tools.cmd_uptime', new_callable=AsyncMock)
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=True)
    async def test_callback_uptime_access_denied_returns_early(self, mock_access, mock_cmd_uptime):
        from handlers.tools import callback_uptime

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "uptime_30"
        update = MagicMock(callback_query=query)
        context = MagicMock()

        await callback_uptime(update, context)

        mock_cmd_uptime.assert_not_awaited()

    @pytest.mark.asyncio
    @patch('services.config_manager.get_all_configs', return_value={"Thresholds": [{"label": "CPU", "value": "90", "key": "CPU_THRESHOLD", "is_overridden": False}]})
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_config_callback_show(self, mock_access, mock_catat, mock_cfg):
        from handlers.tools import cmd_config
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.args = []

        await cmd_config(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        assert "KONFIGURASI BOT" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('services.config_manager.set_config', return_value=(False, "invalid"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_config_set_callback_edit(self, mock_access, mock_catat, mock_set):
        from handlers.tools import cmd_config
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.args = ['set', 'CPU_THRESHOLD', '101']

        await cmd_config(update, context)

        query.edit_message_text.assert_called_once()
        assert "CONFIG SET" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('services.config_manager.reset_config', return_value=(False, "missing"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_config_reset_callback_edit(self, mock_access, mock_catat, mock_reset):
        from handlers.tools import cmd_config
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.args = ['reset', 'CPU_THRESHOLD']

        await cmd_config(update, context)

        query.edit_message_text.assert_called_once()
        assert "CONFIG RESET" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('services.config_manager.get_all_configs', return_value={"Thresholds": [{"label": "CPU", "value": "90", "key": "CPU_THRESHOLD", "is_overridden": False}]})
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_config_callback_show_edit_error_is_suppressed(self, mock_access, mock_catat, mock_cfg, mock_logger):
        from handlers.tools import cmd_config
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.args = []

        await cmd_config(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('services.config_manager.set_config', return_value=(False, "invalid"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_config_set_callback_edit_error_is_suppressed(self, mock_access, mock_catat, mock_set, mock_logger):
        from handlers.tools import cmd_config
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.args = ['set', 'CPU_THRESHOLD', '101']

        await cmd_config(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.tools.logger')
    @patch('services.config_manager.reset_config', return_value=(False, "missing"))
    @patch('handlers.tools.catat')
    @patch('handlers.tools._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_config_reset_callback_edit_error_is_suppressed(self, mock_access, mock_catat, mock_reset, mock_logger):
        from handlers.tools import cmd_config
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.args = ['reset', 'CPU_THRESHOLD']

        await cmd_config(update, context)

        mock_logger.debug.assert_called_once()
