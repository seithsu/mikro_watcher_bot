# ============================================
# BOT - Telegram Bot Monitoring MikroTik
# Multi-admin, rate limit, backup, daily report
# ============================================

import logging
import time
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

from core.config import (
    TOKEN, CHAT_ID, ADMIN_IDS,
    REBOOT_COOLDOWN, RATE_LIMIT_PER_MINUTE, DAILY_REPORT_HOUR, AUTO_BACKUP_DAY,
    INSTITUTION_NAME, BOT_VERSION, ASYNC_THREAD_WORKERS
)
import core.config as cfg
from mikrotik import (
    reboot_router, export_router_backup, export_router_backup_ftp,
    unblock_ip, send_wol, get_interfaces
)
from handlers.jobs import daily_report, auto_backup
from core.logger import catat, baca_log, format_log_pretty, rotate_log
from core.backup import backup_semua
from core.logging_setup import configure_root_logging
from core.runtime_guard import install_global_exception_hooks

logger = logging.getLogger(__name__)
_default_executor = None

from handlers.utils import get_back_button, _check_access, read_state_json
from core import database

# C2 FIX: _last_reboot_time dipindah ke handlers/general.py
# Gunakan set_last_reboot_time() dari sana

# ============ COMMAND HANDLERS ============

from handlers.general import (
    cmd_start, cmd_help, cmd_status, cmd_history, cmd_audit,
    cmd_reboot, cmd_backup, cmd_log, cmd_mtlog, callback_mtlog,
    callback_menu_cat, callback_reset_data, set_last_reboot_time
)
from handlers.network import (
    cmd_interface, callback_ifacedetail, cmd_traffic, cmd_scan, _do_scan, callback_scan,
    cmd_dhcp, callback_dhcp, cmd_wol, cmd_freeip, callback_freeip
)
from handlers.queue import (
    cmd_queue, callback_queue
)
from handlers.alert import (
    cmd_mute, cmd_mute_1h, cmd_unmute, callback_confirm_mute_1h, cmd_ack
)
from handlers.tools import (
    cmd_ping, callback_ping, cmd_dns, callback_dns, handle_dns_add,
    cmd_schedule, callback_schedule,
    cmd_vpn, cmd_firewall, callback_firewall, cmd_uptime, callback_uptime,
    cmd_config, callback_config_reset
)
from handlers.report import (
    cmd_report, callback_report, cmd_bandwidth
)
from handlers.charts import cmd_chart, callback_chart, callback_back_to_chart, callback_back_to_start

# ============ CALLBACK HANDLERS ============


def _schedule_daily_jobs(app: Application):
    """(Re)schedule daily report + weekly auto-backup berdasarkan config runtime terbaru."""
    job_queue = app.job_queue
    if not job_queue:
        return

    # Hapus job lama agar tidak duplikasi.
    for name in ("daily_report", "auto_backup"):
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()

    local_tz = datetime.now().astimezone().tzinfo
    hour = int(getattr(cfg, "DAILY_REPORT_HOUR", 7))
    backup_day = str(getattr(cfg, "AUTO_BACKUP_DAY", "sunday")).strip().lower()

    report_time = dtime(hour=hour, minute=0, second=0, tzinfo=local_tz)
    job_queue.run_daily(daily_report, time=report_time, name="daily_report")

    days_map = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2,
        'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
    }
    day_tuple = (days_map.get(backup_day, 6),)
    backup_time = dtime(hour=hour, minute=30, second=0, tzinfo=local_tz)
    job_queue.run_daily(auto_backup, time=backup_time, days=day_tuple, name="auto_backup")

    app.bot_data["_schedule_signature"] = (hour, backup_day)
    logger.info(f"Daily report dijadwalkan jam {hour}:00")
    logger.info(f"Auto-backup mingguan dijadwalkan hari {backup_day.capitalize()}")


async def _sync_scheduled_jobs(context: ContextTypes.DEFAULT_TYPE):
    """Sinkronisasi periodik schedule jika runtime config berubah."""
    try:
        cfg.reload_runtime_overrides(min_interval=5)
        cfg.reload_router_env(min_interval=10)
        sig = (int(getattr(cfg, "DAILY_REPORT_HOUR", 7)), str(getattr(cfg, "AUTO_BACKUP_DAY", "sunday")).lower())
        if context.application.bot_data.get("_schedule_signature") != sig:
            _schedule_daily_jobs(context.application)
    except Exception as e:
        logger.warning(f"Gagal sinkronisasi scheduler runtime: {e}")


