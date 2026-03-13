import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from mikrotik import get_simple_queues, remove_simple_queue
from core.logger import catat
from .utils import _check_access, get_back_button, append_back_button, escape_html, generic_error_html, with_menu_timestamp

logger = logging.getLogger(__name__)

async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /queue - List simple queue dengan tombol interaktif."""
    user = update.effective_user
    if await _check_access(update, user, "/queue"):
        return

    # Jika dipanggil dari callback (tombol kembali/navigasi)
    if update.callback_query:
        message = update.callback_query.message
        page = 0
    else:
        message = update.message
        page = 0

    try:
        import asyncio
        queues = await asyncio.to_thread(get_simple_queues)
        if not queues:
            text = with_menu_timestamp("ℹ️ Tidak ada simple queue aktif.")
            if update.callback_query:
                await message.edit_text(text, parse_mode='HTML')
            else:
                await message.reply_text(text, parse_mode='HTML')
            return

        # Tampilkan Halaman 0
        reply_markup = _get_queue_keyboard(queues, page=0)
        text = with_menu_timestamp(f"⏳ <b>DAFTAR LIMIT BANDWIDTH</b>\n<i>Total Queue: {len(queues)} item</i>\n\nSilakan pilih pengguna untuk melihat detail:")
        
        catat(user.id, user.username, "/queue", "berhasil")
        if update.callback_query:
            try:
                await update.callback_query.answer()
                await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
                return
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        
        await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))

    except Exception as e:
        catat(user.id, user.username, "/queue", f"gagal: {e}")
        if update.callback_query:
            await update.callback_query.answer()
            
        await update.effective_message.reply_text(
            generic_error_html("Gagal memuat daftar queue"),
            parse_mode='HTML',
            reply_markup=get_back_button()
        )




def _get_queue_keyboard(queues, page=0, per_page=10):
    """Helper membuat keyboard pagination untuk queue."""
    total = len(queues)
    total_pages = (total + per_page - 1) // per_page
    if total_pages == 0: total_pages = 1
    
    start = page * per_page
    end = start + per_page
    current_items = queues[start:end]
    
    keyboard = []
    
    for q in current_items:
        # cari ID, fallback ke .id
        qid = q.get('id') or q.get('.id')
        btn = InlineKeyboardButton(f"👤 {q.get('name', 'Unknown')}", callback_data=f"q_view|{qid}")
        keyboard.append([btn])
    
    # Navigation buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"q_list|{page-1}"))
    
    # Indikator halaman (non-clickable)
    nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"q_list|{page+1}"))
        
    keyboard.append(nav_row)
    
    return InlineKeyboardMarkup(keyboard)


async def callback_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback interaktif queue (List, View, Del)."""
    query = update.callback_query
    user = query.from_user
    
    if await _check_access(update, user, "callback_queue"):
        return

    await query.answer()
    data = query.data.split("|")
    action = data[0]
    
    try:
        if action == "q_list":
            page = int(data[1])
            import asyncio
            queues = await asyncio.to_thread(get_simple_queues)
            reply_markup = _get_queue_keyboard(queues, page=page)
            # When inside callback_queue (navigating pages) we SHOULD edit the message, but we still append back button
            await query.edit_message_text(
                with_menu_timestamp(f"⏳ <b>DAFTAR LIMIT BANDWIDTH</b>\n<i>Total Queue: {len(queues)} item</i>\n\nSilakan pilih pengguna untuk melihat detail:"),
                parse_mode='HTML',
                reply_markup=append_back_button(reply_markup)
            )
            
        elif action == "q_view":
            queue_id = data[1]
            import asyncio
            queues = await asyncio.to_thread(get_simple_queues)
            
            # Cari queue by ID (baik 'id' maupun '.id')
            target_q = next((q for q in queues if str(q.get('id') or q.get('.id')) == queue_id), None)
            
            if not target_q:
                # Debugging log
                available_ids = [q.get('id') or q.get('.id') for q in queues]
                logger.warning(f"Queue ID '{queue_id}' not found. Available IDs: {available_ids}")
                await query.edit_message_text(
                    with_menu_timestamp(f"❌ Queue tidak ditemukan atau sudah dihapus.\nID: <code>{escape_html(queue_id)}</code>"),
                    parse_mode='HTML'
                )
                return

            text = (
                f"👤 <b>{target_q.get('name', 'Unknown')}</b>\n"
                f"🎯 Target: <code>{target_q.get('target', 'Unknown')}</code>\n"
                f"📶 Limit: <code>{target_q.get('max-limit', '0/0')}</code>\n"
                f"📝 Ket: {target_q.get('comment', '-')}\n"
            )
            text = with_menu_timestamp(text)
            
            # Tombol Hapus & Kembali
            qid = target_q.get('id') or target_q.get('.id')
            keyboard = [
                [InlineKeyboardButton("❌ Stop Limit (Hapus)", callback_data=f"q_del|{qid}")],
                [InlineKeyboardButton("🔙 Kembali ke List", callback_data="q_list|0")]
            ]
            await query.edit_message_text(text, reply_markup=append_back_button(InlineKeyboardMarkup(keyboard)), parse_mode='HTML')
            
        elif action == "q_del":
            queue_id = data[1]
            import asyncio
            queues = await asyncio.to_thread(get_simple_queues)
            target_q = next((q for q in queues if str(q.get('id') or q.get('.id')) == queue_id), None)
            if not target_q:
                await query.edit_message_text(
                    with_menu_timestamp("❌ Queue tidak ditemukan atau sudah dihapus."),
                    parse_mode='HTML',
                    reply_markup=get_back_button()
                )
                return

            queue_name = escape_html(target_q.get('name', queue_id))
            text = (
                "⚠️ <b>Konfirmasi Hapus Queue</b>\n\n"
                f"Queue: <b>{queue_name}</b>\n"
                f"ID: <code>{escape_html(queue_id)}</code>\n\n"
                "Aksi ini akan menghapus limit bandwidth dari router.\n"
                "Lanjutkan?"
            )
            text = with_menu_timestamp(text)
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Ya, hapus", callback_data=f"q_delexec|{queue_id}"),
                    InlineKeyboardButton("❌ Batal", callback_data="q_list|0"),
                ]
            ])
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(keyboard))

        elif action == "q_delexec":
            queue_id = data[1]
            import asyncio
            await asyncio.to_thread(remove_simple_queue, queue_id)
            
            # Balik ke list page 0 setelah hapus
            queues = await asyncio.to_thread(get_simple_queues)
            if not queues:
                await query.edit_message_text(
                    with_menu_timestamp("✅ Queue berhasil dihapus.\n\nℹ️ Tidak ada simple queue aktif."),
                    parse_mode='HTML',
                    reply_markup=get_back_button()
                )
            else:
                reply_markup = _get_queue_keyboard(queues, page=0)
                await query.edit_message_text(
                    with_menu_timestamp(f"✅ <i>Berhasil dihapus.</i>\n\n⏳ <b>DAFTAR LIMIT BANDWIDTH</b>\n<i>Total Queue: {len(queues)} item</i>\n\nSilakan pilih pengguna untuk melihat detail:"),
                    parse_mode='HTML',
                    reply_markup=append_back_button(reply_markup)
                )
            catat(user.id, user.username, f"del_queue {queue_id}", "berhasil")

        # Backward compatibility for old buttons if any (del_queue)
        elif action == "del_queue":
            queue_id = data[1]
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Ya, hapus", callback_data=f"q_delexec|{queue_id}"),
                    InlineKeyboardButton("❌ Batal", callback_data="q_list|0"),
                ]
            ])
            await query.edit_message_text(
                with_menu_timestamp("⚠️ Konfirmasi hapus queue lama.\nLanjutkan?"),
                reply_markup=append_back_button(keyboard)
            )
            
    except Exception as e:
        await query.edit_message_text(generic_error_html("Operasi queue gagal"), parse_mode='HTML', reply_markup=get_back_button())
        catat(user.id, user.username, "callback_queue", f"gagal: {e}")

