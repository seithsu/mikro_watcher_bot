# ============================================
# TEST_HANDLERS_NETWORK - Tests for handlers/network.py
# Interface, Traffic, Scan, DHCP, FreeIP, WOL
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


# ============ /interface ============

class TestInterfaceCommand:
    """Test /interface command."""

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_interfaces', return_value=[
        {'name': 'ether1', 'type': 'ether', 'running': 'true', 'disabled': 'false',
         'rx-byte': '123456789', 'tx-byte': '987654321'},
        {'name': 'bridge-local', 'type': 'bridge', 'running': 'true', 'disabled': 'false',
         'rx-byte': '0', 'tx-byte': '0'},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_interface_list(self, mock_access, mock_ifaces, mock_catat):
        from handlers.network import cmd_interface
        update = _make_update()
        context = MagicMock()
        await cmd_interface(update, context)
        assert update.effective_message.reply_text.called or update.effective_message.edit_text.called

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_interfaces', return_value=[])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_interface_empty(self, mock_access, mock_ifaces, mock_catat):
        from handlers.network import cmd_interface
        update = _make_update()
        context = MagicMock()
        await cmd_interface(update, context)
        assert update.effective_message.reply_text.called or update.effective_message.edit_text.called

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_interfaces', side_effect=Exception("API error"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_interface_error(self, mock_access, mock_ifaces, mock_catat):
        from handlers.network import cmd_interface
        update = _make_update()
        context = MagicMock()
        await cmd_interface(update, context)
        assert update.effective_message.reply_text.called or update.effective_message.edit_text.called

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=True)
    async def test_callback_ifacedetail_access_denied(self, mock_access):
        from handlers.network import callback_ifacedetail

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.from_user = user
        query.data = "ifacedetail_ether1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        update.effective_user = user
        context = MagicMock()

        await callback_ifacedetail(update, context)
        query.edit_message_text.assert_not_called()


# ============ /scan ============

