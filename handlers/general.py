import logging
import time
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from mikrotik import get_status, get_mikrotik_log
import core.config as cfg
from core.logger import catat, baca_log, format_log_pretty
from services.runtime_reset import reset_runtime_data
from .utils import (
    _check_access, get_back_button, append_back_button, format_bytes_auto,
    read_state_json, escape_html, generic_error_html, set_cache_with_ts, get_cache_if_fresh,
    with_menu_timestamp
)
from core import database

logger = logging.getLogger(__name__)

# C2 FIX: reboot cooldown state di modul sendiri — tidak lagi import dari bot.py
_last_reboot_time = 0
_MTLOG_FILTER_KEYWORDS = {
    'error': ['error', 'critical'],
    'warning': ['warning'],
    'account': ['account'],
    'all': None,
}


def set_last_reboot_time(ts):
    """Setter untuk reboot timestamp (dipakai callback_reboot di bot.py)."""
    global _last_reboot_time
    _last_reboot_time = ts


async def _edit_or_reply_text(
    update: Update,
    text,
    *,
    parse_mode=None,
    reply_markup=None,
    target_message=None,
    target_editor=None,
    allow_fallback_reply=True,
    log_template="Suppressed non-fatal exception: %s",
):
    """Coba edit pesan callback; fallback ke reply biasa jika gagal/tidak ada callback."""
    if update.callback_query:
        try:
            if target_editor is not None:
                await target_editor(text, parse_mode=parse_mode, reply_markup=reply_markup)
            else:
                message = target_message or update.callback_query.message
                await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return True
        except Exception as e:
            logger.debug(log_template, e)

    if not allow_fallback_reply:
        return False

    await update.effective_message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    return False


def _build_mtlog_filter_markup(nav_buttons=None):
    """Keyboard filter log MikroTik yang dipakai ulang di seluruh alur mtlog."""
    keyboard = []
    if nav_buttons:
        keyboard.append(list(nav_buttons))
    keyboard.append([
        InlineKeyboardButton("Semua", callback_data='logfilter_all'),
        InlineKeyboardButton("🔴 Error/Crit", callback_data='logfilter_error')
    ])
    keyboard.append([
        InlineKeyboardButton("⚠️ Warning", callback_data='logfilter_warning'),
        InlineKeyboardButton("🛡️ Auth", callback_data='logfilter_account')
    ])
    return InlineKeyboardMarkup(keyboard)


def _filter_mtlog_entries(logs, topic_filter):
    """Filter log berdasarkan kelompok topic yang didukung UI."""
    if topic_filter == "all":
        return list(logs)

    keywords = _MTLOG_FILTER_KEYWORDS.get(topic_filter, [topic_filter])
    filtered_logs = []
    for log in logs:
        topics_str = str(log.get('topics', '')).lower()
        if any(kw in topics_str for kw in keywords):
            filtered_logs.append(log)
    return filtered_logs


def _get_first_context_arg(context):
    """Ambil argumen command pertama jika context.args memang list/tuple non-kosong."""
    args = getattr(context, "args", None)
    if isinstance(args, (list, tuple)) and args:
        return str(args[0])
    return None


async def _get_device_header():
    """W1 FIX: Shared helper — ambil teks header device (nama + versi ROS + status).
    Dipakai baik oleh _build_home_menu() maupun callback_menu_cat().
    """
    rb_text = "Device: <b>-</b>\n"
    ros_version = ""
    identity = ""

    try:
        info = await asyncio.to_thread(get_status)
        ros_version = escape_html(str(info.get('version', '')).strip())
        identity = escape_html(str(info.get('identity', '')).strip())
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)

    try:
        from mikrotik.system import get_system_routerboard
        rb_info = await asyncio.to_thread(get_system_routerboard)
        if rb_info:
            board = rb_info.get('board', '')
            model = rb_info.get('model', '')
            dev_name = [x for x in [board, model] if x and x != 'unknown']
            dev_str = escape_html(" ".join(dev_name) if dev_name else "-")
            ros_str = f" ROS v{ros_version}" if ros_version else ""
            rb_text = f"Device: <b>{dev_str}</b>{ros_str}\n"
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    # Fallback: jika routerboard info kosong/tidak tersedia, pakai identity dari resource system.
    if rb_text == "Device: <b>-</b>\n":
        if identity:
            ros_str = f" ROS v{ros_version}" if ros_version else ""
            rb_text = f"Device: <b>{identity}</b>{ros_str}\n"
    api_diag = {"healthy": False, "last_error": ""}
    try:
        from mikrotik.connection import pool
        api_diag = pool.connection_diagnostics()
    except Exception:
        api_diag = {"healthy": False, "last_error": ""}

    api_up = bool(api_diag.get("healthy", False))

    try:
        state = await asyncio.to_thread(read_state_json)
        kategori = state.get('kategori', '🟢 NORMAL')
        today_count = await asyncio.to_thread(database.count_incidents_today)
    except Exception:
        state = {}
        kategori = '🟢 NORMAL'
        today_count = 0

    if not api_up or state.get("api_connected") is False:
        kategori = "🟠 API UNAVAILABLE (MikroTik belum connect/login)"

    return rb_text, kategori, today_count, api_up, api_diag, state


def _host_state_icon(value, api_connected=True):
    """Render status host untuk UI tanpa salah menganggap API failure sebagai host down."""
    if api_connected is False or value is None:
        return "⚪ Unknown"
    return "✅" if bool(value) else "❌"


