# ============================================
# TEST_HANDLERS_CHARTS - Tests for handlers/charts.py
# Chart command and photo callbacks
# ============================================

import io
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


class TestCmdChart:
    """Test /chart command."""

    @pytest.mark.asyncio
    @patch('handlers.charts.catat')
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    async def test_chart_shows_menu(self, mock_access, mock_catat):
        from handlers.charts import cmd_chart
        update = _make_update()
        context = MagicMock()
        await cmd_chart(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=True)
    async def test_chart_access_denied(self, mock_access):
        from handlers.charts import cmd_chart
        update = _make_update()
        context = MagicMock()
        await cmd_chart(update, context)
        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.charts.catat')
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    async def test_chart_callback_edits_existing_message(self, mock_access, mock_catat):
        from handlers.charts import cmd_chart
        update = _make_update()
        user = update.effective_user
        query = MagicMock()
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = MagicMock()

        await cmd_chart(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()


class TestCallbackBackToChart:
    """Test back to chart navigation from photo."""

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    async def test_deletes_photo_and_sends_menu(self, mock_access):
        from handlers.charts import callback_back_to_chart

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.answer = AsyncMock()
        query.from_user = user
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.delete = AsyncMock()

        update = MagicMock()
        update.callback_query = query

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()

        await callback_back_to_chart(update, context)
        query.message.delete.assert_called()
        context.bot.send_message.assert_called()


class TestCallbackBackToStart:
    """Test back to start navigation from photo."""

    @pytest.mark.asyncio
    @patch('core.database.get_stats_today', return_value=0)
    @patch('handlers.utils.read_state_json', return_value={'kategori': '🟢 NORMAL'})
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    async def test_deletes_photo_and_sends_start(self, mock_access, mock_state, mock_db):
        from handlers.charts import callback_back_to_start

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.answer = AsyncMock()
        query.from_user = user
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.delete = AsyncMock()

        update = MagicMock()
        update.callback_query = query

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()

        await callback_back_to_start(update, context)
        query.message.delete.assert_called()
        context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=True)
    async def test_back_to_start_access_denied(self, mock_access):
        from handlers.charts import callback_back_to_start

        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.answer = AsyncMock()
        query.from_user = user
        query.message = MagicMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()

        await callback_back_to_start(update, context)
        context.bot.send_message.assert_not_called()