class TestScanCommand:
    """Test /scan command."""

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_interfaces', return_value=[
        {'name': 'ether1', 'type': 'ether', 'running': 'true', 'disabled': 'false'},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_scan_shows_interface_menu(self, mock_access, mock_ifaces, mock_catat):
        from handlers.network import cmd_scan
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_scan(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.run_ip_scan', return_value=[
        {'address': '192.168.1.1', 'mac-address': 'AA:BB:CC:DD:EE:FF', 'host-name': 'router'},
        {'address': '192.168.1.10', 'mac-address': '11:22:33:44:55:66', 'host-name': 'PC01'},
    ])
    @patch('handlers.network.get_interfaces', return_value=[
        {'name': 'ether1', 'type': 'ether', 'running': 'true', 'disabled': 'false'},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_scan_with_results(self, mock_access, mock_ifaces, mock_scan, mock_catat):
        from handlers.network import _do_scan
        update = _make_update()
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        # This tests the internal _do_scan function
        await _do_scan(update, context, 'ether1')

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.run_ip_scan', side_effect=Exception("scan failed"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_scan_error_handled(self, mock_access, mock_scan, mock_catat):
        from handlers.network import _do_scan
        update = _make_update()
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        # Should not raise
        await _do_scan(update, context, 'ether1')


# ============ /dhcp ============

class TestDhcpCommand:
    """Test /dhcp command."""

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_dhcp_leases', return_value=[
        {'address': '192.168.1.100', 'mac-address': 'AA:BB:CC:DD:EE:01',
         'host-name': 'PC01', 'status': 'bound'},
        {'address': '192.168.1.101', 'mac-address': 'AA:BB:CC:DD:EE:02',
         'host-name': 'PC02', 'status': 'bound'},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dhcp_list(self, mock_access, mock_leases, mock_catat):
        from handlers.network import cmd_dhcp
        update = _make_update()
        context = MagicMock()
        await cmd_dhcp(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_dhcp_leases', return_value=[])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dhcp_empty(self, mock_access, mock_leases, mock_catat):
        from handlers.network import cmd_dhcp
        update = _make_update()
        context = MagicMock()
        await cmd_dhcp(update, context)
        update.effective_message.reply_text.assert_called()


# ============ /freeip ============

class TestFreeIpCommand:
    """Test /freeip command."""

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_ip_addresses', return_value=[
        {'address': '192.168.1.1/24', 'interface': 'ether1', 'network': '192.168.1.0'},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_freeip_shows_networks(self, mock_access, mock_ips, mock_catat):
        from handlers.network import cmd_freeip
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_freeip(update, context)
        update.effective_message.reply_text.assert_called()


# ============ /wol ============

class TestWolCommand:
    """Test /wol command."""

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_dhcp_leases', return_value=[
        {'address': '192.168.1.100', 'mac-address': 'AA:BB:CC:DD:EE:01',
         'host-name': 'PC-Server', 'status': 'waiting'},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_wol_shows_offline_devices(self, mock_access, mock_leases, mock_catat):
        from handlers.network import cmd_wol
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_wol(update, context)
        update.effective_message.reply_text.assert_called()


class TestNetworkFormattersAndCallbacks:
    def test_format_scan_page_with_and_without_token(self):
        from handlers.network import _format_scan_page

        devices = [
            {"ip": "192.168.3.10", "mac": "AA:BB:CC:00:00:01", "hostname": "SIMRS"},
            {"ip": "192.168.3.11", "mac": "AA:BB:CC:00:00:02", "hostname": ""},
        ]

        text_no_token, markup_no_token = _format_scan_page(devices, "bridge", page=0, interface_token=None, per_page=1)
        assert "IP Scan: bridge" in text_no_token
        assert markup_no_token.inline_keyboard[0][0].text == "🔄 Rescan"

        text_with_token, markup_with_token = _format_scan_page(devices, "bridge", page=1, interface_token="tok123", per_page=1)
        assert "Hal 2/2" in text_with_token
        assert "No-Name" in text_with_token
        nav_row = markup_with_token.inline_keyboard[0]
        assert any("Prev" in btn.text for btn in nav_row)

    def test_format_freeip_page_variants(self):
        from handlers.network import _format_freeip_page

        result_empty = {"free_count": 0, "free_ips": [], "total_hosts": 254, "used_count": 254}
        text_empty, markup_empty = _format_freeip_page("192.168.3.0/24", result_empty, page=0, network_token=None)
        assert "IP Pool sudah terpakai penuh" in text_empty
        assert markup_empty.inline_keyboard[0][0].text == "🔄 Rescan"

        result_many = {
            "free_count": 12,
            "free_ips": [f"192.168.3.{i}" for i in range(100, 112)],
            "total_hosts": 254,
            "used_count": 242,
        }
        text_many, markup_many = _format_freeip_page("192.168.3.0/24", result_many, page=1, limit=10, network_token="free123")
        assert "Hal 2/2" in text_many
        assert any("Prev" in btn.text for btn in markup_many.inline_keyboard[0])

    def test_format_dhcp_page_contains_static_dynamic_markers(self):
        from handlers.network import _format_dhcp_page

        leases = [
            {"address": "192.168.3.10", "mac": "AA:AA:AA:AA:AA:10", "host": "SIMRS", "dynamic": False, "comment": "server"},
            {"address": "192.168.3.20", "mac": "AA:AA:AA:AA:AA:20", "host": "AP1", "dynamic": True},
        ]
        text, markup = _format_dhcp_page(leases, page=0, per_page=1)

        assert "📌" in text or "🔄" in text
        assert "DHCP Clients" in text
        assert markup.inline_keyboard[-1][0].text == "🔄 Refresh"

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_scan_invalid_data(self, mock_access):
        from handlers.network import callback_scan

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.from_user = user
        query.data = "scpk_invalid"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        update.effective_user = user
        context = MagicMock()
        context.bot_data = {}

        await callback_scan(update, context)
        query.answer.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_dhcp_invalid_page(self, mock_access):
        from handlers.network import callback_dhcp

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.from_user = user
        query.data = "dhcp_page_invalid"
        query.answer = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        update.effective_user = user
        context = MagicMock()

        await callback_dhcp(update, context)
        query.answer.assert_called_once_with("Data tidak valid.")


class TestNetworkAdditionalPaths:
    @pytest.mark.asyncio
    @patch('handlers.network.get_callback_payload', return_value=None)
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_ifacedetail_token_expired(self, mock_access, mock_payload):
        from handlers.network import callback_ifacedetail
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "ifacedetailk_deadbeef"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        await callback_ifacedetail(update, context)
        query.answer.assert_any_call("Data kedaluwarsa. Buka ulang menu interface.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network.get_interfaces', return_value=[])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_ifacedetail_not_found(self, mock_access, mock_ifaces):
        from handlers.network import callback_ifacedetail
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "ifacedetail_etherX"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        await callback_ifacedetail(update, context)
        called = query.edit_message_text.call_args[0][0]
        assert "tidak ditemukan" in called

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_invalid_chars(self, mock_access):
        from handlers.network import cmd_traffic
        update = _make_update()
        context = MagicMock()
        context.args = ["bad!iface"]
        context.bot_data = {}

        await cmd_traffic(update, context)
        update.effective_message.reply_text.assert_called_once()
        assert "Karakter tidak valid" in update.effective_message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_expired_callback_token(self, mock_access):
        from handlers.network import cmd_traffic
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "traffick_deadbeef"
        query.answer = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        update.effective_user = user
        update.effective_message = MagicMock(reply_text=AsyncMock())
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        with patch('handlers.network.get_callback_payload', return_value=None):
            await cmd_traffic(update, context)

        query.answer.assert_called_once_with("Data kedaluwarsa. Buka ulang menu traffic.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network.get_interfaces', return_value=[])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_no_interface_found(self, mock_access, mock_ifaces):
        from handlers.network import cmd_traffic
        update = _make_update()
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_traffic', return_value={
        'name': 'ether1',
        'rx': '1 Mbps',
        'tx': '2 Mbps',
        'rx_bytes': 100,
        'tx_bytes': 200,
    })
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_callback_not_modified(self, mock_access, mock_traffic, mock_catat):
        from handlers.network import cmd_traffic
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "traffic_ether1"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("Message is not modified"))
        update = MagicMock()
        update.callback_query = query
        update.effective_user = user
        update.effective_message = query.message
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)

        query.message.edit_text.assert_called_once()
        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_scan_sck_expired(self, mock_access):
        from handlers.network import callback_scan
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "sck_deadbeef"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_callback_payload', return_value=None):
            await callback_scan(update, context)
        query.answer.assert_called_with("Data scan expired. Silakan pilih interface lagi.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_scan_not_modified_is_suppressed(self, mock_access):
        from handlers.network import callback_scan
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "scpk_token_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("Message is not modified"))
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with (
            patch('handlers.network.get_callback_payload', return_value="ether1"),
            patch('handlers.network.get_cache_if_fresh', return_value=[{"ip": "192.168.3.10", "mac": "AA", "hostname": "PC"}]),
        ):
            await callback_scan(update, context)

        query.answer.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_freeip_expired_paths(self, mock_access):
        from handlers.network import callback_freeip
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        query.data = "fipagek_token_0"
        with patch('handlers.network.get_callback_payload', return_value=None):
            await callback_freeip(update, context)
        query.answer.assert_called_with("Data waktu scan sudah kedaluwarsa. Silakan Rescan.", show_alert=True)

        query.answer.reset_mock()
        query.data = "freeipk_token"
        with patch('handlers.network.get_callback_payload', return_value=None):
            await callback_freeip(update, context)
        query.answer.assert_called_with("Data tidak valid/kedaluwarsa.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('mikrotik.find_free_ips', return_value={
        'free_count': 2,
        'free_ips': ['192.168.3.20', '192.168.3.21'],
        'total_hosts': 254,
        'used_count': 252,
    })
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_freeip_not_modified_shows_hint(self, mock_access, mock_find, mock_catat):
        from handlers.network import callback_freeip
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "freeipk_token"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("Message is not modified"))
        query.message.reply_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user, effective_message=query.message)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_callback_payload', return_value="192.168.3.0/24"):
            await callback_freeip(update, context)

        query.answer.assert_any_call()

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_dhcp_leases', return_value=[
        {'address': '192.168.1.100', 'mac': 'unknown', 'host': 'PC-Server'},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_wol_no_valid_mac(self, mock_access, mock_leases, mock_catat):
        from handlers.network import cmd_wol
        update = _make_update()
        context = MagicMock()
        context.args = []
        context.bot_data = {}
        await cmd_wol(update, context)
        assert update.effective_message.reply_text.called