def _build_api_unavailable_message(state, api_diag):
    """Pesan ringkas saat RouterOS API belum tersedia."""
    from core.config import MIKROTIK_IP, INSTITUTION_NAME

    last_update = escape_html(state.get("last_update", "-"))
    api_error = escape_html(
        state.get("api_error")
        or api_diag.get("last_error")
        or "MikroTik API belum connect/login"
    )
    raw_error = str(
        state.get("api_error")
        or api_diag.get("last_error")
        or ""
    ).lower()
    if "invalid user name or password" in raw_error:
        hint = "Kemungkinan user/password API di router tidak cocok dengan konfigurasi bot."
    elif "not logged in" in raw_error:
        hint = "Sesi API invalid atau policy API user router berubah."
    elif "unreachable" in raw_error or "timed out" in raw_error:
        hint = "Cek konektivitas jaringan host bot ke MikroTik dan allow-list service API."
    elif "forcibly closed" in raw_error or "unexpectedly closed" in raw_error:
        hint = "Router menutup koneksi. Cek stabilitas link dan service API RouterOS."
    else:
        hint = "Periksa login/API RouterOS terlebih dahulu."

    return (
        f"📡 <b>LAPORAN JARINGAN — {INSTITUTION_NAME}</b>\n\n"
        f"Status: 🟠 <b>MIKROTIK API UNAVAILABLE</b>\n"
        f"Router: <code>{MIKROTIK_IP}</code>\n"
        f"Last update: <code>{last_update}</code>\n\n"
        f"Monitor host detail sedang dipause agar tidak memerah palsu.\n"
        f"{escape_html(hint)}\n\n"
        f"Detail: <code>{api_error}</code>"
    )


