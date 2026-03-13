# ============================================
# HANDLERS/CHARTS - Chart Command Handler
# /chart - Menampilkan grafik monitoring via Telegram
# ============================================

import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.logger import catat
from .utils import _check_access, with_menu_timestamp

logger = logging.getLogger(__name__)


# ============ KEYBOARD HELPERS ============

def _get_chart_keyboard():
    """DRY helper: chart menu keyboard (2-column layout + time range selector).

    R10: Menambah pilihan rentang waktu 1h/6h/24h per chart agar lebih fleksibel.
    """
    return [
        [
            InlineKeyboardButton("📈 CPU (1h)",  callback_data="chart_cpu_1"),
            InlineKeyboardButton("📈 CPU (6h)",  callback_data="chart_cpu_6"),
            InlineKeyboardButton("📈 CPU (24h)", callback_data="chart_cpu_24"),
        ],
        [
            InlineKeyboardButton("🧠 RAM (1h)",  callback_data="chart_ram_1"),
            InlineKeyboardButton("🧠 RAM (6h)",  callback_data="chart_ram_6"),
            InlineKeyboardButton("🧠 RAM (24h)", callback_data="chart_ram_24"),
        ],
        [
            InlineKeyboardButton("📶 Traffic (1h)",  callback_data="chart_traffic_1"),
            InlineKeyboardButton("📶 Traffic (6h)",  callback_data="chart_traffic_6"),
            InlineKeyboardButton("📶 Traffic (24h)", callback_data="chart_traffic_24"),
        ],
        [
            InlineKeyboardButton("📊 DHCP (6h)",  callback_data="chart_dhcp_6"),
            InlineKeyboardButton("📊 DHCP (24h)", callback_data="chart_dhcp_24"),
        ],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="cmd_start")],
    ]


_CHART_MENU_TEXT = (
    "📊 <b>CHART MONITORING</b>\n\n"
    "Pilih jenis chart dan rentang waktu:\n\n"
    "📈 <b>CPU/RAM</b> — Penggunaan resource (1h/6h/24h)\n"
    "📶 <b>Traffic</b> — Total trafik semua interface (1h/6h/24h)\n"
    "📊 <b>DHCP</b> — Tren pemakaian pool (6h/24h)\n\n"
    "⏱️ <i>Traffic chart inject data live saat dibuka.</i>"
)
_CHART_MENU_TEXT = with_menu_timestamp(_CHART_MENU_TEXT)


# ============ LIVE TRAFFIC INJECT (B10-RC3) ============

async def _inject_live_traffic_point():
    """B10-RC3: Ambil snapshot traffic live dari MikroTik dan simpan ke DB.

    Dipanggil tepat sebelum generate chart traffic agar titik paling kanan
    di chart selalu mencerminkan kondisi jaringan saat ini, bukan 5 menit lalu.
    Jika gagal, chart tetap tampil dari history — non-fatal.
    """
    try:
        from mikrotik import get_interfaces, get_traffic
        from core import database
        from core.config import MONITOR_IGNORE_IFACE

        interfaces = await asyncio.to_thread(get_interfaces)
        if not interfaces:
            return

        active = [
            i for i in interfaces
            if i.get('running') and i['name'] not in MONITOR_IGNORE_IFACE
        ]
        if not active:
            return

        traffic_tasks = [asyncio.to_thread(get_traffic, i['name']) for i in active]
        results = await asyncio.gather(*traffic_tasks, return_exceptions=True)

        batch = []
        for iface, traffic in zip(active, results):
            if isinstance(traffic, Exception) or not traffic:
                continue
            batch.extend([
                ('traffic_rx_bps', traffic.get('rx_bps', 0), iface['name']),
                ('traffic_tx_bps', traffic.get('tx_bps', 0), iface['name']),
            ])

        if batch:
            await asyncio.to_thread(database.record_metrics_batch, batch)
            logger.debug(f"Live traffic inject: {len(batch) // 2} interface(s)")

    except Exception as e:
        logger.debug(f"Live traffic inject error (non-fatal): {e}")


# ============ /chart ============