class TestNetworkMoreBranches:
    @pytest.mark.asyncio
    @patch('handlers.network.put_callback_payload', side_effect=["tok1", "tok2"])
    @patch('handlers.network.get_interfaces', return_value=[
        {'name': 'ether1', 'type': 'ether', 'running': True, 'enabled': True},
        {'name': 'ether2', 'type': 'ether', 'running': False, 'enabled': False},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_interface_callback_edits_message(self, mock_access, mock_ifaces, mock_payload):
        from handlers.network import cmd_interface
        update = _make_update()
        user = update.effective_user
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = update.effective_message
        update.callback_query = query
        context = MagicMock()
        context.bot_data = {}

        await cmd_interface(update, context)

        query.answer.assert_called_once()
        update.effective_message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.put_callback_payload', side_effect=["tok1", "tok2"])
    @patch('handlers.network.get_interfaces', return_value=[
        {'name': 'ether1', 'type': 'ether', 'running': True, 'enabled': True},
        {'name': 'ether2', 'type': 'ether', 'running': False, 'enabled': False},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_interface_callback_falls_back_to_reply(self, mock_access, mock_ifaces, mock_payload):
        from handlers.network import cmd_interface
        update = _make_update()
        update.effective_message.edit_text = AsyncMock(side_effect=Exception("ui-fail"))
        user = update.effective_user
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = update.effective_message
        update.callback_query = query
        context = MagicMock()
        context.bot_data = {}

        await cmd_interface(update, context)

        update.effective_message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.put_callback_payload', side_effect=["tok-detail", "tok-traffic"])
    @patch('handlers.network.get_interfaces', return_value=[
        {
            'name': 'ether1',
            'type': 'ether',
            'running': True,
            'enabled': True,
            'mac-address': 'AA:BB:CC:DD:EE:FF',
            'actual-mtu': '1500',
            'rx_error': 1,
            'tx_error': 2,
            'rx_drop': 3,
            'tx_drop': 4,
            'comment': 'uplink',
        }
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_ifacedetail_success(self, mock_access, mock_ifaces, mock_payload):
        from handlers.network import callback_ifacedetail
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "ifacedetail_ether1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        await callback_ifacedetail(update, context)

        query.edit_message_text.assert_called_once()
        assert "INFO DEVICE" in query.edit_message_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network.get_interfaces', side_effect=Exception("router down"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_ifacedetail_error_path(self, mock_access, mock_ifaces):
        from handlers.network import callback_ifacedetail
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "ifacedetail_ether1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        await callback_ifacedetail(update, context)

        query.edit_message_text.assert_called_once()
        assert "Gagal ambil detail interface" in query.edit_message_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network.get_interfaces', return_value=[{'name': 'ether1'}])
    @patch('handlers.network.put_callback_payload', return_value='tok-traffic')
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_callback_menu_edit_success(self, mock_access, mock_payload, mock_ifaces):
        from handlers.network import cmd_traffic
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.data = "cmd_traffic"
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)

        query.answer.assert_called_once()
        query.message.edit_text.assert_called_once()
        message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.network.get_interfaces', side_effect=Exception("router down"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_menu_error_path(self, mock_access, mock_ifaces):
        from handlers.network import cmd_traffic
        update = _make_update()
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "Gagal mengambil daftar interface" in update.effective_message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network.get_traffic', return_value=None)
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_interface_not_found(self, mock_access, mock_traffic):
        from handlers.network import cmd_traffic
        update = _make_update()
        context = MagicMock()
        context.args = ["ether404"]
        context.bot_data = {}

        await cmd_traffic(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "tidak ditemukan" in update.effective_message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network.get_traffic', side_effect=Exception("api fail"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_callback_error_fallbacks_to_reply(self, mock_access, mock_traffic):
        from handlers.network import cmd_traffic
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.data = "traffic_ether1"
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)

        message.reply_text.assert_called_once()
        assert "Gagal ambil traffic ether1" in message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network._do_scan', new_callable=AsyncMock)
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_scan_invalid_chars(self, mock_access, mock_do_scan):
        from handlers.network import cmd_scan
        update = _make_update()
        context = MagicMock()
        context.args = ["bad!iface"]

        await cmd_scan(update, context)

        update.effective_message.reply_text.assert_called_once()
        mock_do_scan.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.network.get_interfaces', return_value=[])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_scan_empty_interface_list(self, mock_access, mock_ifaces):
        from handlers.network import cmd_scan
        update = _make_update()
        context = MagicMock()
        context.args = []

        await cmd_scan(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "Tidak ada interface ditemukan" in update.effective_message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network.get_interfaces', side_effect=Exception("router down"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_scan_menu_error(self, mock_access, mock_ifaces):
        from handlers.network import cmd_scan
        update = _make_update()
        context = MagicMock()
        context.args = []

        await cmd_scan(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "Gagal membuka menu scan" in update.effective_message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('mikrotik.run_ip_scan', return_value=[])
    async def test_do_scan_no_devices(self, mock_scan):
        from handlers.network import _do_scan
        update = _make_update()
        context = MagicMock()
        context.bot_data = {}

        await _do_scan(update, context, "ether1")

        update.effective_message.reply_text.assert_called_once()
        loading_message = update.effective_message.reply_text.return_value
        loading_message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('mikrotik.run_ip_scan', side_effect=Exception("socket 10038"))
    @patch('handlers.network.catat')
    async def test_do_scan_socket_error_message(self, mock_catat, mock_scan):
        from handlers.network import _do_scan
        update = _make_update()
        context = MagicMock()
        context.bot_data = {}

        await _do_scan(update, context, "ether1")

        loading_message = update.effective_message.reply_text.return_value
        loading_message.edit_text.assert_called_once()
        assert "sedang tidak aktif" in loading_message.edit_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_scan_legacy_page_expired(self, mock_access):
        from handlers.network import callback_scan
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "scp_ether1_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_cache_if_fresh', return_value=None):
            await callback_scan(update, context)

        query.answer.assert_called_with("Data scan expired. Silakan rescan.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_scan_raw_sc_triggers_do_scan(self, mock_access):
        from handlers.network import callback_scan
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "sc_ether1"
        query.answer = AsyncMock(side_effect=Exception("ignore"))
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network._do_scan', new=AsyncMock()) as mock_do_scan:
            await callback_scan(update, context)

        mock_do_scan.assert_awaited_once()

    @pytest.mark.asyncio
    @patch('handlers.network.get_ip_addresses', return_value=[])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_freeip_empty_subnet_list(self, mock_access, mock_ips):
        from handlers.network import cmd_freeip
        update = _make_update()
        context = MagicMock()
        context.bot_data = {}

        await cmd_freeip(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "Tidak ada subnet ditemukan" in update.effective_message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network.get_ip_addresses', side_effect=Exception("router down"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_freeip_menu_error(self, mock_access, mock_ips):
        from handlers.network import cmd_freeip
        update = _make_update()
        context = MagicMock()
        context.bot_data = {}

        await cmd_freeip(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "Gagal mengambil daftar IP" in update.effective_message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_freeip_invalid_page_token(self, mock_access):
        from handlers.network import callback_freeip
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "fipagek_token_bad"
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        await callback_freeip(update, context)

        query.answer.assert_called_with("Data tidak valid.")

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_freeip_legacy_page_expired(self, mock_access):
        from handlers.network import callback_freeip
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "fipage_192.168.3.0/24_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_cache_if_fresh', return_value=None):
            await callback_freeip(update, context)

        query.answer.assert_called_with("Data waktu scan sudah kedaluwarsa. Silakan Rescan.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_freeip_raw_path_uses_do_freeip(self, mock_access):
        from handlers.network import callback_freeip
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "freeip_192.168.3.0/24"
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network._do_freeip', new=AsyncMock()) as mock_do_freeip:
            await callback_freeip(update, context)

        mock_do_freeip.assert_awaited_once_with(update, context, "192.168.3.0/24")

    @pytest.mark.asyncio
    @patch('mikrotik.find_free_ips', return_value={
        'free_count': 1,
        'free_ips': ['192.168.3.20'],
        'total_hosts': 254,
        'used_count': 253,
    })
    @patch('handlers.network.catat')
    async def test_do_freeip_not_modified_shows_hint(self, mock_catat, mock_find):
        from handlers.network import _do_freeip
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("Message is not modified"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.bot_data = {}

        await _do_freeip(update, context, "192.168.3.0/24", network_token="tok")

        query.answer.assert_any_call()
        query.answer.assert_any_call("Hasil rescan masih sama!", show_alert=False)
        message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('mikrotik.find_free_ips', side_effect=Exception("router down"))
    @patch('handlers.network.catat')
    async def test_do_freeip_error_falls_back_to_reply(self, mock_catat, mock_find):
        from handlers.network import _do_freeip
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.bot_data = {}

        await _do_freeip(update, context, "192.168.3.0/24", network_token="tok")

        message.reply_text.assert_called_once()
        assert "Gagal analisis Free IP" in message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network.get_dhcp_leases', return_value=[])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dhcp_callback_empty_alert(self, mock_access, mock_leases):
        from handlers.network import cmd_dhcp
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        await cmd_dhcp(update, context)

        query.answer.assert_called_with("Tidak ada DHCP lease.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network.get_dhcp_leases', side_effect=Exception("router down"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dhcp_error_callback_and_reply(self, mock_access, mock_leases):
        from handlers.network import cmd_dhcp
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        await cmd_dhcp(update, context)

        query.answer.assert_called_with("Gagal mengambil data DHCP.", show_alert=True)
        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.get_dhcp_leases', return_value=[])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_dhcp_empty(self, mock_access, mock_leases):
        from handlers.network import callback_dhcp
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "dhcp_page_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()

        await callback_dhcp(update, context)

        query.answer.assert_called_with("Tidak ada DHCP lease.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network.get_dhcp_leases', side_effect=Exception("router down"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_dhcp_error(self, mock_access, mock_leases):
        from handlers.network import callback_dhcp
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "dhcp_page_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()

        await callback_dhcp(update, context)

        query.answer.assert_called_with("Gagal memuat halaman DHCP.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network.get_dhcp_leases', return_value=[])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_wol_callback_empty_uses_edit(self, mock_access, mock_leases):
        from handlers.network import cmd_wol
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.bot_data = {}

        await cmd_wol(update, context)

        message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.get_dhcp_leases', side_effect=Exception("router down"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_wol_error(self, mock_access, mock_leases):
        from handlers.network import cmd_wol
        update = _make_update()
        context = MagicMock()
        context.bot_data = {}

        await cmd_wol(update, context)

        update.effective_message.reply_text.assert_called_once()
        assert "Gagal menarik data WoL" in update.effective_message.reply_text.call_args[0][0]


class TestNetworkCoveragePush:
    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=True)
    async def test_cmd_interface_access_denied(self, mock_access):
        from handlers.network import cmd_interface
        update = _make_update()
        context = MagicMock()

        await cmd_interface(update, context)

        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.get_interfaces', side_effect=Exception("API error"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_interface_error_falls_back_to_reply_when_edit_fails(self, mock_access, mock_ifaces, mock_catat):
        from handlers.network import cmd_interface
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        await cmd_interface(update, context)

        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.get_interfaces', return_value=[{
        'name': 'ether1', 'running': True, 'enabled': True, 'type': 'ether',
        'mac-address': 'AA:BB:CC:DD:EE:FF', 'actual-mtu': '1500',
        'rx_error': 0, 'tx_error': 0, 'rx_drop': 0, 'tx_drop': 0,
    }])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_ifacedetail_not_modified_answers_hint(self, mock_access, mock_ifaces):
        from handlers.network import callback_ifacedetail
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "ifacedetail_ether1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("Message is not modified"))
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        await callback_ifacedetail(update, context)

        query.answer.assert_any_call("Info interface belum berubah", show_alert=False)

    @pytest.mark.asyncio
    @patch('handlers.network.logger')
    @patch('handlers.network.get_interfaces', side_effect=Exception("router down"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_ifacedetail_error_edit_failure_is_suppressed(self, mock_access, mock_ifaces, mock_logger):
        from handlers.network import callback_ifacedetail
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "ifacedetail_ether1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        await callback_ifacedetail(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=True)
    async def test_cmd_traffic_access_denied(self, mock_access):
        from handlers.network import cmd_traffic
        update = _make_update()
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)

        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.network.get_interfaces', return_value=[{'name': 'ether1'}])
    @patch('handlers.network.put_callback_payload', return_value='tok-traffic')
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_callback_menu_edit_error_falls_back_to_reply(self, mock_access, mock_payload, mock_ifaces):
        from handlers.network import cmd_traffic
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.data = "cmd_traffic"
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)

        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.put_callback_payload', return_value='tok-traffic')
    @patch('handlers.network.get_traffic', return_value={
        'name': 'ether1',
        'rx': '1 Mbps',
        'tx': '2 Mbps',
        'rx_bytes': 100,
        'tx_bytes': 200,
    })
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_callback_success_edit_error_falls_back_to_reply(self, mock_access, mock_traffic, mock_payload, mock_catat):
        from handlers.network import cmd_traffic
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.data = "traffic_ether1"
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)

        message.reply_text.assert_called_once()
        assert "TRAFFIC LIVE" in message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_scan_scp_success(self, mock_access):
        from handlers.network import callback_scan
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "scp_ether1_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_cache_if_fresh', return_value=[{"ip": "192.168.3.10", "mac": "AA", "hostname": "PC"}]), \
             patch('handlers.network.put_callback_payload', return_value="tok-scan"):
            await callback_scan(update, context)

        query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.logger')
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_scan_sck_answer_error_is_suppressed(self, mock_access, mock_logger):
        from handlers.network import callback_scan
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "sck_tok123"
        query.answer = AsyncMock(side_effect=Exception("ignore"))
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_callback_payload', return_value="ether1"), \
             patch('handlers.network._do_scan', new=AsyncMock()) as mock_do_scan:
            await callback_scan(update, context)

        mock_logger.debug.assert_called_once()
        mock_do_scan.assert_awaited_once_with(update, context, "ether1", interface_token="tok123")

    @pytest.mark.asyncio
    @patch('handlers.network.logger')
    @patch('handlers.network.get_ip_addresses', return_value=[
        {'address': '192.168.1.1/24', 'interface': 'ether1', 'network': '192.168.1.0'},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_freeip_callback_edit_error_falls_back_to_reply(self, mock_access, mock_ips, mock_logger):
        from handlers.network import cmd_freeip
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.bot_data = {}

        await cmd_freeip(update, context)

        mock_logger.debug.assert_called_once()
        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_freeip_pagek_success(self, mock_access):
        from handlers.network import callback_freeip
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "fipagek_tok_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_callback_payload', return_value="192.168.3.0/24"), \
             patch('handlers.network.get_cache_if_fresh', return_value={"free_count": 1, "free_ips": ["192.168.3.20"], "total_hosts": 254, "used_count": 253}):
            await callback_freeip(update, context)

        query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_freeip_legacy_success(self, mock_access):
        from handlers.network import callback_freeip
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "fipage_192.168.3.0/24_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_cache_if_fresh', return_value={"free_count": 1, "free_ips": ["192.168.3.20"], "total_hosts": 254, "used_count": 253}), \
             patch('handlers.network.put_callback_payload', return_value="tok-free"):
            await callback_freeip(update, context)

        query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.get_dhcp_leases', return_value=[
        {"address": "192.168.3.10", "mac": "AA:AA", "host": "SIMRS", "dynamic": False},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_dhcp_success(self, mock_access, mock_leases):
        from handlers.network import callback_dhcp
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "dhcp_page_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()

        await callback_dhcp(update, context)

        query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.logger')
    @patch('handlers.network.get_dhcp_leases', return_value=[
        {'address': '192.168.1.100', 'mac': 'AA:BB:CC:DD:EE:01', 'host': 'PC-Server', 'status': 'waiting'},
    ])
    @patch('handlers.network.catat')
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_wol_callback_edit_error_is_suppressed(self, mock_access, mock_catat, mock_leases, mock_logger):
        from handlers.network import cmd_wol
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.bot_data = {}

        await cmd_wol(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network.catat')
    @patch('handlers.network.put_callback_payload', return_value='tok-traffic')
    @patch('handlers.network.get_traffic', return_value={
        'name': 'ether1',
        'rx': '1 Mbps',
        'tx': '2 Mbps',
        'rx_bytes': 100,
        'tx_bytes': 200,
    })
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_callback_success_edit_path(self, mock_access, mock_traffic, mock_payload, mock_catat):
        from handlers.network import cmd_traffic
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.data = "traffic_ether1"
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)

        message.edit_text.assert_called_once()
        message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.network.get_traffic', side_effect=Exception("api fail"))
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_traffic_callback_error_edit_path(self, mock_access, mock_traffic):
        from handlers.network import cmd_traffic
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock()
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.data = "traffic_ether1"
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.args = []
        context.bot_data = {}

        await cmd_traffic(update, context)

        message.edit_text.assert_called_once()
        message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.network._do_scan', new_callable=AsyncMock)
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_scan_with_valid_arg_dispatches(self, mock_access, mock_do_scan):
        from handlers.network import cmd_scan
        update = _make_update()
        context = MagicMock()
        context.args = ["ether1"]

        await cmd_scan(update, context)

        mock_do_scan.assert_awaited_once_with(update, context, "ether1")

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_scan_callback_menu_edit_error_falls_back_to_reply(self, mock_access):
        from handlers.network import cmd_scan
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()
        context.args = []

        with patch('handlers.network.get_interfaces', return_value=[{'name': 'ether1'}]), \
             patch('handlers.network.put_callback_payload', return_value='tok-scan'):
            await cmd_scan(update, context)

        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_scan_scpk_invalid_page(self, mock_access):
        from handlers.network import callback_scan
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "scpk_tok_bad"
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        await callback_scan(update, context)

        query.answer.assert_called_with("Data tidak valid.")

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_scan_scpk_expired_interface(self, mock_access):
        from handlers.network import callback_scan
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "scpk_tok_0"
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_callback_payload', return_value=None):
            await callback_scan(update, context)

        query.answer.assert_called_with("Data scan expired. Silakan rescan.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_freeip_pagek_invalid_page_string(self, mock_access):
        from handlers.network import callback_freeip
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "fipagek_tok_bad"
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        await callback_freeip(update, context)

        query.answer.assert_called_with("Data tidak valid.")

    @pytest.mark.asyncio
    @patch('handlers.network.logger')
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_freeip_pagek_edit_error_is_suppressed(self, mock_access, mock_logger):
        from handlers.network import callback_freeip
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "fipagek_tok_0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("ui fail"))
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()
        context.bot_data = {}

        with patch('handlers.network.get_callback_payload', return_value="192.168.3.0/24"), \
             patch('handlers.network.get_cache_if_fresh', return_value={"free_count": 1, "free_ips": ["192.168.3.20"], "total_hosts": 254, "used_count": 253}):
            await callback_freeip(update, context)

        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=True)
    async def test_cmd_dhcp_access_denied(self, mock_access):
        from handlers.network import cmd_dhcp
        update = _make_update()
        context = MagicMock()

        await cmd_dhcp(update, context)

        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.network.get_dhcp_leases', return_value=[
        {"address": "192.168.3.10", "mac": "AA:AA", "host": "SIMRS", "dynamic": False},
    ])
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_dhcp_callback_success_edit_debug_fallback(self, mock_access, mock_leases):
        from handlers.network import cmd_dhcp
        user = MagicMock(id=12345, username="admin")
        message = MagicMock()
        message.edit_text = AsyncMock(side_effect=Exception("ui fail"))
        message.reply_text = AsyncMock()
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = message
        update = MagicMock(callback_query=query, effective_user=user, effective_message=message)
        context = MagicMock()

        await cmd_dhcp(update, context)

        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=True)
    async def test_callback_dhcp_access_denied(self, mock_access):
        from handlers.network import callback_dhcp
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "dhcp_page_0"
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=user)
        context = MagicMock()

        await callback_dhcp(update, context)

        query.answer.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.network._check_access', new_callable=AsyncMock, return_value=True)
    async def test_cmd_wol_access_denied(self, mock_access):
        from handlers.network import cmd_wol
        update = _make_update()
        context = MagicMock()
        context.bot_data = {}

        await cmd_wol(update, context)

        update.effective_message.reply_text.assert_not_called()