async def _cleanup_bot_data_cache(context: ContextTypes.DEFAULT_TYPE):
    """Hapus cache bot_data lama agar memory tidak tumbuh tanpa batas."""
    try:
        now = time.time()
        bot_data = context.application.bot_data
        ttl_by_prefix = {
            "scan_result_": 1800,
            "freeip_res_": 1800,
            "mtlog_": 900,
            "wol_": 300,
        }
        removed = 0
        for key in list(bot_data.keys()):
            if not isinstance(key, str):
                continue
            for prefix, ttl in ttl_by_prefix.items():
                if key.startswith(prefix):
                    ts = bot_data.get(f"ts_{key}", 0) or 0
                    if not isinstance(ts, (int, float)):
                        ts = 0
                    if (now - float(ts)) > ttl:
                        bot_data.pop(key, None)
                        bot_data.pop(f"ts_{key}", None)
                        removed += 1
                    break
        if removed:
            logger.debug(f"Bot cache cleanup: {removed} entry dihapus")
    except Exception as e:
        logger.debug(f"Bot cache cleanup error: {e}")


async def callback_reboot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reboot konfirmasi"""
    query = update.callback_query
    data = query.data
    user = query.from_user

    if await _check_access(update, user, "callback_reboot"):
        return

    if data == 'reboot_confirm':
        await query.answer("Memulai proses reboot...")
        try:
            await query.edit_message_text("🔄 <b>Rebooting router...</b>\nMohon tunggu 1-2 menit hingga router kembali online.", parse_mode='HTML')
            await asyncio.to_thread(reboot_router)
            # C2 FIX: Update cooldown via handler module (bukan global bot level)
            set_last_reboot_time(time.time())
            catat(user.id, user.username, "/reboot", "berhasil")
            database.audit_log(user.id, user.username, "/reboot", "", "berhasil")
        except Exception as e:
            catat(user.id, user.username, "/reboot", f"error: {e}")
            database.audit_log(user.id, user.username, "/reboot", str(e)[:200], "gagal")
            await query.message.reply_text("❌ Reboot gagal dijalankan. Cek log bot untuk detail teknis.")
            
    elif data == 'reboot_cancel':
        await query.answer("Reboot dibatalkan.")
        await query.edit_message_text("ℹ️ <b>Reboot router dibatalkan.</b>", parse_mode='HTML', reply_markup=get_back_button())


async def callback_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle backup (ftp atau full)"""
    query = update.callback_query
    data = query.data
    user = query.from_user
    backup_success = False

    if await _check_access(update, user, "callback_backup"):
        return

    file_type = data.replace('backup_', '')
    await query.answer(f"Memproses request backup {file_type}...")
    try:
        if file_type == 'bot':
            backup_file = backup_semua()
            with open(backup_file, 'rb') as f:
                await query.message.reply_document(
                    document=f,
                    filename=backup_file,
                    caption=f"✅ <b>Backup Bot Script Selesai!</b>\nFile: {backup_file}",
                    parse_mode='HTML',
                    reply_markup=get_back_button(),
                )
            try:
                os.remove(backup_file)
            except OSError as e:
                logger.debug("Gagal hapus file backup bot sementara: %s", e)
            backup_success = True

        elif file_type in ('rsc', 'ftp'):
            await query.edit_message_text(
                "⏳ <b>Membuat backup script (.rsc)...</b>\n"
                "<i>Prioritas: API export, fallback FTP/FTPS bila perlu.</i>",
                parse_mode='HTML',
            )
            try:
                backup_file = await asyncio.to_thread(export_router_backup, "export")
            except Exception as e:
                logger.debug("Backup .rsc via API gagal, fallback FTP/FTPS: %s", e)
                backup_file = None
            if not backup_file:
                try:
                    backup_file = await asyncio.to_thread(export_router_backup_ftp, "export")
                except Exception as e:
                    logger.debug("Backup .rsc via FTP/FTPS gagal: %s", e)
                    backup_file = None
            if backup_file and os.path.exists(backup_file):
                with open(backup_file, 'rb') as f:
                    await query.message.reply_document(
                        document=f,
                        filename=backup_file,
                        caption="✅ <b>Backup Selesai (.rsc)!</b>",
                        parse_mode='HTML',
                        reply_markup=get_back_button(),
                    )
                try:
                    os.remove(backup_file)
                except OSError as e:
                    logger.debug("Gagal hapus file .rsc sementara: %s", e)
                backup_success = True
            else:
                await query.message.reply_text(
                    "❌ Gagal membuat backup script (.rsc).",
                    reply_markup=get_back_button(),
                )

        elif file_type in ('full', 'bin'):
            await query.edit_message_text(
                "⏳ <b>Membuat full backup (.backup) lokal...</b>\n"
                "<i>(File akan tersimpan di memory internal router, lalu di-download via API)</i>",
                parse_mode='HTML',
            )
            try:
                backup_file = await asyncio.to_thread(export_router_backup_ftp, "backup")
            except Exception as e:
                logger.debug("Backup .backup via FTP gagal, fallback API: %s", e)
                backup_file = None
            if not backup_file:
                try:
                    backup_file = await asyncio.to_thread(export_router_backup, "backup")
                except Exception as e:
                    logger.debug("Backup .backup via API gagal: %s", e)
                    backup_file = None
            if backup_file and os.path.exists(backup_file):
                with open(backup_file, 'rb') as f:
                    await query.message.reply_document(
                        document=f,
                        filename=backup_file,
                        caption="✅ <b>Full Backup (.backup) Selesai!</b>\nCatatan: Restore file ini dari Winbox.",
                        parse_mode='HTML',
                        reply_markup=get_back_button(),
                    )
                try:
                    os.remove(backup_file)
                except OSError as e:
                    logger.debug("Gagal hapus file .backup sementara: %s", e)
                backup_success = True
            else:
                await query.message.reply_text(
                    "❌ Gagal membuat full backup (.backup).",
                    reply_markup=get_back_button(),
                )

        status = "berhasil" if backup_success else "gagal"
        catat(user.id, user.username, f"/backup {data}", status)
        database.audit_log(user.id, user.username, "/backup", data, status)
        try:
            await query.message.delete()
        except Exception as e:
            logger.debug("Gagal hapus pesan backup sebelumnya: %s", e)
    except Exception as e:
        catat(user.id, user.username, f"/backup {data}", f"error: {e}")
        await query.message.reply_text(
            "❌ Error saat proses backup. Cek log bot untuk detail teknis.",
            reply_markup=get_back_button(),
        )


