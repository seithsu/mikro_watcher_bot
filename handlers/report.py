# ============================================
# HANDLERS/REPORT - Report & Bandwidth Commands
# /report, /bandwidth
# ============================================

import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.logger import catat
from .utils import _check_access, get_back_button, append_back_button, format_bytes_auto, escape_html, with_menu_timestamp
from mikrotik import get_top_queues, get_simple_queues, get_traffic, get_interfaces
from core import database

logger = logging.getLogger(__name__)


def _fmt_dur(seconds):
    """Format durasi detik jadi string yang mudah dibaca."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "0s"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}j {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"



# ============ /report ============

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /report - Laporan ringkasan downtime & uptime."""
    user = update.effective_user
    if await _check_access(update, user, "/report"): return

    # Default: pilih periode
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.message.edit_text("⏳ <i>Menyiapkan laporan...</i>", parse_mode='HTML')
        except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
    
    keyboard = [
        [
            InlineKeyboardButton("📊 7 Hari", callback_data="report_7"),
            InlineKeyboardButton("📊 14 Hari", callback_data="report_14"),
        ],
        [
            InlineKeyboardButton("📊 30 Hari", callback_data="report_30"),
            InlineKeyboardButton("📊 90 Hari", callback_data="report_90"),
        ],
    ]
    
    # Tag filter buttons
    keyboard.append([
        InlineKeyboardButton("🏷️ Filter: Server", callback_data="report_7_server"),
        InlineKeyboardButton("🏷️ Filter: WAN", callback_data="report_7_wan"),
    ])
    keyboard.append([
        InlineKeyboardButton("🏷️ Filter: WiFi", callback_data="report_7_wifi"),
        InlineKeyboardButton("🏷️ Filter: DNS", callback_data="report_7_dns"),
    ])
    keyboard.append([InlineKeyboardButton("🔙 Kembali ke Menu Utama", callback_data='cmd_start')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    pesan = (
        "📊 <b>LAPORAN INSIDEN & UPTIME</b>\n\n"
        "Pilih periode laporan atau gunakan filter tag:\n\n"
        "<i>Tips: Ketik /report 30 untuk langsung 30 hari</i>"
    )
    pesan = with_menu_timestamp(pesan)
    
    # Cek argument langsung
    if context.args:
        try:
            days = int(context.args[0])
            return await _send_report(update, context, days)
        except ValueError:
            pass
    
    if update.callback_query:
        await update.callback_query.message.edit_text(pesan, parse_mode='HTML', reply_markup=reply_markup)
    else:
        await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=reply_markup)
    
    catat(user.id, user.username, "/report", "berhasil")


async def callback_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback untuk report."""
    query = update.callback_query
    user = query.from_user

    if await _check_access(update, user, "callback_report"):
        return

    data = query.data  # report_7, report_30, report_7_server, etc.
    
    parts = data.replace("report_", "").split("_")
    days = int(parts[0])
    tag_filter = parts[1] if len(parts) > 1 else None
    
    await query.answer()
    try:
        await query.message.edit_text(f"⏳ <i>Generating report {days} hari...</i>", parse_mode='HTML')
    except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
    await _send_report(update, context, days, tag_filter)


async def _send_report(update, context, days, tag_filter=None):
    """Generate dan kirim laporan."""
    report = await asyncio.to_thread(database.get_report, days, tag_filter)
    uptime = await asyncio.to_thread(database.get_uptime_stats, days)
    
    # Format MTTR
    mttr = report['mttr_seconds']
    if mttr > 3600:
        mttr_str = f"{mttr // 3600}j {(mttr % 3600) // 60}m"
    elif mttr > 60:
        mttr_str = f"{mttr // 60}m {mttr % 60}s"
    else:
        mttr_str = f"{mttr}s"
    
    filter_label = f" (Tag: {tag_filter})" if tag_filter else ""
    
    pesan = (
        f"📊 <b>LAPORAN INSIDEN — {days} HARI TERAKHIR</b>{filter_label}\n"
        f"{'━' * 25}\n\n"
        f"📌 Total Insiden: <b>{report['total_incidents']}x</b>\n"
        f"⏱️ MTTR (Avg Recovery): <b>{mttr_str}</b>\n\n"
    )
    
    # Per-host breakdown
    if report['hosts']:
        pesan += "<b>🏠 PER HOST:</b>\n"
        for h in report['hosts'][:10]:
            dur = _fmt_dur(h['total_down_sec'])
            avg = _fmt_dur(h['avg_down_sec'])
            host_safe = escape_html(h['host'])
            pesan += f"  • {host_safe}: {h['count']}x (total: {dur}, avg: {avg})\n"
        pesan += "\n"
    
    # Tag breakdown
    if report['tags']:
        pesan += "<b>🏷️ PER KATEGORI:</b>\n"
        for t in report['tags']:
            tag_safe = escape_html(t['tag'])
            pesan += f"  • {tag_safe}: {t['count']}x\n"
        pesan += "\n"
    
    # Uptime stats
    if uptime:
        pesan += "<b>📈 UPTIME RANKING:</b>\n"
        for host, stats in list(uptime.items())[:10]:
            pct = stats['uptime_pct']
            icon = "🟢" if pct >= 99.9 else "🟡" if pct >= 99 else "🟠" if pct >= 95 else "🔴"
            host_safe = escape_html(host)
            pesan += f"  {icon} {host_safe}: {pct:.2f}% ({stats['total_downtime_str']} down)\n"
        pesan += "\n"
    
    # Metrics summary
    try:
        cpu_stats = await asyncio.to_thread(database.get_metrics_summary, 'cpu_usage', days)
        ram_stats = await asyncio.to_thread(database.get_metrics_summary, 'ram_usage', days)
        if cpu_stats or ram_stats:
            pesan += "<b>📉 RESOURCE TRENDS:</b>\n"
            if cpu_stats:
                pesan += f"  • CPU: avg {cpu_stats['avg']}% | max {cpu_stats['max']}%\n"
            if ram_stats:
                pesan += f"  • RAM: avg {ram_stats['avg']:.1f}% | max {ram_stats['max']:.1f}%\n"
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    pesan = with_menu_timestamp(pesan)
    keyboard = []
    if not tag_filter:
        keyboard.append([
            InlineKeyboardButton("🏷️ Filter Server", callback_data=f"report_{days}_server"),
            InlineKeyboardButton("🏷️ Filter WAN", callback_data=f"report_{days}_wan"),
        ])
    keyboard.append([InlineKeyboardButton("🔙 Kembali ke Menu Utama", callback_data='cmd_start')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(pesan, parse_mode='HTML', reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text(pesan, parse_mode='HTML', reply_markup=reply_markup)
    else:
        await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=reply_markup)


# ============ /bandwidth ============

async def cmd_bandwidth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /bandwidth - Top bandwidth users dari Simple Queues."""
    user = update.effective_user
    if await _check_access(update, user, "/bandwidth"): return
    
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.message.edit_text("⏳ <i>Mengambil data bandwidth...</i>", parse_mode='HTML')
        except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
    
    try:
        top = await asyncio.to_thread(get_top_queues, 15)
        
        if not top:
            pesan = "ℹ️ <i>Tidak ada traffic aktif saat ini.</i>"
            if update.callback_query:
                await update.callback_query.message.edit_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
            else:
                await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
            return
        
        pesan = "📊 <b>TOP BANDWIDTH USAGE</b>\n"
        pesan += f"{'━' * 25}\n\n"
        
        total_rx = 0
        total_tx = 0
        
        for i, q in enumerate(top, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            qname = escape_html(q['name'])
            pesan += (
                f"{medal} <b>{qname}</b>\n"
                f"   ↓ {escape_html(q['rx_rate_fmt'])} | ↑ {escape_html(q['tx_rate_fmt'])}\n"
                f"   Total: {escape_html(q['total_rate_fmt'])}\n\n"
            )
            total_rx += q['rx_rate']
            total_tx += q['tx_rate']
        
        pesan += f"{'━' * 25}\n"
        pesan += f"📶 Total aktif: ↓ {format_bytes_auto(total_rx)}ps | ↑ {format_bytes_auto(total_tx)}ps"
        pesan = with_menu_timestamp(pesan)
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="cmd_bandwidth")],
            [InlineKeyboardButton("🔙 Kembali ke Menu Utama", callback_data='cmd_start')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.message.edit_text(pesan, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=reply_markup)
        
        catat(user.id, user.username, "/bandwidth", "berhasil")
        
    except Exception as e:
        logger.error(f"Bandwidth error: {e}")
        pesan = f"❌ Error mengambil data bandwidth:\n<code>{escape_html(str(e)[:200])}</code>"
        if update.callback_query:
            await update.callback_query.message.edit_text(pesan, parse_mode='HTML', reply_markup=get_back_button())
        else:
            await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())