async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /chart - Menu pilihan grafik monitoring."""
    user = update.effective_user
    if await _check_access(update, user, "/chart"):
        return

    keyboard = _get_chart_keyboard()
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=_CHART_MENU_TEXT, parse_mode='HTML', reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            text=_CHART_MENU_TEXT, parse_mode='HTML', reply_markup=reply_markup
        )

    catat(user.id, user.username, "/chart", "berhasil")


async def callback_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback untuk chart buttons.

    Format data: "chart_{type}_{hours}" → e.g. "chart_cpu_24", "chart_traffic_1"
    R10: Mendukung time-range 1h/6h/24h dari keyboard selector.
    B10-RC3: Inject live traffic point sebelum generate traffic chart.
    """
    query = update.callback_query
    user = query.from_user

    if await _check_access(update, user, "callback_chart"):
        return

    data = query.data  # e.g. "chart_cpu_24"
    await query.answer("Generating chart...")

    # Parse format: chart_{type}_{hours}
    parts = data.split('_')
    if len(parts) < 3:
        await query.answer("Format chart tidak dikenal.", show_alert=True)
        return

    chart_type = parts[1]          # cpu / ram / dhcp / traffic
    try:
        hours = int(parts[2])      # 1 / 6 / 24
    except (ValueError, IndexError):
        hours = 24

    try:
        # Show loading message
        await query.edit_message_text(
            "⏳ <b>Generating chart...</b>\n<i>Mohon tunggu beberapa detik.</i>",
            parse_mode='HTML'
        )

        buf, summary = None, None
        caption = ""

        if chart_type == "cpu":
            from services.chart_service import generate_cpu_chart, get_data_freshness
            buf, summary = await asyncio.to_thread(generate_cpu_chart, hours)
            freshness, _ = await asyncio.to_thread(get_data_freshness, 'cpu_usage')
            if summary:
                caption = (
                    f"📈 <b>CPU Usage — {hours}h Terakhir</b>\n\n"
                    f"Avg: <b>{summary['avg']:.1f}%</b> | "
                    f"Min: {summary['min']:.1f}% | "
                    f"Max: {summary['max']:.1f}%\n"
                    f"Data points: {summary['count']}\n"
                    f"🕒 {freshness}"
                )
            else:
                caption = f"📈 <b>CPU Usage — {hours}h Terakhir</b>"

        elif chart_type == "ram":
            from services.chart_service import generate_ram_chart, get_data_freshness
            buf, summary = await asyncio.to_thread(generate_ram_chart, hours)
            freshness, _ = await asyncio.to_thread(get_data_freshness, 'ram_usage')
            if summary:
                caption = (
                    f"🧠 <b>RAM Usage — {hours}h Terakhir</b>\n\n"
                    f"Avg: <b>{summary['avg']:.1f}%</b> | "
                    f"Min: {summary['min']:.1f}% | "
                    f"Max: {summary['max']:.1f}%\n"
                    f"Data points: {summary['count']}\n"
                    f"🕒 {freshness}"
                )
            else:
                caption = f"🧠 <b>RAM Usage — {hours}h Terakhir</b>"

        elif chart_type == "dhcp":
            from services.chart_service import generate_dhcp_chart, get_data_freshness
            buf, summary = await asyncio.to_thread(generate_dhcp_chart, hours)
            freshness, _ = await asyncio.to_thread(get_data_freshness, 'dhcp_usage_pct')
            if summary:
                caption = (
                    f"📊 <b>DHCP Pool Usage — {hours}h Terakhir</b>\n\n"
                    f"Avg: <b>{summary['avg']:.1f}%</b> | "
                    f"Min: {summary['min']:.1f}% | "
                    f"Max: {summary['max']:.1f}%\n"
                    f"Data points: {summary['count']}\n"
                    f"🕒 {freshness}"
                )
            else:
                caption = f"📊 <b>DHCP Pool Usage — {hours}h Terakhir</b>"

        elif chart_type == "traffic":
            # B10-RC3: Inject live data point dulu sebelum generate chart
            await _inject_live_traffic_point()

            from services.chart_service import generate_traffic_chart, get_data_freshness
            buf, summary = await asyncio.to_thread(generate_traffic_chart, hours)
            freshness, _ = await asyncio.to_thread(get_data_freshness, 'traffic_rx_bps')
            if summary:
                ifaces = summary.get('ifaces', 'semua interface')
                caption = (
                    f"📶 <b>Traffic Jaringan — {hours}h Terakhir</b>\n\n"
                    f"Interface: <i>{ifaces}</i>\n"
                    f"Max Download (RX): <b>{summary['max_rx']} Mbps</b>\n"
                    f"Max Upload (TX): <b>{summary['max_tx']} Mbps</b>\n"
                    f"Avg: {summary['avg_rx']}⬇️ / {summary['avg_tx']}⬆️ Mbps\n"
                    f"Data points: {summary['count']}\n"
                    f"🕒 {freshness}"
                )
            else:
                caption = f"📶 <b>Traffic Jaringan — {hours}h Terakhir</b>"

        if buf:
            # Hapus pesan loading, kirim foto baru
            chat_id = query.message.chat_id
            try:
                await query.message.delete()
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=buf,
                caption=caption,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Kembali ke Chart", callback_data="back_to_chart")],
                    [InlineKeyboardButton("🏠 Menu Utama", callback_data="back_to_start")],
                ])
            )
            catat(user.id, user.username, f"/chart {data}", "berhasil")
        else:
            await query.edit_message_text(
                "ℹ️ <b>Data belum tersedia.</b>\n\n"
                "Chart membutuhkan data metrics yang dikumpulkan oleh monitor.\n"
                "Pastikan MIKRO_MONITOR sudah berjalan minimal beberapa saat.",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Kembali", callback_data="cmd_chart")],
                ])
            )

    except Exception as e:
        logger.error(f"Chart generation error: {e}")
        try:
            await query.edit_message_text(
                f"❌ Gagal generate chart:\n<code>{str(e)[:200]}</code>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Kembali", callback_data="cmd_chart")],
                ])
            )
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
async def callback_back_to_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle kembali ke chart menu dari foto chart."""
    query = update.callback_query
    user = query.from_user
    if await _check_access(update, user, "callback_back_to_chart"):
        return

    await query.answer()
    chat_id = query.message.chat_id

    try:
        await query.message.delete()
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    await context.bot.send_message(
        chat_id=chat_id,
        text=_CHART_MENU_TEXT,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(_get_chart_keyboard())
    )


async def callback_back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle kembali ke menu utama dari foto chart."""
    query = update.callback_query
    user = query.from_user
    if await _check_access(update, user, "callback_back_to_start"):
        return

    await query.answer()
    chat_id = query.message.chat_id

    try:
        await query.message.delete()
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    from .general import _build_home_menu
    pesan, reply_markup = await _build_home_menu()
    await context.bot.send_message(
        chat_id=chat_id,
        text=pesan,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