async def callback_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle IP unban request"""
    query = update.callback_query
    data = query.data
    user = query.from_user

    if await _check_access(update, user, "callback_unban"):
         return

    ip_target = data.replace('unban_', '')
    await query.answer("Memproses unban...")
    try:
        if unblock_ip(ip_target):
            await query.edit_message_text(f"✅ IP <b>{ip_target}</b> berhasil dihapus dari daftar blokir/Address-List.", parse_mode='HTML', reply_markup=get_back_button())
            catat(user.id, user.username, f"/unban {ip_target}", "berhasil")
        else:
            await query.edit_message_text(f"ℹ️ IP <b>{ip_target}</b> tidak ditemukan di daftar blokir.", parse_mode='HTML', reply_markup=get_back_button())
    except Exception as e:
        catat(user.id, user.username, f"/unban {ip_target}", f"error: {e}")
        await query.message.reply_text("❌ Error saat membuka blokir. Cek log bot untuk detail teknis.", reply_markup=get_back_button())


async def callback_wol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Wake on LAN action"""
    query = update.callback_query
    data = query.data
    user = query.from_user

    if await _check_access(update, user, "callback_wol"):
        return

    mac_asli = context.bot_data.get(data)
    # W8 FIX: Cek TTL — entry lama (> 5 menit) dianggap kadaluarsa
    ts_key = f"ts_{data}"
    stored_at_raw = context.bot_data.get(ts_key, 0)
    try:
        stored_at = float(stored_at_raw)
    except (TypeError, ValueError):
        stored_at = 0.0
    if not mac_asli or (time.time() - stored_at) > 300:
        # Hapus entry lama jika ada
        context.bot_data.pop(data, None)
        context.bot_data.pop(ts_key, None)
        await query.answer("Sesi kadaluarsa. Silakan ketik /wol lagi.")
        return
        
    await query.answer(f"Mengirim Magic Packet ke {mac_asli}...")
    try:
         interfaces = await asyncio.to_thread(get_interfaces)
         bridge_ifaces = [i['name'] for i in interfaces if i['running'] and (i['type'] in ('bridge', 'ether') and i['name'] != 'ether1')]
         
         success_count = 0
         for iface in bridge_ifaces:
             try:
                 await asyncio.to_thread(send_wol, mac_asli, iface)
                 success_count += 1
             except Exception as e:
                 logger.debug("WoL gagal kirim via interface %s: %s", iface, e)
                 
         # Hapus setelah digunakan
         context.bot_data.pop(data, None)
         context.bot_data.pop(ts_key, None)

         if success_count > 0:
             await query.edit_message_text(f"⚡ Magic Packet WoL berhasil disebar ke MAC:\n<b>{mac_asli}</b>", parse_mode='HTML', reply_markup=get_back_button())
             catat(user.id, user.username, f"/wol {mac_asli}", "berhasil")
         else:
             await query.edit_message_text(f"⚠️ Gagal mengirim WoL. Tidak ada interface LAN valid.", reply_markup=get_back_button())
    except Exception as e:
         catat(user.id, user.username, f"/wol {mac_asli}", f"error: {e}")
         await query.message.reply_text("❌ Error saat mengirim WoL. Cek log bot untuk detail teknis.", reply_markup=get_back_button())





