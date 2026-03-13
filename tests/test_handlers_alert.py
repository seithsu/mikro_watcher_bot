# ============================================
# TEST_HANDLERS_ALERT - Tests for handlers/alert.py
# Mute, unmute, acknowledge handlers
# ============================================

import os
import time
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _make_update(user_id=12345, username="admin", is_callback=False):
    """Helper to create mock Update object."""
    user = MagicMock()
    user.id = user_id
    user.username = username

    message = MagicMock()
    message.chat = MagicMock()
    message.chat.id = user_id
    message.reply_text = AsyncMock()
    message.edit_text = AsyncMock()

    update = MagicMock()
    update.effective_user = user
    update.effective_message = message

    if is_callback:
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.message = message
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        update.message = None
    else:
        update.message = message
        update.callback_query = None

    return update


class TestCmdMute:
    """Test /mute command."""

    @pytest.mark.asyncio
    @patch('handlers.alert.catat')
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mute_creates_lock(self, mock_access, mock_catat, tmp_path, monkeypatch):
        import handlers.alert as alert_module
        mute_file = tmp_path / "mute.lock"
        monkeypatch.setattr(alert_module, '_MUTE_FILE', mute_file)

        update = _make_update()
        context = MagicMock()
        context.args = ['30']

        await alert_module.cmd_mute(update, context)
        assert mute_file.exists()

    @pytest.mark.asyncio
    @patch('handlers.alert.catat')
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mute_default_60min(self, mock_access, mock_catat, tmp_path, monkeypatch):
        import handlers.alert as alert_module
        mute_file = tmp_path / "mute.lock"
        monkeypatch.setattr(alert_module, '_MUTE_FILE', mute_file)

        update = _make_update()
        context = MagicMock()
        context.args = []

        await alert_module.cmd_mute(update, context)
        call_text = update.effective_message.reply_text.call_args[0][0]
        assert '60 menit' in call_text

    @pytest.mark.asyncio
    @patch('handlers.alert.catat')
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_mute_callback_edit_path(self, mock_access, mock_catat, tmp_path, monkeypatch):
        import handlers.alert as alert_module
        mute_file = tmp_path / "mute.lock"
        monkeypatch.setattr(alert_module, '_MUTE_FILE', mute_file)

        update = _make_update(is_callback=True)
        context = MagicMock()
        context.args = ['15']

        await alert_module.cmd_mute(update, context)
        update.callback_query.answer.assert_called()
        update.callback_query.message.edit_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=True)
    async def test_mute_access_denied(self, mock_access):
        from handlers.alert import cmd_mute
        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_mute(update, context)
        # Access denied — _check_access returns True meaning blocked
        update.effective_message.reply_text.assert_not_called()


