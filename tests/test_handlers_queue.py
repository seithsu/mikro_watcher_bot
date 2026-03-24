# ============================================
# TEST_HANDLERS_QUEUE - Tests for handlers/queue.py
# Queue listing, top, and callbacks
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


class TestCmdQueue:
    """Test /queue command."""

    @pytest.mark.asyncio
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=True)
    async def test_queue_access_denied_short_circuit(self, mock_access):
        from handlers.queue import cmd_queue

        update = _make_update()
        context = MagicMock()

        await cmd_queue(update, context)

        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.queue.catat')
    @patch('handlers.queue.get_simple_queues')
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_queue_with_data(self, mock_access, mock_queues, mock_catat):
        from handlers.queue import cmd_queue

        mock_queues.return_value = [
            {'.id': '*1', 'name': 'limit-PC01', 'target': '192.168.1.10/32',
             'max-limit': '10M/5M', 'disabled': 'false'},
        ]

        update = _make_update()
        context = MagicMock()
        await cmd_queue(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.queue.get_simple_queues', return_value=[])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_queue_empty_via_callback_edits_message(self, mock_access, mock_queues):
        from handlers.queue import cmd_queue

        update = _make_update()
        query = MagicMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update.callback_query = query
        context = MagicMock()

        await cmd_queue(update, context)

        query.message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.queue.catat')
    @patch('handlers.queue.get_simple_queues', return_value=[{'.id': '*1', 'name': 'limit-PC01'}])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_queue_callback_prefers_edit_message(self, mock_access, mock_queues, mock_catat):
        from handlers.queue import cmd_queue

        update = _make_update()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock()
        update.callback_query = query
        context = MagicMock()

        await cmd_queue(update, context)

        query.answer.assert_called_once()
        query.message.edit_text.assert_called_once()
        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.queue.catat')
    @patch('handlers.queue.get_simple_queues', return_value=[{'.id': '*1', 'name': 'limit-PC01'}])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_queue_callback_edit_failure_falls_back_to_reply(self, mock_access, mock_queues, mock_catat):
        from handlers.queue import cmd_queue

        update = _make_update()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_text = AsyncMock(side_effect=RuntimeError("ui-fail"))
        update.callback_query = query
        context = MagicMock()

        await cmd_queue(update, context)

        update.effective_message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch('handlers.queue.catat')
    @patch('handlers.queue.get_simple_queues', side_effect=RuntimeError("load-fail"))
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_queue_error_callback_answers_then_replies(self, mock_access, mock_queues, mock_catat):
        from handlers.queue import cmd_queue

        update = _make_update()
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = MagicMock()
        update.callback_query = query

        await cmd_queue(update, MagicMock())

        query.answer.assert_called_once()
        update.effective_message.reply_text.assert_called_once()


class TestQueueCallbacks:
    @pytest.mark.asyncio
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=True)
    async def test_callback_access_denied_short_circuit(self, mock_access):
        from handlers.queue import callback_queue
        query = MagicMock()
        query.from_user = MagicMock(id=12345, username="admin")
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query)

        await callback_queue(update, MagicMock())

        query.answer.assert_not_called()

    @pytest.mark.asyncio
    @patch('handlers.queue.get_simple_queues', return_value=[
        {'.id': '*1', 'name': 'user-1', 'target': '192.168.3.10/32', 'max-limit': '10M/10M', 'comment': 'test'},
    ])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_q_list_callback(self, mock_access, mock_q):
        from handlers.queue import callback_queue
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "q_list|0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        await callback_queue(update, context)
        query.edit_message_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.queue.get_simple_queues', return_value=[])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_q_view_not_found(self, mock_access, mock_q):
        from handlers.queue import callback_queue
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "q_view|*99"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        await callback_queue(update, context)
        called_text = query.edit_message_text.call_args[0][0]
        assert "Queue tidak ditemukan" in called_text

    @pytest.mark.asyncio
    @patch('handlers.queue.get_simple_queues', return_value=[
        {'.id': '*1', 'name': 'user-1', 'target': '192.168.3.10/32', 'max-limit': '10M/10M', 'comment': 'test'},
    ])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_q_view_found(self, mock_access, mock_q):
        from handlers.queue import callback_queue
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "q_view|*1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)

        await callback_queue(update, MagicMock())

        called_text = query.edit_message_text.call_args[0][0]
        assert "user-1" in called_text
        assert "192.168.3.10/32" in called_text

    @pytest.mark.asyncio
    @patch('handlers.queue.get_simple_queues', return_value=[
        {'.id': '*1', 'name': 'user-1', 'target': '192.168.3.10/32', 'max-limit': '10M/10M', 'comment': 'test'},
    ])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_q_del_confirmation(self, mock_access, mock_q):
        from handlers.queue import callback_queue
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "q_del|*1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        await callback_queue(update, context)
        called_text = query.edit_message_text.call_args[0][0]
        assert "Konfirmasi Hapus Queue" in called_text

    @pytest.mark.asyncio
    @patch('handlers.queue.get_simple_queues', return_value=[])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_q_del_not_found(self, mock_access, mock_q):
        from handlers.queue import callback_queue
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "q_del|*99"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)

        await callback_queue(update, MagicMock())

        called_text = query.edit_message_text.call_args[0][0]
        assert "Queue tidak ditemukan" in called_text

    @pytest.mark.asyncio
    @patch('handlers.queue.catat')
    @patch('handlers.queue.remove_simple_queue')
    @patch('handlers.queue.get_simple_queues', return_value=[])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_q_delexec(self, mock_access, mock_q, mock_remove, mock_catat):
        from handlers.queue import callback_queue
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "q_delexec|*1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)
        context = MagicMock()
        await callback_queue(update, context)
        mock_remove.assert_called_once_with('*1')
        query.edit_message_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.queue.catat')
    @patch('handlers.queue.remove_simple_queue')
    @patch('handlers.queue.get_simple_queues', return_value=[{'.id': '*2', 'name': 'user-2'}])
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_q_delexec_with_remaining_queues(self, mock_access, mock_q, mock_remove, mock_catat):
        from handlers.queue import callback_queue
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "q_delexec|*1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)

        await callback_queue(update, MagicMock())

        mock_remove.assert_called_once_with('*1')
        called_text = query.edit_message_text.call_args[0][0]
        assert "Berhasil dihapus" in called_text

    @pytest.mark.asyncio
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_del_queue_legacy_branch(self, mock_access):
        from handlers.queue import callback_queue
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "del_queue|*1"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)

        await callback_queue(update, MagicMock())

        called_text = query.edit_message_text.call_args[0][0]
        assert "Konfirmasi hapus queue lama" in called_text

    @pytest.mark.asyncio
    @patch('handlers.queue.catat')
    @patch('handlers.queue.get_simple_queues', side_effect=RuntimeError("boom"))
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_callback_exception_path(self, mock_access, mock_q, mock_catat):
        from handlers.queue import callback_queue
        user = MagicMock(id=12345, username="admin")
        query = MagicMock()
        query.from_user = user
        query.data = "q_list|0"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)

        await callback_queue(update, MagicMock())

        called_text = query.edit_message_text.call_args[0][0]
        assert "Operasi queue gagal" in called_text

    def test_get_queue_keyboard_has_nav(self):
        from handlers.queue import _get_queue_keyboard
        queues = [{'.id': f'*{i}', 'name': f'user-{i}'} for i in range(1, 13)]
        markup = _get_queue_keyboard(queues, page=1, per_page=10)
        nav_row = markup.inline_keyboard[-1]
        assert any("Prev" in btn.text for btn in nav_row)

    def test_get_queue_keyboard_empty_still_has_page_indicator(self):
        from handlers.queue import _get_queue_keyboard

        markup = _get_queue_keyboard([], page=0, per_page=10)

        assert markup.inline_keyboard[-1][0].text == "1/1"

    def test_get_queue_keyboard_has_next_button(self):
        from handlers.queue import _get_queue_keyboard

        queues = [{'.id': f'*{i}', 'name': f'user-{i}'} for i in range(1, 13)]
        markup = _get_queue_keyboard(queues, page=0, per_page=10)
        nav_row = markup.inline_keyboard[-1]

        assert any("Next" in btn.text for btn in nav_row)

    @pytest.mark.asyncio
    @patch('handlers.queue.catat')
    @patch('handlers.queue.get_simple_queues')
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_queue_empty(self, mock_access, mock_queues, mock_catat):
        from handlers.queue import cmd_queue
        mock_queues.return_value = []

        update = _make_update()
        context = MagicMock()
        await cmd_queue(update, context)
        update.effective_message.reply_text.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.queue.get_simple_queues', side_effect=Exception("fail"))
    @patch('handlers.queue._check_access', new_callable=AsyncMock, return_value=False)
    async def test_queue_error_handled(self, mock_access, mock_queues):
        from handlers.queue import cmd_queue

        update = _make_update()
        context = MagicMock()
        await cmd_queue(update, context)
        update.effective_message.reply_text.assert_called()