async def post_init(app: Application):
    """Set daftar command untuk Menu Button di Telegram."""
    global _default_executor
    if _default_executor is None:
        loop = asyncio.get_running_loop()
        _default_executor = ThreadPoolExecutor(
            max_workers=max(2, int(getattr(cfg, "ASYNC_THREAD_WORKERS", ASYNC_THREAD_WORKERS)))
        )
        loop.set_default_executor(_default_executor)

        def _loop_exception_handler(_loop, context):
            logger.error("Unhandled asyncio loop exception: %s", context.get("message", "unknown"))
            if context.get("exception") is not None:
                logger.error("Async loop exception detail:", exc_info=context["exception"])

        loop.set_exception_handler(_loop_exception_handler)

    commands = [
        BotCommand("start", "Menu Utama"),
        BotCommand("help", "Bantuan & Daftar Perintah"),
        BotCommand("status", "Status Sistem"),
        BotCommand("report", "Laporan Insiden"),
        BotCommand("bandwidth", "Top Bandwidth"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands menu updated.")


async def post_shutdown(app: Application):
    """Shutdown resource async executor."""
    global _default_executor
    if _default_executor is not None:
        _default_executor.shutdown(wait=False, cancel_futures=True)
        _default_executor = None

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler - tangkap semua error yang tidak ter-handle."""
    err_str = str(context.error)
    
    # Optimasi Log: Abaikan traceback penuh untuk error koneksi biasa dari Telegram API
    if any(x in err_str for x in ["NetworkError", "ConnectError", "getaddrinfo failed", "TimedOut", "Query is too old"]):
        logger.warning(f"Telegram API Glitch/Timeout: {err_str}")
        return
        
    logger.error("Exception saat memproses update:", exc_info=context.error)

    try:
        if update and hasattr(update, 'effective_message') and update.effective_message:
            await update.effective_message.reply_text(
                "[ERR] Terjadi error internal. Cek log bot untuk detail."
            )
    except Exception as e:
        logger.debug("Gagal kirim pesan dari global error handler: %s", e)

async def handle_unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menghapus pesan text acak/tidak dikenal dari user (anti-spam)."""
    # Hanya berlakukan untuk Admin yang ada di ADMIN_IDS jika perlu,
    # tapi secara umum, hapus semua chat text yang bukan command
    try:
        if update.message:
            await update.message.delete()
    except Exception as e:
        logger.debug("Gagal hapus pesan text non-command: %s", e)


# ============ MAIN ============

def main():
    """Fungsi utama menjalankan bot."""

    # Logging terpusat + redaction token sensitif.
    configure_root_logging(level=logging.INFO)
    install_global_exception_hooks(process_name="bot")

    if not getattr(cfg, "MIKROTIK_USE_SSL", False):
        logger.info("MIKROTIK_USE_SSL=false: bot berjalan dalam mode API non-SSL sesuai konfigurasi.")
    elif not getattr(cfg, "MIKROTIK_TLS_VERIFY", True):
        logger.warning(
            "MIKROTIK_TLS_VERIFY=false: koneksi API RouterOS sudah terenkripsi, "
            "tetapi sertifikat belum diverifikasi. Ini cocok hanya sebagai mode transisi."
        )

    if not TOKEN:
        logger.error("Error: TOKEN belum diset di .env")
        return

    # Cek log dulu
    rotate_log()

    app = Application.builder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()

    # Handler Callback Modules
    app.add_handler(CallbackQueryHandler(callback_queue, pattern="^(del_queue|q_)"))
    app.add_handler(CallbackQueryHandler(callback_dhcp, pattern="^dhcp_page_"))
    app.add_handler(CallbackQueryHandler(callback_scan, pattern="^(sc_|scp_|sck_|scpk_)"))
    app.add_handler(CallbackQueryHandler(callback_freeip, pattern="^(freeip_|fipage_|freeipk_|fipagek_)"))
    app.add_handler(CallbackQueryHandler(callback_mtlog, pattern="^mtlogpage_"))
    app.add_handler(CallbackQueryHandler(callback_ping, pattern="^ping_"))
    app.add_handler(CallbackQueryHandler(callback_dns, pattern="^(dnspage_|dnsdel_|dns_add)"))
    app.add_handler(CallbackQueryHandler(callback_schedule, pattern="^(schedpage_|schedtoggle_|schedexec_)"))
    app.add_handler(CallbackQueryHandler(callback_firewall, pattern="^(fwpage_|fwtoggle_|fwexec_|fwswitch_)"))
    app.add_handler(CallbackQueryHandler(callback_uptime, pattern="^uptime_"))
    app.add_handler(CallbackQueryHandler(callback_report, pattern="^report_"))
    app.add_handler(CallbackQueryHandler(callback_chart, pattern="^chart_"))
    app.add_handler(CallbackQueryHandler(callback_back_to_chart, pattern="^back_to_chart$"))
    app.add_handler(CallbackQueryHandler(callback_back_to_start, pattern="^back_to_start$"))
    app.add_handler(CallbackQueryHandler(callback_config_reset, pattern="^config_reset_"))
    app.add_handler(CallbackQueryHandler(callback_reset_data, pattern="^reset_data_"))

    
    app.add_handler(CallbackQueryHandler(callback_reboot, pattern="^reboot_"))
    app.add_handler(CallbackQueryHandler(callback_backup, pattern="^backup_"))
    app.add_handler(CallbackQueryHandler(callback_unban, pattern="^unban_"))
    app.add_handler(CallbackQueryHandler(callback_wol, pattern="^wol_"))
    app.add_handler(CallbackQueryHandler(callback_ifacedetail, pattern="^(ifacedetail_|ifacedetailk_)"))

    # Handler routing menu utama (tombol inline yang memanggil CMD)
    app.add_handler(CallbackQueryHandler(cmd_start, pattern="^cmd_start$"))
    app.add_handler(CallbackQueryHandler(cmd_status, pattern="^cmd_status$|^status$|^status_full$"))
    app.add_handler(CallbackQueryHandler(cmd_interface, pattern="^cmd_interface$"))
    app.add_handler(CallbackQueryHandler(cmd_scan, pattern="^cmd_scan$"))
    app.add_handler(CallbackQueryHandler(cmd_traffic, pattern="^cmd_traffic$|^traffic_|^traffick_"))
    app.add_handler(CallbackQueryHandler(cmd_queue, pattern="^cmd_queue$"))

    app.add_handler(CallbackQueryHandler(cmd_reboot, pattern="^cmd_reboot$"))
    app.add_handler(CallbackQueryHandler(cmd_wol, pattern="^cmd_wol$"))
    app.add_handler(CallbackQueryHandler(cmd_dhcp, pattern="^cmd_dhcp$"))
    app.add_handler(CallbackQueryHandler(cmd_backup, pattern="^cmd_backup$"))
    app.add_handler(CallbackQueryHandler(cmd_mtlog, pattern="^cmd_mtlog$|^logfilter_"))
    app.add_handler(CallbackQueryHandler(cmd_history, pattern="^cmd_history$|^history_"))
    app.add_handler(CallbackQueryHandler(cmd_log, pattern="^cmd_log$"))
    app.add_handler(CallbackQueryHandler(cmd_audit, pattern="^cmd_audit$"))
    app.add_handler(CallbackQueryHandler(cmd_mute_1h, pattern="^cmd_mute_1h$"))
    app.add_handler(CallbackQueryHandler(callback_confirm_mute_1h, pattern="^confirm_mute_1h$"))
    app.add_handler(CallbackQueryHandler(cmd_unmute, pattern="^cmd_unmute$"))
    app.add_handler(CallbackQueryHandler(cmd_freeip, pattern="^cmd_freeip$"))
    app.add_handler(CallbackQueryHandler(cmd_ack, pattern="^cmd_ack$"))
    app.add_handler(CallbackQueryHandler(cmd_config, pattern="^cmd_config$"))
    app.add_handler(CallbackQueryHandler(cmd_ping, pattern="^cmd_ping$"))
    app.add_handler(CallbackQueryHandler(cmd_dns, pattern="^cmd_dns$"))
    app.add_handler(CallbackQueryHandler(cmd_schedule, pattern="^cmd_schedule$"))
    app.add_handler(CallbackQueryHandler(cmd_vpn, pattern="^cmd_vpn$"))
    app.add_handler(CallbackQueryHandler(cmd_firewall, pattern="^cmd_firewall$"))
    app.add_handler(CallbackQueryHandler(cmd_uptime, pattern="^cmd_uptime$"))
    app.add_handler(CallbackQueryHandler(cmd_report, pattern="^cmd_report$"))
    app.add_handler(CallbackQueryHandler(cmd_bandwidth, pattern="^cmd_bandwidth$"))
    app.add_handler(CallbackQueryHandler(cmd_chart, pattern="^cmd_chart$"))
    app.add_handler(CallbackQueryHandler(cmd_help, pattern="^cmd_help$"))
    app.add_handler(CallbackQueryHandler(callback_menu_cat, pattern="^menu_"))
    
    # Silently handle noop callback (do nothing)
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
    
    # Command handlers
    commands = {
        "start": cmd_start,
        "help": cmd_help,
        "status": cmd_status,
        "history": cmd_history,
        "audit": cmd_audit,
        "mute": cmd_mute,
        "unmute": cmd_unmute,
        "interface": cmd_interface,
        "traffic": cmd_traffic,
        "scan": cmd_scan,
        "wol": cmd_wol,
        "queue": cmd_queue,

        "dhcp": cmd_dhcp,
        "reboot": cmd_reboot,
        "backup": cmd_backup,
        "log": cmd_log,
        "mtlog": cmd_mtlog,
        "freeip": cmd_freeip,
        "ping": cmd_ping,
        "dns": cmd_dns,
        "schedule": cmd_schedule,
        "vpn": cmd_vpn,
        "firewall": cmd_firewall,
        "uptime": cmd_uptime,
        "report": cmd_report,
        "bandwidth": cmd_bandwidth,
        "chart": cmd_chart,
        "ack": cmd_ack,
        "config": cmd_config,
    }

    for name, handler in commands.items():
        app.add_handler(CommandHandler(name, handler))

    # DNS add handler (catch text input when awaiting DNS add)
    async def _dns_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.user_data.get('awaiting_dns_add'):
            handled = await handle_dns_add(update, context)
            if handled:
                return
        await handle_unknown_text(update, context)

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), _dns_text_handler))

    # Global error handler
    app.add_error_handler(error_handler)

    # Daily report scheduler (runtime-sync aware)
    job_queue = app.job_queue
    if job_queue:
        _schedule_daily_jobs(app)
        job_queue.run_repeating(_sync_scheduled_jobs, interval=60, first=60, name="schedule_sync")
        job_queue.run_repeating(_cleanup_bot_data_cache, interval=300, first=300, name="bot_cache_cleanup")

    # Startup info
    cmd_list = " ".join(f"/{c}" for c in commands)
    admin_list = ", ".join(str(a) for a in getattr(cfg, "ADMIN_IDS", ADMIN_IDS))

    logger.info("=" * 50)
    logger.info("BOT MONITORING MIKROTIK")
    logger.info("=" * 50)
    logger.info(f"Admin IDs: {admin_list}")
    logger.info(f"Commands: {cmd_list}")
    logger.info(f"Daily report: {cfg.DAILY_REPORT_HOUR}:00")
    logger.info(f"Rate limit: {cfg.RATE_LIMIT_PER_MINUTE}/menit")
    logger.info(f"Reboot cooldown: {cfg.REBOOT_COOLDOWN}s")
    logger.info("=" * 50)
    logger.info("Tekan Ctrl+C untuk berhenti")
    logger.info("=" * 50)

    # Batasi tipe update agar polling lebih efisien.
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