async def _build_home_menu():
    """Build home menu text and keyboard. Reusable by cmd_start and callback_back_to_start."""
    rb_text, kategori, today_count, api_up, api_diag, state = await _get_device_header()

    try:
        from core.config import MIKROTIK_IP

        if api_up and state.get("api_connected", True):
            router_status = f"✅ Terhubung ({MIKROTIK_IP})"
        else:
            router_status = f"⚠️ Belum connect/login ke {MIKROTIK_IP}"

    except Exception:
        router_status = "⚠️ Status API tidak tersedia"

    pesan = (
        f"🏠 <b>MIKRO WATCHER</b>\n"
        f"{rb_text}"
        f"{'━' * 25}\n\n"
        f"📡 Status: {kategori}\n"
        f"🔌 Router: {router_status}\n"
        f"📊 Insiden hari ini: {today_count}\n\n"
        f"Pilih menu:"
    )
    pesan = with_menu_timestamp(pesan)

    keyboard = [
        [
            InlineKeyboardButton("📊 Monitor & Report", callback_data='menu_monitor'),
            InlineKeyboardButton("🌐 Network", callback_data='menu_network')
        ],
        [
            InlineKeyboardButton("📈 Bandwidth", callback_data='menu_bandwidth'),
            InlineKeyboardButton("🛡️ Security", callback_data='menu_security')
        ],
        [
            InlineKeyboardButton("🧰 Tools", callback_data='menu_tools'),
            InlineKeyboardButton("⚙️ System", callback_data='menu_system')
        ],
        [InlineKeyboardButton("🧹 Reset Data", callback_data='reset_data_confirm')],
        [InlineKeyboardButton("❓ Help", callback_data='cmd_help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    return pesan, reply_markup


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start command handler."""
    user = update.effective_user
    if await _check_access(update, user, "/start"): return
    catat(user.id, user.username, "/start", "berhasil")

    if getattr(cfg, "ALERT_REQUIRE_START", False) and not update.callback_query:
        try:
            from monitor.alerts import set_alert_delivery_enabled
            await asyncio.to_thread(
                set_alert_delivery_enabled,
                True,
                f"telegram:{user.id}",
                "/start"
            )
        except Exception as e:
            logger.warning("Gagal mengaktifkan alert gate via /start: %s", e)

    pesan, reply_markup = await _build_home_menu()
    if update.callback_query:
        try:
            await update.callback_query.answer()
            await _edit_or_reply_text(
                update,
                pesan,
                parse_mode='HTML',
                reply_markup=reply_markup,
            )
            return
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    try: await update.message.delete()
    except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
    await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=reply_markup)


# Sub-menu definitions — human-friendly labels (no /command)
_MENU_CATEGORIES = {
    'menu_monitor': {
        'title': '📊 <b>Monitor & Report</b>',
        'buttons': [
            [InlineKeyboardButton("✅ Status", callback_data='cmd_status'),
             InlineKeyboardButton("📈 Chart", callback_data='cmd_chart')],
            [InlineKeyboardButton("📜 History", callback_data='cmd_history'),
             InlineKeyboardButton("📄 Report", callback_data='cmd_report')],
            [InlineKeyboardButton("⏱️ Uptime", callback_data='cmd_uptime')],
        ]
    },
    'menu_network': {
        'title': '🌐 <b>Network</b>',
        'buttons': [
            [InlineKeyboardButton("🌐 Interface", callback_data='cmd_interface'),
             InlineKeyboardButton("📡 Scan", callback_data='cmd_scan')],
            [InlineKeyboardButton("📋 DHCP", callback_data='cmd_dhcp'),
             InlineKeyboardButton("🔍 Free IP", callback_data='cmd_freeip')],
            [InlineKeyboardButton("🏓 Ping", callback_data='cmd_ping'),
             InlineKeyboardButton("📡 DNS", callback_data='cmd_dns')],
        ]
    },
    'menu_tools': {
        'title': '🧰 <b>Tools</b>',
        'buttons': [
            [InlineKeyboardButton("⚡ WOL", callback_data='cmd_wol'),
             InlineKeyboardButton("📅 Schedule", callback_data='cmd_schedule')],
            [InlineKeyboardButton("⚙️ Config", callback_data='cmd_config')],
        ]
    },
    'menu_security': {
        'title': '🛡️ <b>Security</b>',
        'buttons': [
            [InlineKeyboardButton("🛡️ Firewall", callback_data='cmd_firewall'),
             InlineKeyboardButton("🔒 VPN", callback_data='cmd_vpn')],
            [InlineKeyboardButton("🔍 Audit", callback_data='cmd_audit')],
        ]
    },
    'menu_bandwidth': {
        'title': '📈 <b>Bandwidth</b>',
        'buttons': [
            [InlineKeyboardButton("🚦 Traffic", callback_data='cmd_traffic'),
             InlineKeyboardButton("🔥 Top Usage", callback_data='cmd_bandwidth')],
            [InlineKeyboardButton("📋 Queue", callback_data='cmd_queue')],
        ]
    },
    'menu_system': {
        'title': '⚙️ <b>System</b>',
        'buttons': [
            [InlineKeyboardButton("🔇 Mute 1h", callback_data='cmd_mute_1h'),
             InlineKeyboardButton("🔊 Unmute", callback_data='cmd_unmute')],
            [InlineKeyboardButton("📝 Bot Log", callback_data='cmd_log'),
             InlineKeyboardButton("📋 Router Log", callback_data='cmd_mtlog')],
            [InlineKeyboardButton("✅ Ack Alert", callback_data='cmd_ack'),
             InlineKeyboardButton("💾 Backup", callback_data='cmd_backup')],
            [InlineKeyboardButton("🔄 Reboot", callback_data='cmd_reboot')],
            [InlineKeyboardButton("🧹 Reset Data", callback_data='reset_data_confirm')],
        ]
    }
}


async def callback_menu_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sub-menu category callbacks — with consistent header like home menu."""
    query = update.callback_query
    user = query.from_user

    if await _check_access(update, user, "callback_menu_cat"):
        return

    await query.answer()

    cat = _MENU_CATEGORIES.get(query.data)
    if not cat:
        return

    # W1 FIX: Gunakan helper _get_device_header() agar tidak duplikasi kode
    rb_text, kategori, today_count, api_up, api_diag, state = await _get_device_header()

    text = (
        f"🏠 <b>MIKRO WATCHER</b>\n"
        f"{rb_text}"
        f"{'━' * 25}\n\n"
        f"{cat['title']}\n"
        f"Pilih perintah:"
    )
    text = with_menu_timestamp(text)

    keyboard = list(cat['buttons'])
    keyboard.append([
        InlineKeyboardButton("🏠 Home", callback_data='cmd_start'),
    ])

    await _edit_or_reply_text(
        update,
        text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        target_editor=query.edit_message_text,
        allow_fallback_reply=False,
    )


async def callback_reset_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset histori/state runtime dari menu bot dengan konfirmasi dua langkah."""
    query = update.callback_query
    user = query.from_user

    if await _check_access(update, user, "callback_reset_data"):
        return

    data = str(query.data or "")

    if data == "reset_data_confirm":
        await query.answer()
        text = (
            "🧹 <b>RESET DATA RUNTIME</b>\n\n"
            "Aksi ini akan menghapus histori incident, metrics, audit log, state monitor, "
            "pending ack, dan file log runtime agar baseline kembali fresh.\n\n"
            "<b>Tidak mengubah</b> <code>.env</code> dan default-nya juga tidak menghapus "
            "<code>data/runtime_config.json</code>.\n\n"
            "Lanjutkan reset?"
        )
        text = with_menu_timestamp(text)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ya, Reset", callback_data="reset_data_execute"),
                InlineKeyboardButton("❌ Batal", callback_data="cmd_start"),
            ]
        ])
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
        return

    if data != "reset_data_execute":
        await query.answer("Aksi reset tidak valid.", show_alert=True)
        return

    await query.answer("Mereset data runtime...")
    try:
        result = await asyncio.to_thread(reset_runtime_data)
        if getattr(cfg, "ALERT_REQUIRE_START", False):
            try:
                from monitor.alerts import set_alert_delivery_enabled
                await asyncio.to_thread(
                    set_alert_delivery_enabled,
                    True,
                    f"telegram:{user.id}",
                    "reset_data_menu",
                )
            except Exception as gate_err:
                logger.debug("Reset data: gagal mengaktifkan ulang alert gate: %s", gate_err)

        db = result.get("database", {})
        text = (
            "✅ <b>Reset data selesai.</b>\n\n"
            f"Incidents dihapus: <code>{int(db.get('incidents', 0) or 0)}</code>\n"
            f"Metrics dihapus: <code>{int(db.get('metrics', 0) or 0)}</code>\n"
            f"Audit log dihapus: <code>{int(db.get('audit_log', 0) or 0)}</code>\n"
            f"Total record dihapus: <code>{int(db.get('total', 0) or 0)}</code>\n\n"
            "Monitor akan memuat baseline baru dan membersihkan cache/state pada siklus berikutnya."
        )
        text = with_menu_timestamp(text)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏠 Home", callback_data='cmd_start'),
                InlineKeyboardButton("✅ Status", callback_data='cmd_status'),
            ]
        ])
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
    except Exception as e:
        logger.exception("Reset data via bot gagal")
        await query.edit_message_text(
            generic_error_html("Reset data gagal"),
            parse_mode='HTML',
            reply_markup=get_back_button('cmd_start')
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /help - Daftar semua perintah."""
    user = update.effective_user
    if await _check_access(update, user, "/help"):
        return

    from core.config import BOT_VERSION
    pesan = (
        f"📖 <b>DAFTAR PERINTAH</b> <i>v{BOT_VERSION}</i>\n\n"
        "<b>📊 Monitor</b>\n"
        "/start — Menu Utama\n"
        "/status — Status Router & Network\n"
        "/history — Riwayat Downtime\n"
        "/uptime — Uptime per Host\n"
        "/audit — Cek Keamanan Router\n"
        "/report — Laporan Insiden & Uptime\n"
        "/chart — Grafik CPU/RAM/Uptime\n\n"
        "<b>🌐 Network</b>\n"
        "/interface — Daftar Interface\n"
        "/traffic — Bandwidth Usage\n"
        "/scan — Deteksi IP Terkoneksi\n"
        "/freeip — Cek IP Kosong\n"
        "/dhcp — Daftar Client DHCP\n"
        "/ping — Ping dari Router\n"
        "/dns — Kelola DNS Static\n\n"
        "<b>📈 Bandwidth</b>\n"
        "/bandwidth — Top Bandwidth Users\n"
        "/queue — Manajemen Limit\n\n"
        "<b>🛡️ Security</b>\n"
        "/firewall — Kelola Firewall Rules\n"
        "/vpn — Monitor VPN Tunnels\n\n"
        "<b>⚙️ System</b>\n"
        "/mute — Matikan Notifikasi Alert\n"
        "/unmute — Nyalakan Kembali Alert\n"
        "/ack — Acknowledge Alert Pending\n"
        "/log — Log Interaksi Bot\n"
        "/mtlog — Log Sistem Router\n"
        "/backup — Backup Config/Script\n"
        "/reboot — Restart Router\n\n"
        "<b>🧰 Tools</b>\n"
        "/wol — Wake on LAN\n"
        "/schedule — Kelola Scheduler\n"
        "/config — Setting Bot Runtime\n"
        "🧹 Reset Data — Tombol di menu awal/System\n\n"
        "<b>ℹ️ Catatan</b>\n"
        "Jika alert gate aktif, notifikasi monitor baru aktif setelah /start.\n"
        "Jumlah paket /ping diatur lewat <code>PING_COUNT</code>; "
        "<code>NETWATCH_PING_CONCURRENCY</code> hanya mengatur banyaknya host yang dicek paralel.\n"
        "Semua menu utama menampilkan timestamp lokal bot.\n"
    )
    pesan = with_menu_timestamp(pesan)
    catat(user.id, user.username, "/help", "berhasil")
    if update.callback_query:
        try:
            await update.callback_query.answer()
            await _edit_or_reply_text(
                update,
                pesan,
                parse_mode='HTML',
                reply_markup=get_back_button(),
            )
            return
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /status - Status ringkas sistem."""
    user = update.effective_user
    if await _check_access(update, user, "/status"):
        return

    msg_load = None
    if update.callback_query:
        await update.callback_query.answer()
        msg_load = update.callback_query.message
        try:
            await msg_load.edit_text("⏳ <i>Mengambil data status router...</i>", parse_mode='HTML')
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    else:
        msg_load = await update.effective_message.reply_text("⏳ <i>Mengambil data status router...</i>", parse_mode='HTML')

    try:
        from mikrotik.connection import pool
        state = await asyncio.to_thread(read_state_json)
        api_diag = pool.connection_diagnostics()
        api_connected = bool(api_diag.get("healthy", False)) and state.get("api_connected", True) is not False

        if not api_connected:
            pesan = _build_api_unavailable_message(state, api_diag)
            await msg_load.edit_text(
                pesan,
                parse_mode='HTML',
                reply_markup=get_back_button('menu_monitor')
            )
            catat(user.id, user.username, "/status", "api-unavailable")
            return

        from mikrotik import (
            get_status, get_interfaces, get_dhcp_usage_count, get_dhcp_pool_capacity, get_dhcp_leases,
            get_monitored_aps, get_monitored_servers, get_monitored_critical_devices,
            get_default_gateway, get_active_critical_device_names
        )
        from core.config import DHCP_POOL_SIZE, GW_WAN, GW_INET, MIKROTIK_IP

        # Sequential calls — hindari concurrent access ke router
        # Setiap call mendapat koneksi thread-local sendiri
        info = await asyncio.to_thread(get_status)
        interfaces = await asyncio.to_thread(get_interfaces)
        current_aps = await asyncio.to_thread(get_monitored_aps)
        current_servers = await asyncio.to_thread(get_monitored_servers)
        current_critical = await asyncio.to_thread(get_monitored_critical_devices)
        try:
            current_gw_wan = await asyncio.to_thread(get_default_gateway)
        except Exception:
            current_gw_wan = None
        if not current_gw_wan:
            current_gw_wan = GW_WAN

        if not info:
            raise Exception("Gagal mengambil data resource dari router")

        try:
            dhcp_count = await asyncio.to_thread(get_dhcp_usage_count)
            dhcp_pool_size = await asyncio.to_thread(get_dhcp_pool_capacity)
            leases = await asyncio.to_thread(get_dhcp_leases)
        except Exception:
            dhcp_count = 0
            dhcp_pool_size = 0
            leases = []

        total_ram = int(info['ram_total'])
        free_ram = int(info['ram_free'])
        used_ram = total_ram - free_ram
        ram_pct = ((used_ram) / total_ram) * 100 if total_ram > 0 else 0
        used_ram_mb = used_ram / (1024*1024)
        total_ram_mb = total_ram / (1024*1024)
        free_ram_mb = free_ram / (1024*1024)
        


        up_text = info['uptime']
        
        # Ambil matriks dari state.json via shared utility
        kategori_net = state.get('kategori', '🟢 NORMAL')
        hosts = state.get('hosts', {})
        def up(h):
            return _host_state_icon(hosts.get(h), api_connected=state.get("api_connected", True))

        # Cek newest lease
        newest_lease = "Unknown"
        if leases:
            dyn_leases = [l for l in leases if l.get('dynamic')]
            if dyn_leases:
                # Prefer bound leases as they are actively connected
                bound_leases = [l for l in dyn_leases if l.get('status') == 'bound']
                target_list = bound_leases if bound_leases else dyn_leases
                if target_list:
                    last = target_list[-1]
                    last_seen = last.get('last-seen', '')
                    newest_lease = f"{last.get('address')} ({last.get('host', '-')})"
                    if last_seen:
                        newest_lease += f" seen {last_seen}"

        effective_dhcp_pool_size = int(dhcp_pool_size or DHCP_POOL_SIZE or 0)
        pool_pct_dhcp = (dhcp_count / effective_dhcp_pool_size) * 100 if effective_dhcp_pool_size > 0 else 0

        # Waktu
        from datetime import datetime
        tz_label = datetime.now().astimezone().tzname() or "LOCAL"
        now_str = datetime.now().strftime(f"%Y-%m-%d %H:%M:%S {tz_label}")

        # Calculate Disk usage
        total_disk = int(info.get('disk_total', 0))
        free_disk = int(info.get('disk_free', 0))
        used_disk = total_disk - free_disk
        disk_pct = (used_disk / total_disk) * 100 if total_disk > 0 else 0
        used_disk_mb = used_disk / (1024*1024)
        total_disk_mb = total_disk / (1024*1024)

        from core.config import INSTITUTION_NAME, BOT_IP
        pesan = (
            f"📡 <b>LAPORAN JARINGAN — {INSTITUTION_NAME}</b>\n"
            f"🕒 {now_str}\n\n"
            f"Kondisi Umum: {kategori_net}\n\n"
            f"<b>📱 Koneksi Perangkat:</b>\n"
            f"- Router ({MIKROTIK_IP}): {up(MIKROTIK_IP)}\n"
        )
        if current_gw_wan: pesan += f"- WAN Gateway ({current_gw_wan}): {up(current_gw_wan)}\n"
        if GW_INET: pesan += f"- Internet ({GW_INET}): {up(GW_INET)}\n"
        
        for k, v in current_servers.items():
            pesan += f"- {k} ({v}): {up(v)}\n"

        for k, v in current_critical.items():
            pesan += f"- [Penting] {k} ({v}): {up(v)}\n"

        active_critical_names = await asyncio.to_thread(get_active_critical_device_names)
        unresolved_critical = [n for n in active_critical_names if n not in current_critical]
        for name in unresolved_critical:
            pesan += f"- [Penting] {name}: ⚪ Unknown (hostname DHCP belum ditemukan)\n"
            
        for ap_name, ap_ip in current_aps.items():
            pesan += f"- {ap_name} ({ap_ip}): {up(ap_ip)}\n"
            
        pesan += f"- Bot Server ({BOT_IP}): 🟦 Bekerja\n\n"

        pesan += (
            f"<b>⚙️ Kesehatan Sistem:</b>\n"
            f"- Uptime: {up_text}\n"
        )
        
        # Format CPU info
        cpu_info = f"- Prosesor: {info['cpu']}% terpakai"
        if info.get('cpu_freq'): cpu_info += f" @ {info['cpu_freq']}MHz"
        if info.get('cpu_count', 1) > 1: cpu_info += f" ({info['cpu_count']} cores)"
        pesan += f"{cpu_info}\n"
        
        pesan += f"- Memori: {used_ram_mb:.1f}MB terpakai dari {total_ram_mb:.1f}MB\n"
        if total_disk > 0:
            pesan += f"- Penyimpanan: {disk_pct:.1f}% terpakai ({used_disk_mb:.1f}MB dari {total_disk_mb:.1f}MB)\n"
        
        # Format Hardware & OS info
        board_model = []
        if info.get('board') and info['board'] != '?': board_model.append(info['board'])
        if info.get('model'): board_model.append(info['model'])
        if board_model:
            pesan += f"- Device: {' '.join(board_model)}\n"
            
        os_fw = []
        if info.get('version') and info['version'] != '?': os_fw.append(f"RouterOS v{info['version']}")
        if info.get('current_firmware'): os_fw.append(f"Firmware {info['current_firmware']}")
        if os_fw:
            pesan += f"- System: {' | '.join(os_fw)}\n"
            
        # Format Sensors
        sensors = []
        if info.get('cpu_temp'): sensors.append(f"🌡️ {info['cpu_temp']}°C")
        if info.get('voltage'):
            v = info['voltage']
            # MikroTik often returns voltage in decidegrees (e.g. 241 = 24.1V)
            try:
                v_val = float(v)
                if v_val > 100: v_val = v_val / 10
                sensors.append(f"⚡ {v_val}V")
            except Exception:
                sensors.append(f"⚡ {v}V")
                
        if sensors:
            pesan += f"- Sensors: {' | '.join(sensors)}\n"

        pesan += f"\n<b>🔌 Interface:</b>\n"

        indibiz = next((i for i in interfaces if 'indibiz' in i['name'].lower() or 'ether1' in i['name'].lower()), None)
        local = next((i for i in interfaces if 'local' in i['name'].lower() or 'ether2' in i['name'].lower()), None)

        if indibiz:
            irun = "🟢 UP" if indibiz['running'] else "🔴 DOWN"
            pesan += f"- INDIBIZ: {irun} | link-downs: {indibiz.get('link_downs', 0)} | rx/tx errors: {indibiz.get('rx_error', 0)}/{indibiz.get('tx_error', 0)}\n"
        if local:
            lrun = "🟢 UP" if local['running'] else "🔴 DOWN"
            pesan += f"- LOCAL: {lrun} | link-downs: {local.get('link_downs', 0)} | rx/tx errors: {local.get('rx_error', 0)}/{local.get('tx_error', 0)}\n"

        pesan += (
            f"\n<b>DHCP:</b>\n"
            f"- Pool: {dhcp_count}/{effective_dhcp_pool_size} ({pool_pct_dhcp:.0f}%)\n"
            f"- Lease newest: {newest_lease}\n\n"
        )
        
        pesan += (
            f"<b>Saran tindakan:</b>\n"
            f"1) Periksa status indikator silang ❌ di matriks\n"
            f"2) Jika 🔴 CORE DOWN, utamakan periksa Router / Indibiz\n"
            f"3) Jika 🟡 WIFI PARTIAL, periksa jalur switch ke AP mati"
        )

        catat(user.id, user.username, "/status", "berhasil")
        
        keyboard = []
        keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="status_full")])
             
        reply_markup = InlineKeyboardMarkup(keyboard)
             
        try:
             import telegram.error
             await msg_load.edit_text(pesan, parse_mode='HTML', reply_markup=append_back_button(reply_markup, 'menu_monitor'))
        except telegram.error.BadRequest as e:
             if 'not modified' in str(e).lower():
                  pass # abaikan error ini
             else:
                  await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=append_back_button(reply_markup, 'menu_monitor'))
        except Exception:
             await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=append_back_button(reply_markup, 'menu_monitor'))

    except Exception as e:
        catat(user.id, user.username, "/status", f"gagal: {e}")
        try:
             await msg_load.edit_text(
                 generic_error_html("Gagal mengambil status router"),
                 parse_mode='HTML',
                 reply_markup=get_back_button('menu_monitor')
             )
        except Exception:
             await update.effective_message.reply_text(
                 generic_error_html("Gagal mengambil status router"),
                 parse_mode='HTML',
                 reply_markup=get_back_button('menu_monitor')
             )



async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /history - Riwayat incident dengan pagination dan status."""
    user = update.effective_user
    if await _check_access(update, user, "/history"):
        return

    # Determine page from callback or args
    page = 0
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data
        if data.startswith("history_"):
            try:
                page = int(data.replace("history_", ""))
            except ValueError:
                page = 0
    elif context.args:
        try:
            page = int(context.args[0])
        except (ValueError, IndexError):
            page = 0

    import asyncio
    per_page = 10
    total = await asyncio.to_thread(database.count_all_incidents)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    
    history = await asyncio.to_thread(
        database.get_recent_history, per_page, offset=page * per_page
    )
    
    if not history and page == 0:
        pesan = "\u2705 Tidak ada catatan downtime yang terekam dalam database."
    else:
        pesan = (
            f"📜 <b>RIWAYAT INCIDENT</b>\n"
            f"Total: {total} | Hal {page + 1}/{total_pages}\n"
            f"{'━' * 25}\n\n"
        )
        for i, dict_h in enumerate(history, page * per_page + 1):
            # Status: resolved or ongoing
            if dict_h['waktu_up']:
                status = "\u2705"
                durasi = int(dict_h['durasi_detik'] or 0)
                if durasi < 0:
                    dur_str = "Auto-closed"
                else:
                    m, s = divmod(durasi, 60)
                    h, m = divmod(m, 60)
                    if h > 0:
                        dur_str = f"{h}h {m}m {s}s"
                    elif m > 0:
                        dur_str = f"{m}m {s}s"
                    else:
                        dur_str = f"{s}s"
            else:
                status = "\U0001F534"
                dur_str = "Sedang DOWN"

            waktu = dict_h['waktu_down'].replace("T", " ")[:16]
            tag = dict_h.get('tag', '')
            tag_str = f" [{tag}]" if tag else ""

            pesan += f"{status} <b>{i}. {dict_h['host']}</b>{tag_str}\n"
            pesan += f"   🕐 {waktu} | ⏱️ {dur_str}\n\n"

    # Pagination buttons
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"history_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"history_{page + 1}"))
    keyboard = [nav] if nav else []
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="history_0")])

    reply_markup = append_back_button(InlineKeyboardMarkup(keyboard), 'menu_monitor')

    catat(user.id, user.username, "/history", "berhasil")
    if update.callback_query:
        try:
            await _edit_or_reply_text(
                update,
                pesan,
                parse_mode='HTML',
                reply_markup=reply_markup,
            )
            return
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=reply_markup)


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /audit - Pengecekan celah keamanan RouterOS."""
    user = update.effective_user
    if await _check_access(update, user, "/audit"):
        return

    msg = None
    if update.callback_query:
        await update.callback_query.answer()
        try:
            msg = update.callback_query.message
            await msg.edit_text("⏳ <i>Menjalankan sekuriti audit...</i>", parse_mode='HTML')
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    try:
        from mikrotik import _pool
        from mikrotik.decorators import to_bool
        import asyncio
        
        def run_audit():
            api = _pool.get_api()
            report = []
            
            # 1. Cek User Default (admin)
            users = list(api.path('user'))
            has_admin = any(u.get('name') == 'admin' for u in users)
            if has_admin:
                report.append("❌ Ada user default 'admin' yang berisiko di-bruteforce.")
            else:
                report.append("✅ Tidak ada user 'admin' standar.")

            # 2. Cek Layanan Terbuka Terlalu Banyak (ftp, telnet, www)
            services = list(api.path('ip', 'service'))
            open_risky = []
            for s in services:
                if not to_bool(s.get('disabled', False)) and s.get('name') in ['telnet', 'ftp', 'www', 'ssh']:
                    # cek apakah dibatasi ip list / subnet
                    addr = s.get('address', '')
                    if not addr:
                        open_risky.append(s['name'])
                        
            if open_risky:
                report.append(f"❌ Layanan berikut terbuka untuk publik (tanpa IP allowance): {', '.join(open_risky)}")
            else:
                report.append("✅ Layanan kritis aman (dibatasi/didisable).")

            # 3. Cek Open DNS Resolver
            dns_settings = list(api.path('ip', 'dns'))
            allow_remote = False
            for d in dns_settings:
                 if to_bool(d.get('allow-remote-requests', False)):
                      allow_remote = True
                      break
            
            if allow_remote:
                 # cek apakah traffic dns difilter lewat firewall
                 firewall = list(api.path('ip', 'firewall', 'filter'))
                 # heuristik: cek apakah ada drop port 53
                 has_filter = any(f.get('dst-port') == '53' and f.get('action') == 'drop' for f in firewall)
                 if not has_filter:
                      report.append("⚠️ DNS Allow-Remote nyala, dan tidak terlihat ada blokir port 53 di Firewall! Berisiko terkena DNS Amplification DDoS.")
                 else:
                      report.append("✅ DNS Remote nyala, tetapi ada proteksi di firewall.")
            else:
                 report.append("✅ DNS Remote mati (Aman).")
                 
            return "\n\n".join(report)
            
        hasil_audit = await asyncio.to_thread(run_audit)

        pesan = f"🛡️ <b>HASIL AUDIT KEAMANAN (BASIC)</b>\n➖➖➖➖➖➖➖➖➖➖➖➖➖➖\n\n{hasil_audit}"

        catat(user.id, user.username, "/audit", "berhasil")
        if update.callback_query:
            try:
                await msg.edit_text(pesan, parse_mode='HTML', reply_markup=get_back_button('menu_monitor'))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=get_back_button())

    except Exception as e:
        catat(user.id, user.username, "/audit", f"gagal: {e}")
        if update.callback_query:
            try:
                await msg.edit_text(
                    generic_error_html("Audit gagal dijalankan"),
                    parse_mode='HTML',
                    reply_markup=get_back_button()
                )
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(
                generic_error_html("Audit gagal dijalankan"),
                parse_mode='HTML',
                reply_markup=get_back_button()
            )


async def cmd_reboot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /reboot - Restart router dengan konfirmasi."""
    user = update.effective_user
    if await _check_access(update, user, "/reboot"):
        return

    import time
    from core.config import REBOOT_COOLDOWN

    # C2 FIX: Gunakan _last_reboot_time dari modul ini sendiri, bukan 'import bot'
    now = time.time()
    elapsed = now - _last_reboot_time
    if elapsed < REBOOT_COOLDOWN:
        sisa = int(REBOOT_COOLDOWN - elapsed)
        if update.callback_query:
             await update.callback_query.answer(f"Cooldown! Tunggu {sisa} detik", show_alert=True)
             return
        await update.effective_message.reply_text(f"⚠️ Cooldown aktif! Tunggu {sisa} detik lagi sebelum reboot.")
        return

    if update.callback_query:
        await update.callback_query.answer()

    catat(user.id, user.username, "/reboot", "diminta")

    keyboard = [
        [
            InlineKeyboardButton("🚨 YA, REBOOT SEKARANG", callback_data='reboot_confirm'),
            InlineKeyboardButton("❌ BATAL", callback_data='cmd_start')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    pesan_reboot = (
        "⚠️ <b>PERINGATAN!</b>\n\n"
        "Anda akan melakukan <b>RESTART</b> pada router.\n"
        "Semua koneksi internet dan jaringan akan terputus selama 1-2 menit.\n\n"
        "Apakah Anda <b>yakin</b> ingin melanjutkan?"
    )
    pesan_reboot = with_menu_timestamp(pesan_reboot)
    if update.callback_query:
        try:
            await _edit_or_reply_text(
                update,
                pesan_reboot,
                parse_mode='HTML',
                reply_markup=reply_markup,
            )
            return
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    await update.effective_message.reply_text(pesan_reboot, parse_mode='HTML', reply_markup=reply_markup)


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /backup - Menampilkan menu backup."""
    user = update.effective_user

    if await _check_access(update, user, "/backup"):
        return

    if update.callback_query:
        await update.callback_query.answer()

    keyboard = [
        [InlineKeyboardButton("📁 Script Bot (.zip)", callback_data='backup_bot')],
        [InlineKeyboardButton("🗄️ Config Router (.rsc)", callback_data='backup_rsc')],
        [InlineKeyboardButton("📦 Full Router (.backup)", callback_data='backup_bin')],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data='cmd_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    pesan_backup = with_menu_timestamp(
        "💾 <b>BACKUP</b>\n\n"
        "Pilih tipe backup yang ingin diunduh:"
    )
    catat(user.id, user.username, "/backup", "menunggu-pilihan")
    
    if update.callback_query:
        try:
            await _edit_or_reply_text(
                update,
                pesan_backup,
                reply_markup=reply_markup,
            )
            return
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    await update.effective_message.reply_text(pesan_backup, reply_markup=reply_markup)


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /log - Lihat log penggunaan bot."""
    user = update.effective_user

    if await _check_access(update, user, "/log"): return

    if update.callback_query: await update.callback_query.answer()

    import asyncio
    logs = await asyncio.to_thread(baca_log, 10)
    text = format_log_pretty(logs)

    catat(user.id, user.username, "/log", "berhasil")
    if update.callback_query:
        try:
            await _edit_or_reply_text(
                update,
                text,
                parse_mode='HTML',
                reply_markup=get_back_button(),
            )
            return
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())


def _format_mtlog_page(filtered_logs, topic_filter, page=0, per_page=10):
    """Format satu halaman log MikroTik."""
    total = len(filtered_logs)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    end = min(start + per_page, total)
    page_logs = filtered_logs[start:end]

    label = topic_filter.upper() if topic_filter != "all" else "SEMUA"
    text = (
        f"📋 <b>Log MikroTik (Filter: {label})</b>\n"
        f"Total: {total} log | Hal {page + 1}/{total_pages}\n"
        f"{'━' * 28}\n\n"
    )

    if not page_logs:
        text += "<i>Tidak ada log ditemukan.</i>\n"
    else:
        for log in page_logs:
            topics = log.get('topics', '').replace(',', ' | ')
            safe_msg = log.get('message', '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            text += f"⏰ {log.get('time', '')}\n"
            text += f"🏷️ {topics}\n"
            text += f"📝 <code>{safe_msg}</code>\n\n"

    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"mtlogpage_{topic_filter}_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"mtlogpage_{topic_filter}_{page + 1}"))

    reply_markup = _build_mtlog_filter_markup(nav_buttons=nav_buttons)
    return with_menu_timestamp(text), reply_markup


async def cmd_mtlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /mtlog - Lihat log dari MikroTik dengan filter."""
    user = update.effective_user

    if await _check_access(update, user, "/mtlog"): return

    topic_filter = "all"
    first_arg = _get_first_context_arg(context)
    if first_arg:
        topic_filter = first_arg
    elif update.callback_query and update.callback_query.data.startswith('logfilter_'):
        topic_filter = update.callback_query.data.replace('logfilter_', '')

    msg = None
    try:
        if update.callback_query: 
            await update.callback_query.answer()
            try:
                msg = update.callback_query.message
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
        import asyncio
        logs = await asyncio.to_thread(get_mikrotik_log, 200)

        if not logs:
            text = with_menu_timestamp("ℹ️ Log MikroTik kosong.")
            reply_markup = append_back_button(_build_mtlog_filter_markup())
            await _edit_or_reply_text(
                update,
                text,
                parse_mode='HTML',
                reply_markup=reply_markup,
                target_message=msg,
                allow_fallback_reply=not bool(update.callback_query),
                log_template="Non-fatal UI update error: %s",
            )
            return

        filtered_logs = _filter_mtlog_entries(logs, topic_filter)

        # Simpan ke bot_data untuk pagination
        cache_key = f"mtlog_{topic_filter}"
        set_cache_with_ts(context.bot_data, cache_key, filtered_logs)

        if not filtered_logs:
            text = f"ℹ️ Tidak ada log untuk filter '<b>{topic_filter}</b>' dalam 200 baris terakhir."
            reply_markup = append_back_button(_build_mtlog_filter_markup())
            await _edit_or_reply_text(
                update,
                text,
                parse_mode='HTML',
                reply_markup=reply_markup,
                target_message=msg,
                allow_fallback_reply=not bool(update.callback_query),
                log_template="Non-fatal UI update error: %s",
            )
            return

        text, reply_markup = _format_mtlog_page(filtered_logs, topic_filter, page=0)

        catat(user.id, user.username, f"/mtlog {topic_filter}", "berhasil")
        await _edit_or_reply_text(
            update,
            text,
            parse_mode='HTML',
            reply_markup=append_back_button(reply_markup),
            target_message=msg,
            allow_fallback_reply=not bool(update.callback_query),
            log_template="Non-fatal UI update error: %s",
        )

    except Exception as e:
        catat(user.id, user.username, "/mtlog", f"gagal: {e}")
        await _edit_or_reply_text(
            update,
            generic_error_html("Gagal memuat log MikroTik"),
            parse_mode='HTML',
            reply_markup=get_back_button(),
            target_message=msg,
            allow_fallback_reply=not bool(update.callback_query),
            log_template="Non-fatal UI update error: %s",
        )


async def callback_mtlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback pagination untuk mtlog."""
    query = update.callback_query
    user = query.from_user

    if await _check_access(update, user, "callback_mtlog"):
        return

    data = query.data  # format: mtlogpage_{filter}_{page}
    parts = data.replace('mtlogpage_', '').rsplit('_', 1)
    if len(parts) != 2:
        await query.answer("Data tidak valid.")
        return

    topic_filter = parts[0]
    try:
        page = int(parts[1])
    except ValueError:
        await query.answer("Data tidak valid.")
        return

    cache_key = f"mtlog_{topic_filter}"
    filtered_logs = get_cache_if_fresh(context.bot_data, cache_key, ttl_seconds=900)
    if not filtered_logs:
        await query.answer("Data log sudah kedaluwarsa. Silakan refresh.", show_alert=True)
        return

    text, reply_markup = _format_mtlog_page(filtered_logs, topic_filter, page)
    await query.answer()
    await _edit_or_reply_text(
        update,
        text,
        parse_mode='HTML',
        reply_markup=append_back_button(reply_markup),
        target_editor=query.edit_message_text,
        allow_fallback_reply=False,
    )
