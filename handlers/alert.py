import logging
import os
import time

from telegram import Update
from telegram.ext import ContextTypes

from core.logger import catat
from core.config import DATA_DIR
from .utils import _check_access, get_back_button

_MUTE_FILE = DATA_DIR / "mute.lock"

logger = logging.getLogger(__name__)


async def cmd_mute_1h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback khusus mute 1 jam dengan konfirmasi."""
    user = update.effective_user
    if await _check_access(update, user, "/mute_1h"): return

    pesan = "⚠️ <b>Konfirmasi Mute Alarm</b>\n\nAnda yakin ingin mematikan Notifikasi Alert selama <b>1 Jam</b> ke depan?"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = [
        [
            InlineKeyboardButton("✅ YAKIN", callback_data="confirm_mute_1h"),
            InlineKeyboardButton("❌ BATAL", callback_data="cmd_start")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.edit_text(pesan, parse_mode='HTML', reply_markup=reply_markup)
    else:
        await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=reply_markup)

async def callback_confirm_mute_1h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Eksekusi Mute 1 Jam setelah diconfirm."""
    context.args = ['60']
    await cmd_mute(update, context)


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /mute - Mencegah pesan Alert dari monitor selama interval tertentu."""
    user = update.effective_user
    if await _check_access(update, user, "/mute"): return
    
    minutes = 60
    if context.args:
        try:
            minutes = int(context.args[0])
        except ValueError:
            pass
            
    expiry = time.time() + (minutes * 60)
    
    def _write_lock():
        with open(_MUTE_FILE, "w") as f:
            f.write(str(expiry))
    
    import asyncio
    await asyncio.to_thread(_write_lock)
        
    pesan = f"🔇 <b>GLOBAL MUTE AKTIF</b>\n\nBot tidak akan mengirim Notifikasi Alert DOWN/UP maupun Anomaly DHCP selama <b>{minutes} menit</b> ke depan. Gunakan perintah ini saat sedang melakukan Maintenance Terencana.\n\nKetik /unmute untuk membatalkan."
    
    catat(user.id, user.username, f"/mute {minutes}", "berhasil")
    if update.callback_query:
        await update.callback_query.answer("Mute diaktifkan")
        try:
            await update.callback_query.message.edit_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
            return
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /unmute - Membatalkan Status Mute."""
    user = update.effective_user
    if await _check_access(update, user, "/unmute"): return
    
    def _remove_lock():
        if _MUTE_FILE.exists():
            _MUTE_FILE.unlink(missing_ok=True)
            
    import asyncio
    await asyncio.to_thread(_remove_lock)
        
    pesan = "🔊 <b>GLOBAL MUTE DICABUT</b>\n\nNotifikasi Alert kembali normal."
    
    catat(user.id, user.username, "/unmute", "berhasil")
    if update.callback_query:
        await update.callback_query.answer("Unmute berhasil")
        try:
            await update.callback_query.message.edit_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
            return
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())


async def cmd_ack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /ack - Acknowledge alert CRITICAL yang pending.
    
    Membaca pending_acks.json (cross-process IPC) yang ditulis oleh monitor process.
    Bot dan monitor berjalan sebagai proses PM2 berbeda — harus via file.
    """
    user = update.effective_user
    if await _check_access(update, user, "/ack"): return

    # Answer callback query DULU agar Telegram tidak anggap timeout
    if update.callback_query:
        try:
            await update.callback_query.answer("Memproses acknowledge...")
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    from monitor.alerts import acknowledge_alert, get_pending_alerts

    pending = get_pending_alerts()

    if not pending:
        pesan = "\u2705 <b>Tidak ada alert pending.</b>\n\nSemua alert sudah di-acknowledge atau belum ada alert kritis."
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
            except Exception:
                await update.callback_query.message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
        else:
            await update.message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
        return

    # Acknowledge semua
    count = acknowledge_alert()

    # Summary alert yang di-clear
    lines = []
    for a in pending[:5]:
        key = str(a.get('key', '-'))
        host = key.replace('down_', '')
        lines.append(f"\u2022 {host} [{a.get('time', '-')}]")
    summary = "\n".join(lines)
    if len(pending) > 5:
        summary += f"\n... dan {len(pending) - 5} lainnya"

    pesan = (
        f"\u2705 <b>{count} ALERT ACKNOWLEDGED</b>\n\n"
        f"Alert yang di-clear:\n{summary}\n\n"
        f"Escalation dihentikan."
    )

    catat(user.id, user.username, "/ack", f"berhasil ({count} alerts)")

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
        except Exception:
            await update.callback_query.message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
    else:
        await update.message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())




