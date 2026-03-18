# ============================================
# TEST_HANDLERS_REPORT - Tests for handlers/report.py
# Report generation and bandwidth display
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
    update = MagicMock()
    update.effective_user = user
    update.effective_message = message
    update.message = message
    update.callback_query = None
    return update


class TestCmdReport:
    """Test /report command (tanpa args → tampilkan menu)."""

    @pytest.mark.asyncio
    @patch('handlers.report.catat')
    @patch('handlers.report._check_access', new_callable=AsyncMock, return_value=False)
    async def test_report_shows_menu(self, mock_access, mock_catat):
        from handlers.report import cmd_report
        update = _make_update()
        context = MagicMock()
        context.args = []  # No args → show period selection menu
        await cmd_report(update, context)
        update.effective_message.reply_text.assert_called()
        call_text = update.effective_message.reply_text.call_args[0][0]
        assert 'LAPORAN' in call_text


class TestCmdBandwidth:
    """Test /bandwidth command."""

    @pytest.mark.asyncio
    @patch('handlers.report.catat')
    @patch('handlers.report.get_top_queues')
    @patch('handlers.report._check_access', new_callable=AsyncMock, return_value=False)
    async def test_bandwidth_shows_data(self, mock_access, mock_top, mock_catat):
        from handlers.report import cmd_bandwidth

        mock_top.return_value = [
            {
                '.id': '*1',
                'name': 'limit-PC01',
                'target': '192.168.1.10/32',
                'rx_rate': 5_000_000,
                'tx_rate': 10_000_000,
                'total_rate': 15_000_000,
                'rx_rate_fmt': '5.00 Mbps',
                'tx_rate_fmt': '10.0 Mbps',
                'total_rate_fmt': '15.0 Mbps',
            },
        ]

        update = _make_update()
        context = MagicMock()
        await cmd_bandwidth(update, context)
        update.effective_message.reply_text.assert_called()
        sent_text = update.effective_message.reply_text.call_args[0][0]
        assert '5.00 Mbps' in sent_text
        assert '10.0 Mbps' in sent_text
        assert '15.0 Mbps' in sent_text

    @pytest.mark.asyncio
    @patch('handlers.report.catat')
    @patch('handlers.report.get_top_queues')
    @patch('handlers.report._check_access', new_callable=AsyncMock, return_value=False)
    async def test_bandwidth_empty(self, mock_access, mock_top, mock_catat):
        from handlers.report import cmd_bandwidth
        mock_top.return_value = []

        update = _make_update()
        context = MagicMock()
        await cmd_bandwidth(update, context)
        update.effective_message.reply_text.assert_called()


class TestCallbackReport:
    """Test callback report access and routing."""

    @pytest.mark.asyncio
    @patch('handlers.report._send_report', new_callable=AsyncMock)
    @patch('handlers.report._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_report_allowed(self, mock_access, mock_send_report):
        from handlers.report import callback_report

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.data = "report_7_server"
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        await callback_report(update, context)
        mock_send_report.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.report._send_report', new_callable=AsyncMock)
    @patch('handlers.report._check_access', new_callable=AsyncMock, return_value=True)
    async def test_callback_report_access_denied(self, mock_access, mock_send_report):
        from handlers.report import callback_report

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.data = "report_7"
        query.from_user = user
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        await callback_report(update, context)
        mock_send_report.assert_not_called()


class TestReportHelpers:
    def test_fmt_dur_variants(self):
        from handlers.report import _fmt_dur
        assert _fmt_dur(0) == "0s"
        assert _fmt_dur(59) == "59s"
        assert _fmt_dur(120) == "2m 0s"
        assert _fmt_dur(3661) == "1j 1m 1s"

    @pytest.mark.asyncio
    @patch('handlers.report.database.get_metrics_summary', side_effect=[
        {'avg': 20, 'max': 40},
        {'avg': 35.2, 'max': 70.1},
    ])
    @patch('handlers.report.database.get_uptime_stats', return_value={
        'simrs': {'uptime_pct': 99.5, 'total_downtime_str': '5m'},
    })
    @patch('handlers.report.database.get_report', return_value={
        'mttr_seconds': 90,
        'total_incidents': 4,
        'hosts': [{'host': 'simrs', 'count': 2, 'total_down_sec': 120, 'avg_down_sec': 60}],
        'tags': [{'tag': 'server', 'count': 2}],
    })
    async def test_send_report_formats_output(self, mock_report, mock_uptime, mock_metrics):
        from handlers.report import _send_report

        update = _make_update()
        context = MagicMock()
        await _send_report(update, context, 7)
        update.effective_message.reply_text.assert_called_once()
        sent_text = update.effective_message.reply_text.call_args[0][0]
        assert "LAPORAN INSIDEN" in sent_text
        assert "UPTIME RANKING" in sent_text

    @pytest.mark.asyncio
    @patch('handlers.report.database.get_metrics_summary', return_value=None)
    @patch('handlers.report.database.get_uptime_stats', return_value={})
    @patch('handlers.report.database.get_report', return_value={
        'mttr_seconds': 5,
        'total_incidents': 0,
        'hosts': [],
        'tags': [],
    })
    async def test_send_report_callback_fallback_to_reply(self, mock_report, mock_uptime, mock_metrics):
        from handlers.report import _send_report

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=Exception("edit-fail"))
        query.message.reply_text = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        update.effective_message = query.message
        context = MagicMock()

        await _send_report(update, context, 7, "server")
        query.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.report._send_report', new_callable=AsyncMock)
    @patch('handlers.report._check_access', new_callable=AsyncMock, return_value=False)
    async def test_cmd_report_direct_days_arg(self, mock_access, mock_send):
        from handlers.report import cmd_report
        update = _make_update()
        context = MagicMock()
        context.args = ['30']
        await cmd_report(update, context)
        mock_send.assert_called_once()