class TestChartCallbacks:
    def _make_query_update(self, data="chart_cpu_24"):
        user = MagicMock()
        user.id = 12345
        user.username = "admin"
        query = MagicMock()
        query.answer = AsyncMock()
        query.from_user = user
        query.data = data
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.delete = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_photo = AsyncMock()
        return update, context, query

    def test_get_chart_keyboard_contains_expected_buttons(self):
        from handlers.charts import _get_chart_keyboard
        kb = _get_chart_keyboard()
        assert len(kb) >= 4
        assert any("CPU" in b.text for b in kb[0])
        assert any("RAM" in b.text for b in kb[1])

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_chart_invalid_format(self, mock_access):
        from handlers.charts import callback_chart
        update, context, query = self._make_query_update(data="chart_invalid")

        await callback_chart(update, context)
        query.answer.assert_any_call("Format chart tidak dikenal.", show_alert=True)

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    @patch('services.chart_service.get_data_freshness', return_value=("baru saja", None))
    @patch('services.chart_service.generate_cpu_chart', return_value=(None, None))
    async def test_callback_chart_cpu_no_data(self, mock_chart, mock_fresh, mock_access):
        from handlers.charts import callback_chart
        update, context, query = self._make_query_update(data="chart_cpu_24")

        await callback_chart(update, context)
        assert query.edit_message_text.call_count >= 2  # loading + no-data
        context.bot.send_photo.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    @patch('services.chart_service.get_data_freshness', return_value=("baru saja", None))
    @patch('services.chart_service.generate_cpu_chart', return_value=(io.BytesIO(b"fakepng"), {'avg': 10.0, 'min': 5.0, 'max': 20.0, 'count': 10}))
    async def test_callback_chart_cpu_success_send_photo(self, mock_chart, mock_fresh, mock_access):
        from handlers.charts import callback_chart
        update, context, query = self._make_query_update(data="chart_cpu_6")

        await callback_chart(update, context)
        query.message.delete.assert_called()
        context.bot.send_photo.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    @patch('services.chart_service.get_data_freshness', return_value=("baru saja", None))
    @patch('services.chart_service.generate_traffic_chart', return_value=(None, None))
    async def test_callback_chart_traffic_calls_inject_live(self, mock_chart, mock_fresh, mock_access, monkeypatch):
        from handlers.charts import callback_chart
        inject = AsyncMock()
        monkeypatch.setattr("handlers.charts._inject_live_traffic_point", inject)

        update, context, query = self._make_query_update(data="chart_traffic_1")
        await callback_chart(update, context)

        inject.assert_awaited_once()
        assert query.edit_message_text.call_count >= 2

    @pytest.mark.asyncio
    async def test_inject_live_traffic_records_batch(self, monkeypatch):
        from handlers.charts import _inject_live_traffic_point

        monkeypatch.setattr('mikrotik.get_interfaces', lambda: [
            {'name': 'ether2', 'running': True},
            {'name': 'ether3', 'running': True},
        ])
        monkeypatch.setattr('mikrotik.get_traffic', lambda name: {'rx_bps': 1000, 'tx_bps': 500})
        rec = MagicMock()
        monkeypatch.setattr('core.database.record_metrics_batch', rec)
        monkeypatch.setattr('core.config.MONITOR_IGNORE_IFACE', [], raising=False)

        await _inject_live_traffic_point()
        rec.assert_called_once()

    @pytest.mark.asyncio
    async def test_inject_live_traffic_returns_when_no_interfaces(self, monkeypatch):
        from handlers.charts import _inject_live_traffic_point

        monkeypatch.setattr('mikrotik.get_interfaces', lambda: [])
        rec = MagicMock()
        monkeypatch.setattr('core.database.record_metrics_batch', rec)

        await _inject_live_traffic_point()
        rec.assert_not_called()

    @pytest.mark.asyncio
    async def test_inject_live_traffic_returns_when_all_ignored(self, monkeypatch):
        from handlers.charts import _inject_live_traffic_point

        monkeypatch.setattr('mikrotik.get_interfaces', lambda: [{'name': 'ether1', 'running': True}])
        monkeypatch.setattr('mikrotik.get_traffic', lambda name: {'rx_bps': 1, 'tx_bps': 2})
        monkeypatch.setattr('core.config.MONITOR_IGNORE_IFACE', ['ether1'], raising=False)
        rec = MagicMock()
        monkeypatch.setattr('core.database.record_metrics_batch', rec)

        await _inject_live_traffic_point()
        rec.assert_not_called()

    @pytest.mark.asyncio
    async def test_inject_live_traffic_ignores_exceptions_and_empty_traffic(self, monkeypatch):
        from handlers.charts import _inject_live_traffic_point

        monkeypatch.setattr('mikrotik.get_interfaces', lambda: [{'name': 'ether1', 'running': True}, {'name': 'ether2', 'running': True}])
        def fake_traffic(name):
            if name == 'ether1':
                raise RuntimeError("boom")
            return None
        monkeypatch.setattr('mikrotik.get_traffic', fake_traffic)
        monkeypatch.setattr('core.config.MONITOR_IGNORE_IFACE', [], raising=False)
        rec = MagicMock()
        monkeypatch.setattr('core.database.record_metrics_batch', rec)

        await _inject_live_traffic_point()
        rec.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    @patch('services.chart_service.get_data_freshness', return_value=("baru saja", None))
    @patch('services.chart_service.generate_ram_chart', return_value=(io.BytesIO(b"fakepng"), {'avg': 20.0, 'min': 10.0, 'max': 30.0, 'count': 5}))
    async def test_callback_chart_ram_invalid_hour_defaults_to_24(self, mock_chart, mock_fresh, mock_access):
        from handlers.charts import callback_chart
        update, context, query = self._make_query_update(data="chart_ram_x")

        await callback_chart(update, context)

        mock_chart.assert_called_once_with(24)
        context.bot.send_photo.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    @patch('services.chart_service.get_data_freshness', return_value=("baru saja", None))
    @patch('services.chart_service.generate_dhcp_chart', return_value=(io.BytesIO(b"fakepng"), {'avg': 40.0, 'min': 20.0, 'max': 60.0, 'count': 8}))
    async def test_callback_chart_dhcp_success(self, mock_chart, mock_fresh, mock_access):
        from handlers.charts import callback_chart
        update, context, query = self._make_query_update(data="chart_dhcp_6")

        await callback_chart(update, context)

        context.bot.send_photo.assert_called_once()
        assert "DHCP Pool Usage" in context.bot.send_photo.call_args.kwargs["caption"]

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    @patch('services.chart_service.get_data_freshness', return_value=("baru saja", None))
    @patch('services.chart_service.generate_traffic_chart', return_value=(io.BytesIO(b"fakepng"), {'ifaces': 'ether1', 'max_rx': 10, 'max_tx': 5, 'avg_rx': 3, 'avg_tx': 2, 'count': 9}))
    async def test_callback_chart_traffic_success_delete_error_suppressed(self, mock_chart, mock_fresh, mock_access, monkeypatch):
        from handlers.charts import callback_chart
        inject = AsyncMock()
        monkeypatch.setattr("handlers.charts._inject_live_traffic_point", inject)

        update, context, query = self._make_query_update(data="chart_traffic_6")
        query.message.delete = AsyncMock(side_effect=Exception("delete-fail"))

        await callback_chart(update, context)

        inject.assert_awaited_once()
        context.bot.send_photo.assert_called_once()
        assert "Traffic Jaringan" in context.bot.send_photo.call_args.kwargs["caption"]

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    @patch('services.chart_service.generate_cpu_chart', side_effect=RuntimeError("chart boom"))
    async def test_callback_chart_exception_shows_error_message(self, mock_chart, mock_access):
        from handlers.charts import callback_chart
        update, context, query = self._make_query_update(data="chart_cpu_24")

        await callback_chart(update, context)

        assert query.edit_message_text.call_count >= 2
        assert "Gagal generate chart" in query.edit_message_text.call_args_list[-1].args[0]

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    @patch('services.chart_service.generate_cpu_chart', side_effect=RuntimeError("chart boom"))
    async def test_callback_chart_exception_edit_error_suppressed(self, mock_chart, mock_access):
        from handlers.charts import callback_chart
        update, context, query = self._make_query_update(data="chart_cpu_24")
        query.edit_message_text = AsyncMock(side_effect=[None, Exception("ui boom")])

        await callback_chart(update, context)

        assert query.edit_message_text.await_count == 2

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    async def test_back_to_chart_delete_error_still_sends_menu(self, mock_access):
        from handlers.charts import callback_back_to_chart

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.answer = AsyncMock()
        query.from_user = user
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.delete = AsyncMock(side_effect=Exception("delete-fail"))
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()

        await callback_back_to_chart(update, context)

        context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.charts._check_access', new_callable=AsyncMock, return_value=False)
    async def test_back_to_start_delete_error_still_sends_menu(self, mock_access):
        from handlers.charts import callback_back_to_start

        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.answer = AsyncMock()
        query.from_user = user
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.message.delete = AsyncMock(side_effect=Exception("delete-fail"))
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch('handlers.general._build_home_menu', new=AsyncMock(return_value=("home", MagicMock()))):
            await callback_back_to_start(update, context)

        context.bot.send_message.assert_called_once()