class TestCmdUnmute:
    """Test /unmute command."""

    @pytest.mark.asyncio
    @patch('handlers.alert.catat')
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_unmute_removes_lock(self, mock_access, mock_catat, tmp_path, monkeypatch):
        import handlers.alert as alert_module
        mute_file = tmp_path / "mute.lock"
        monkeypatch.setattr(alert_module, '_MUTE_FILE', mute_file)
        mute_file.write_text(str(time.time() + 3600))

        update = _make_update()
        context = MagicMock()
        await alert_module.cmd_unmute(update, context)
        assert not mute_file.exists()

    @pytest.mark.asyncio
    @patch('handlers.alert.catat')
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_unmute_no_lock(self, mock_access, mock_catat, tmp_path, monkeypatch):
        import handlers.alert as alert_module
        mute_file = tmp_path / "mute.lock"
        monkeypatch.setattr(alert_module, '_MUTE_FILE', mute_file)

        update = _make_update()
        context = MagicMock()
        await alert_module.cmd_unmute(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.alert.catat')
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_unmute_callback_falls_back_to_reply(self, mock_access, mock_catat, tmp_path, monkeypatch):
        import handlers.alert as alert_module
        mute_file = tmp_path / "mute.lock"
        monkeypatch.setattr(alert_module, '_MUTE_FILE', mute_file)
        mute_file.write_text(str(time.time() + 3600))

        update = _make_update(is_callback=True)
        update.callback_query.message.edit_text = AsyncMock(side_effect=Exception("boom"))
        context = MagicMock()
        await alert_module.cmd_unmute(update, context)
        update.callback_query.message.reply_text.assert_called()


class TestMuteConfirm:
    @pytest.mark.asyncio
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_mute_1h_callback_renders_confirmation(self, mock_access):
        from handlers.alert import cmd_mute_1h
        update = _make_update(is_callback=True)
        context = MagicMock()

        await cmd_mute_1h(update, context)

        rendered = update.callback_query.message.edit_text.call_args.args[0]
        assert "Konfirmasi Mute Alarm" in rendered

    @pytest.mark.asyncio
    @patch('handlers.alert.cmd_mute', new_callable=AsyncMock)
    async def test_callback_confirm_mute_1h_sets_args_and_delegates(self, mock_cmd_mute):
        from handlers.alert import callback_confirm_mute_1h
        update = _make_update(is_callback=True)
        context = MagicMock()
        context.args = []

        await callback_confirm_mute_1h(update, context)

        assert context.args == ['60']
        mock_cmd_mute.assert_awaited_once()


class TestCmdAck:
    """Test /ack command."""

    @pytest.mark.asyncio
    @patch('handlers.alert.catat')
    @patch('monitor.alerts.acknowledge_alert', return_value=3)
    @patch('monitor.alerts.get_pending_alerts', return_value=[
        {'key': 'k1', 'severity': 'CRITICAL', 'message': 'test', 'escalated': 0}
    ])
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_ack_with_pending(self, mock_access, mock_pending, mock_ack, mock_catat):
        from handlers.alert import cmd_ack

        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_ack(update, context)
        mock_ack.assert_called_once()

    @pytest.mark.asyncio
    @patch('monitor.alerts.get_pending_alerts', return_value=[])
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_ack_no_pending(self, mock_access, mock_pending):
        from handlers.alert import cmd_ack

        update = _make_update()
        context = MagicMock()
        context.args = []
        await cmd_ack(update, context)
        update.message.reply_text.assert_called()
        call_text = update.message.reply_text.call_args[0][0]
        assert 'Tidak ada' in call_text or 'pending' in call_text

    @pytest.mark.asyncio
    @patch('handlers.alert.catat')
    @patch('monitor.alerts.acknowledge_alert', return_value=2)
    @patch('monitor.alerts.get_pending_alerts', return_value=[
        {'key': 'down_192.168.3.1', 'severity': 'CRITICAL', 'message': 'router', 'time': '10:00:00', 'escalated': 0},
        {'key': 'down_192.168.3.2', 'severity': 'CRITICAL', 'message': 'server', 'time': '10:01:00', 'escalated': 0},
    ])
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_ack_callback_edits_message(self, mock_access, mock_pending, mock_ack, mock_catat):
        from handlers.alert import cmd_ack

        update = _make_update(is_callback=True)
        context = MagicMock()
        context.args = []
        await cmd_ack(update, context)

        update.callback_query.edit_message_text.assert_called()
        assert "ALERT ACKNOWLEDGED" in update.callback_query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    @patch('monitor.alerts.get_pending_alerts', return_value=[])
    @patch('handlers.alert._check_access', new_callable=AsyncMock, return_value=False)
    async def test_ack_callback_reply_fallback_when_edit_fails(self, mock_access, mock_pending):
        from handlers.alert import cmd_ack

        update = _make_update(is_callback=True)
        update.callback_query.edit_message_text = AsyncMock(side_effect=Exception("boom"))
        context = MagicMock()
        context.args = []
        await cmd_ack(update, context)

        update.callback_query.message.reply_text.assert_called()
