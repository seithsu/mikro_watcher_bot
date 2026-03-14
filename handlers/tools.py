import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.logger import catat
from .utils import (
    _check_access, cek_admin, get_back_button, append_back_button,
    format_bytes_auto, escape_html, generic_error_html, with_menu_timestamp
)
from core.config import PING_COUNT
from mikrotik import (
    ping_host, get_dns_static, add_dns_static, remove_dns_static,
    get_schedulers, set_scheduler_status,
    get_vpn_tunnels, get_firewall_rules, toggle_firewall_rule, _format_bytes,
    get_simple_queues, get_monitored_aps, get_monitored_servers
)
from core import database

logger = logging.getLogger(__name__)


# ============ /ping ============

def _get_ping_hosts():
    """Ambil daftar host untuk ping, pakai nama dari queue jika ada."""
    hosts = {}
    
    # Ambil mapping IP→nama dari queue
    try:
        queues = get_simple_queues()
        queue_names = {}
        for q in queues:
            target = q.get('target', '')
            if '/' in target:
                ip_only = target.split('/')[0]
                queue_names[ip_only] = q.get('name', ip_only)
    except Exception:
        queue_names = {}
    
    # Servers & APs — gunakan nama queue jika ada
    current_aps = get_monitored_aps()
    current_servers = get_monitored_servers()
    for label, ip in {**current_servers, **current_aps}.items():
        display_name = queue_names.get(ip, label)
        hosts[display_name] = ip
    
    # Queue entries yang belum ada
    for ip, name in queue_names.items():
        if ip not in hosts.values():
            hosts[name] = ip
    
    # Default external
    hosts['Internet (1.1.1.1)'] = '1.1.1.1'
    hosts['DNS Google (8.8.8.8)'] = '8.8.8.8'
    
    return hosts


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /ping - Ping host dari router."""
    user = update.effective_user
    if await _check_access(update, user, "/ping"): return

    if update.callback_query:
        await update.callback_query.answer()

    # Jika ada argumen, langsung ping
    if context.args:
        target = context.args[0]
        await _execute_ping(update, context, target)
        return

    # Tanpa argumen: tampilkan daftar host
    all_hosts = await asyncio.to_thread(_get_ping_hosts)
    keyboard = []
    row = []
    for name, ip in all_hosts.items():
        row.append(InlineKeyboardButton(f"{name}", callback_data=f"ping_{ip}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = with_menu_timestamp("🏓 <b>Ping dari Router</b>\n\nPilih target atau ketik <code>/ping [IP/hostname]</code>")

    if update.callback_query:
        try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
    else:
        await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))


async def callback_config_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle tombol Reset Semua Data dari menu /config.

    Dua step:
    - config_reset_confirm  → tampilkan konfirmasi
    - config_reset_execute  → eksekusi hapus semua data
    """
    query = update.callback_query
    user = query.from_user

    if await _check_access(update, user, "callback_config_reset"):
        return

    data = query.data

    if data == 'config_reset_confirm':
        await query.answer()
        text = (
            "⚠️ <b>KONFIRMASI RESET SEMUA DATA</b>\n\n"
            "Ini akan menghapus:\n"
            "• Semua data metrics (CPU, RAM, Traffic, dll)\n"
            "• Semua data incidents & uptime statistik\n"
            "• Semua audit log\n\n"
            "<b>Data .env dan konfigurasi TIDAK akan terpengaruh.</b>\n\n"
            "Apakah Anda yakin?"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ya, Reset Data", callback_data="config_reset_execute"),
                InlineKeyboardButton("❌ Batal", callback_data="cmd_config"),
            ]
        ])
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    elif data == 'config_reset_execute':
        await query.answer("⏳ Mereset data...", show_alert=False)
        try:
            await asyncio.to_thread(database.reset_all_data)
            catat(user.id, user.username, "/config reset-data", "berhasil")
            text = (
                "✅ <b>Reset Berhasil!</b>\n\n"
                "Semua data metrik, insiden, dan audit log telah dihapus.\n"
                "Bot siap mulai mengumpulkan data baru."
            )
        except Exception as e:
            catat(user.id, user.username, "/config reset-data", f"error: {e}")
            text = generic_error_html("Reset data gagal")

        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_back_button())
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
async def callback_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):

    """Handle callback ping host."""
    query = update.callback_query
    user = query.from_user
    if await _check_access(update, user, "callback_ping"):
        return

    target = query.data.replace('ping_', '')
    await query.answer(f"Pinging {target}...")
    await _execute_ping(update, context, target)


async def _execute_ping(update, context, target):
    """Eksekusi ping dan tampilkan hasil."""
    user = update.effective_user
    msg = update.callback_query.message if update.callback_query else update.effective_message

    # Edit pesan yang ada (bukan kirim baru)
    loading_text = f"🏓 <b>Pinging {target}...</b>\n<i>Menunggu respons ({PING_COUNT} paket)...</i>"
    try:
        await msg.edit_text(loading_text, parse_mode='HTML')
    except Exception:
        msg = await msg.reply_text(loading_text, parse_mode='HTML')

    try:
        result = await asyncio.to_thread(ping_host, target, PING_COUNT)

        is_ok = result.get('received', 0) > 0
        icon = "✅" if is_ok else "❌"
        status_text = "OK" if is_ok else "FAIL"
        loss_pct = result.get('loss', 100)
        avg_rtt = result.get('avg_rtt', 0)
        text = (
            f"{icon} <b>Ping Result — {result.get('host', target)}</b>\n"
            f"{'━' * 25}\n\n"
            f"📤 Sent: {result.get('sent', 0)}\n"
            f"📥 Received: {result.get('received', 0)}\n"
            f"📉 Loss: {loss_pct}%\n"
            f"⏱️ RTT: {avg_rtt}ms\n"
            f"📌 Status: <b>{status_text}</b>"
        )
        catat(user.id, user.username, f"/ping {target}", "berhasil")
    except Exception as e:
        text = generic_error_html("Ping gagal")
        catat(user.id, user.username, f"/ping {target}", f"error: {e}")

    keyboard = [
        [InlineKeyboardButton("🏓 Ping Lagi", callback_data="cmd_ping")]
    ]
    try:
        await msg.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(InlineKeyboardMarkup(keyboard)))
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
# ============ /dns ============

async def cmd_dns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /dns - Kelola DNS static."""
    user = update.effective_user
    if await _check_access(update, user, "/dns"): return

    if update.callback_query:
        await update.callback_query.answer()

    try:
        entries = await asyncio.to_thread(get_dns_static)

        if not entries:
            text = with_menu_timestamp("📡 <b>DNS Static</b>\n\n<i>Tidak ada entry DNS static.</i>")
        else:
            context.bot_data['dns_entries'] = entries
            text, reply_markup = _format_dns_page(entries, 0)
            catat(user.id, user.username, "/dns", "berhasil")
            if update.callback_query:
                try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
                except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
            else:
                await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            return

        keyboard = [[InlineKeyboardButton("➕ Add DNS", callback_data="dns_add_prompt")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        catat(user.id, user.username, "/dns", "berhasil")
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))

    except Exception as e:
        catat(user.id, user.username, "/dns", f"error: {e}")
        text = generic_error_html("Gagal memuat DNS static")
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=get_back_button())
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())


def _format_dns_page(entries, page=0, per_page=10):
    """Format halaman DNS entries."""
    total = len(entries)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = min(start + per_page, total)

    text = (
        f"📡 <b>DNS Static Entries</b>\n"
        f"Total: {total} | Hal {page + 1}/{total_pages}\n"
        f"{'━' * 25}\n\n"
    )

    for i, e in enumerate(entries[start:end], start + 1):
        status = "🔴" if e['disabled'] else "🟢"
        comment = f" ({e['comment']})" if e['comment'] else ""
        text += f"{status} <b>{i}.</b> <code>{e['name']}</code> → {e['address']}{comment}\n"

    keyboard = []
    # Nav
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"dnspage_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"dnspage_{page + 1}"))
    if nav:
        keyboard.append(nav)

    # Delete buttons (for current page entries)
    del_row = []
    for i, e in enumerate(entries[start:end], start):
        del_row.append(InlineKeyboardButton(f"🗑️ {i+1}", callback_data=f"dnsdel_{e['id']}"))
        if len(del_row) == 5:
            keyboard.append(del_row)
            del_row = []
    if del_row:
        keyboard.append(del_row)

    keyboard.append([InlineKeyboardButton("➕ Add DNS", callback_data="dns_add_prompt")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="cmd_dns")])

    return with_menu_timestamp(text), InlineKeyboardMarkup(keyboard)


async def callback_dns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle semua DNS callback."""
    query = update.callback_query
    user = query.from_user
    if await _check_access(update, user, "callback_dns"):
        return

    data = query.data

    if data.startswith('dnspage_'):
        page = int(data.replace('dnspage_', ''))
        entries = context.bot_data.get('dns_entries', [])
        if not entries:
            await query.answer("Data expired. Silakan /dns lagi.", show_alert=True)
            return
        text, reply_markup = _format_dns_page(entries, page)
        await query.answer()
        try: await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as e: logger.debug("Non-fatal UI update error: %s", e)

    elif data.startswith('dnsdel_'):
        entry_id = data.replace('dnsdel_', '')
        await query.answer("Menghapus entry...")
        try:
            await asyncio.to_thread(remove_dns_static, entry_id)
            catat(user.id, user.username, f"/dns delete {entry_id}", "berhasil")
            # Refresh
            entries = await asyncio.to_thread(get_dns_static)
            context.bot_data['dns_entries'] = entries
            if entries:
                text, reply_markup = _format_dns_page(entries, 0)
            else:
                text = with_menu_timestamp("📡 <b>DNS Static</b>\n\n<i>Tidak ada entry tersisa.</i>")
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add DNS", callback_data="dns_add_prompt")]])
            try: await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        except Exception as e:
            try:
                await query.edit_message_text(
                    generic_error_html("Gagal menghapus DNS"),
                    parse_mode='HTML',
                    reply_markup=get_back_button()
                )
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)

    elif data == 'dns_add_prompt':
        await query.answer()
        text = (
            "📡 <b>Tambah DNS Static</b>\n\n"
            "Kirim pesan dengan format:\n"
            "<code>domain.com 192.168.x.x</code>\n\n"
            "Contoh:\n"
            "<code>simrs.local 192.168.3.10</code>"
        )
        text = with_menu_timestamp(text)
        context.user_data['awaiting_dns_add'] = True
        try: await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_back_button())
        except Exception as e: logger.debug("Non-fatal UI update error: %s", e)

    elif data == 'dns_add_confirm':
        pending = context.user_data.get('pending_dns')
        if not pending:
            await query.answer("Data expired.", show_alert=True)
            return
        await query.answer("Menambahkan...")
        try:
            await asyncio.to_thread(add_dns_static, pending['name'], pending['address'], "Added via Bot")
            catat(user.id, user.username, f"/dns add {pending['name']} {pending['address']}", "berhasil")
            context.user_data.pop('pending_dns', None)
            context.user_data.pop('awaiting_dns_add', None)
            # Refresh
            entries = await asyncio.to_thread(get_dns_static)
            context.bot_data['dns_entries'] = entries
            text, reply_markup = _format_dns_page(entries, 0)
            try: await query.edit_message_text(f"✅ DNS <code>{pending['name']}</code> → {pending['address']} ditambahkan!\n\n" + text,
                                               parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        except Exception as e:
            try:
                await query.edit_message_text(
                    generic_error_html("Gagal menambah DNS"),
                    parse_mode='HTML',
                    reply_markup=get_back_button()
                )
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)


async def handle_dns_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input untuk penambahan DNS."""
    if not context.user_data.get('awaiting_dns_add'):
        return False  # Not handling

    user = update.effective_user
    if not cek_admin(user.id):
        return False

    text = update.message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text(
            "⚠️ Format salah. Gunakan:\n<code>domain.com 192.168.x.x</code>",
            parse_mode='HTML', reply_markup=get_back_button()
        )
        return True

    domain = parts[0]
    address = parts[1]

    context.user_data['pending_dns'] = {'name': domain, 'address': address}
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data="dns_add_confirm"),
            InlineKeyboardButton("❌ Batal", callback_data="cmd_dns")
        ]
    ]
    await update.message.reply_text(
        f"📡 <b>Konfirmasi Tambah DNS</b>\n\n"
        f"Domain: <code>{domain}</code>\n"
        f"Address: <code>{address}</code>\n\n"
        f"Tambahkan?",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return True


# ============ /schedule ============

async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /schedule - Lihat & manage RouterOS scheduler."""
    user = update.effective_user
    if await _check_access(update, user, "/schedule"): return

    if update.callback_query:
        await update.callback_query.answer()

    try:
        scheds = await asyncio.to_thread(get_schedulers)
        context.bot_data['schedulers'] = scheds

        if not scheds:
            text = with_menu_timestamp("📅 <b>Scheduler</b>\n\n<i>Tidak ada scheduler entry.</i>")
            if update.callback_query:
                try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=get_back_button())
                except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
            else:
                await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())
            return

        text, reply_markup = _format_schedule_page(scheds, 0)
        catat(user.id, user.username, "/schedule", "berhasil")
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))

    except Exception as e:
        catat(user.id, user.username, "/schedule", f"error: {e}")
        text = generic_error_html("Gagal memuat scheduler")
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=get_back_button())
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())


def _format_schedule_page(scheds, page=0, per_page=10):
    """Format halaman scheduler."""
    total = len(scheds)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = min(start + per_page, total)

    text = (
        f"📅 <b>RouterOS Scheduler</b>\n"
        f"Total: {total} | Hal {page + 1}/{total_pages}\n"
        f"{'━' * 25}\n\n"
    )

    for i, s in enumerate(scheds[start:end], start + 1):
        status = "🔴" if s['disabled'] else "🟢"
        interval = s['interval'] if s['interval'] else "one-time"
        event_preview = s['on_event'][:40] + "..." if len(s['on_event']) > 40 else s['on_event']
        text += (
            f"{status} <b>{i}. {s['name']}</b>\n"
            f"   ⏰ Interval: {interval}\n"
            f"   📜 Event: <code>{event_preview}</code>\n"
            f"   🔄 Run count: {s['run_count']}\n\n"
        )

    keyboard = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"schedpage_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"schedpage_{page + 1}"))
    if nav:
        keyboard.append(nav)

    # Toggle buttons
    toggle_row = []
    for i, s in enumerate(scheds[start:end], start):
        icon = "🟢" if s['disabled'] else "🔴"  # Opposite: click to toggle
        toggle_row.append(InlineKeyboardButton(f"{icon} {i+1}", callback_data=f"schedtoggle_{s['id']}"))
        if len(toggle_row) == 5:
            keyboard.append(toggle_row)
            toggle_row = []
    if toggle_row:
        keyboard.append(toggle_row)

    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="cmd_schedule")])

    return with_menu_timestamp(text), InlineKeyboardMarkup(keyboard)


async def callback_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle scheduler callbacks."""
    query = update.callback_query
    user = query.from_user
    if await _check_access(update, user, "callback_schedule"):
        return

    data = query.data

    if data.startswith('schedpage_'):
        try:
            page = int(data.replace('schedpage_', ''))
        except ValueError:
            await query.answer("Data tidak valid.", show_alert=True)
            return
        scheds = context.bot_data.get('schedulers', [])
        if not scheds:
            await query.answer("Data expired. Silakan /schedule lagi.", show_alert=True)
            return
        text, reply_markup = _format_schedule_page(scheds, page)
        await query.answer()
        try: await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as e: logger.debug("Non-fatal UI update error: %s", e)

    elif data.startswith('schedtoggle_'):
        sched_id = data.replace('schedtoggle_', '')
        scheds = context.bot_data.get('schedulers', [])
        target_sched = next((s for s in scheds if s['id'] == sched_id), None)

        if not target_sched:
            await query.answer("Entry tidak ditemukan.", show_alert=True)
            return

        new_disabled = not target_sched['disabled']
        action = "disable" if new_disabled else "enable"
        await query.answer()
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ya, lanjutkan", callback_data=f"schedexec_{sched_id}"),
                InlineKeyboardButton("❌ Batal", callback_data="cmd_schedule"),
            ]
        ])
        text = (
            "⚠️ <b>Konfirmasi Perubahan Scheduler</b>\n\n"
            f"Entry: <b>{escape_html(target_sched['name'])}</b>\n"
            f"Aksi: <b>{action.upper()}</b>\n\n"
            "Lanjutkan?"
        )
        text = with_menu_timestamp(text)
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    elif data.startswith('schedexec_'):
        sched_id = data.replace('schedexec_', '')
        scheds = context.bot_data.get('schedulers', [])
        target_sched = next((s for s in scheds if s['id'] == sched_id), None)

        if not target_sched:
            await query.answer("Entry tidak ditemukan.", show_alert=True)
            return

        new_disabled = not target_sched['disabled']
        await query.answer(f"{'Disabling' if new_disabled else 'Enabling'} {target_sched['name']}...")

        try:
            await asyncio.to_thread(set_scheduler_status, sched_id, new_disabled)
            catat(user.id, user.username, f"/schedule toggle {target_sched['name']}", f"{'disabled' if new_disabled else 'enabled'}")
            scheds = await asyncio.to_thread(get_schedulers)
            context.bot_data['schedulers'] = scheds
            text, reply_markup = _format_schedule_page(scheds, 0)
            try: await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        except Exception:
            try:
                await query.edit_message_text(
                    generic_error_html("Gagal mengubah scheduler"),
                    parse_mode='HTML',
                    reply_markup=get_back_button()
                )
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
# ============ /vpn ============

async def cmd_vpn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /vpn - Monitor VPN tunnels."""
    user = update.effective_user
    if await _check_access(update, user, "/vpn"): return

    if update.callback_query:
        await update.callback_query.answer()

    try:
        tunnels = await asyncio.to_thread(get_vpn_tunnels)

        if not tunnels:
            text = (
                "🔒 <b>VPN Tunnels</b>\n\n"
                "<i>Tidak ada tunnel VPN yang terkonfigurasi.</i>\n\n"
                "Tunnel yang terpantau: L2TP, PPTP, SSTP, OVPN (client & server)."
            )
        else:
            text = f"🔒 <b>VPN Tunnels ({len(tunnels)})</b>\n{'━' * 25}\n\n"
            for t in tunnels:
                status = "🟢 UP" if t['running'] else ("🔴 DOWN" if not t['disabled'] else "⚪ DISABLED")
                text += (
                    f"{status} <b>{t['name']}</b> [{t['type']}]\n"
                    f"   🌐 Remote: {t['remote'] or '-'}\n"
                )
                if t['uptime']:
                    text += f"   ⏱️ Uptime: {t['uptime']}\n"
                if t['comment']:
                    text += f"   💬 {t['comment']}\n"
                text += "\n"
        text = with_menu_timestamp(text)

        catat(user.id, user.username, "/vpn", "berhasil")
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="cmd_vpn")]
        ])
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))

    except Exception as e:
        catat(user.id, user.username, "/vpn", f"error: {e}")
        text = generic_error_html("Gagal memuat status VPN")
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=get_back_button())
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())


# ============ /firewall ============

async def cmd_firewall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /firewall - Lihat & manage firewall rules."""
    user = update.effective_user
    if await _check_access(update, user, "/firewall"): return

    if update.callback_query:
        await update.callback_query.answer()

    chain_type = context.args[0] if context.args and context.args[0] in ('filter', 'nat') else 'filter'

    try:
        rules = await asyncio.to_thread(get_firewall_rules, chain_type)
        context.bot_data[f'fw_{chain_type}'] = rules

        if not rules:
            text = with_menu_timestamp(f"🛡️ <b>Firewall ({chain_type.upper()})</b>\n\n<i>Tidak ada rule.</i>")
            if update.callback_query:
                try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=get_back_button())
                except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
            else:
                await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())
            return

        text, reply_markup = _format_firewall_page(rules, chain_type, 0)
        catat(user.id, user.username, f"/firewall {chain_type}", "berhasil")
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))

    except Exception as e:
        catat(user.id, user.username, "/firewall", f"error: {e}")
        text = generic_error_html("Gagal memuat firewall")
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=get_back_button())
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())


def _format_firewall_page(rules, chain_type, page=0, per_page=8):
    """Format halaman firewall rules."""
    total = len(rules)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = min(start + per_page, total)

    text = (
        f"🛡️ <b>Firewall {chain_type.upper()} Rules</b>\n"
        f"Total: {total} | Hal {page + 1}/{total_pages}\n"
        f"{'━' * 25}\n\n"
    )

    for i, r in enumerate(rules[start:end], start + 1):
        status = "🔴" if r['disabled'] else "🟢"
        comment = r['comment'] or r['action']
        src = r['src_address'] or '*'
        dst = r['dst_address'] or '*'
        proto = r['protocol'] or '*'
        port = r['dst_port'] or '*'
        hits = _format_bytes(int(r['bytes'])) if int(r['bytes']) > 0 else '0B'

        text += (
            f"{status} <b>{i}.</b> [{r['chain']}] {r['action'].upper()}\n"
            f"   {src} → {dst} | {proto}:{port}\n"
            f"   📊 {hits} | 💬 {comment}\n\n"
        )

    keyboard = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"fwpage_{chain_type}_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"fwpage_{chain_type}_{page + 1}"))
    if nav:
        keyboard.append(nav)

    # Toggle buttons
    toggle_row = []
    for i, r in enumerate(rules[start:end], start):
        icon = "🟢" if r['disabled'] else "🔴"
        toggle_row.append(InlineKeyboardButton(f"{icon} {i+1}", callback_data=f"fwtoggle_{chain_type}_{r['id']}"))
        if len(toggle_row) == 5:
            keyboard.append(toggle_row)
            toggle_row = []
    if toggle_row:
        keyboard.append(toggle_row)

    # Chain type switcher
    other = 'nat' if chain_type == 'filter' else 'filter'
    keyboard.append([
        InlineKeyboardButton(f"📋 Switch to {other.upper()}", callback_data=f"fwswitch_{other}"),
        InlineKeyboardButton("🔄 Refresh", callback_data=f"fwswitch_{chain_type}")
    ])

    return with_menu_timestamp(text), InlineKeyboardMarkup(keyboard)


async def callback_firewall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle firewall callbacks."""
    query = update.callback_query
    user = query.from_user
    if await _check_access(update, user, "callback_firewall"):
        return

    data = query.data

    if data.startswith('fwpage_'):
        parts = data.replace('fwpage_', '').rsplit('_', 1)
        chain_type, page = parts[0], int(parts[1])
        rules = context.bot_data.get(f'fw_{chain_type}', [])
        if not rules:
            await query.answer("Data expired.", show_alert=True)
            return
        text, reply_markup = _format_firewall_page(rules, chain_type, page)
        await query.answer()
        try: await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as e: logger.debug("Non-fatal UI update error: %s", e)

    elif data.startswith('fwswitch_'):
        chain_type = data.replace('fwswitch_', '')
        await query.answer(f"Loading {chain_type}...")
        try:
            rules = await asyncio.to_thread(get_firewall_rules, chain_type)
            context.bot_data[f'fw_{chain_type}'] = rules
            if not rules:
                text = with_menu_timestamp(f"🛡️ <b>Firewall ({chain_type.upper()})</b>\n\n<i>Tidak ada rule.</i>")
                try: await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_back_button())
                except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
                return
            text, reply_markup = _format_firewall_page(rules, chain_type, 0)
            try: await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        except Exception:
            try:
                await query.edit_message_text(
                    generic_error_html("Gagal memuat rule firewall"),
                    parse_mode='HTML',
                    reply_markup=get_back_button()
                )
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
    elif data.startswith('fwtoggle_'):
        # fwtoggle_filter_*123 or fwtoggle_nat_*123
        parts = data.replace('fwtoggle_', '').split('_', 1)
        if len(parts) != 2:
            await query.answer("Data tidak valid.", show_alert=True)
            return
        chain_type = parts[0]
        rule_id = parts[1]
        rules = context.bot_data.get(f'fw_{chain_type}', [])
        target_rule = next((r for r in rules if r['id'] == rule_id), None)
        if not target_rule:
            await query.answer("Rule tidak ditemukan.", show_alert=True)
            return

        new_disabled = not target_rule['disabled']
        action = "disable" if new_disabled else "enable"
        await query.answer()
        text = (
            "⚠️ <b>Konfirmasi Toggle Firewall Rule</b>\n\n"
            f"Chain: <b>{escape_html(chain_type.upper())}</b>\n"
            f"Rule ID: <code>{escape_html(rule_id)}</code>\n"
            f"Aksi: <b>{action.upper()}</b>\n\n"
            "Lanjutkan?"
        )
        text = with_menu_timestamp(text)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ya, lanjutkan", callback_data=f"fwexec_{chain_type}_{rule_id}"),
                InlineKeyboardButton("❌ Batal", callback_data=f"fwswitch_{chain_type}"),
            ]
        ])
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    elif data.startswith('fwexec_'):
        parts = data.replace('fwexec_', '').split('_', 1)
        if len(parts) != 2:
            await query.answer("Data tidak valid.", show_alert=True)
            return
        chain_type = parts[0]
        rule_id = parts[1]
        rules = context.bot_data.get(f'fw_{chain_type}', [])
        target_rule = next((r for r in rules if r['id'] == rule_id), None)
        if not target_rule:
            await query.answer("Rule tidak ditemukan.", show_alert=True)
            return

        new_disabled = not target_rule['disabled']
        await query.answer(f"{'Disabling' if new_disabled else 'Enabling'} rule...")
        try:
            await asyncio.to_thread(toggle_firewall_rule, rule_id, chain_type, new_disabled)
            catat(user.id, user.username, f"/firewall toggle {chain_type} #{rule_id}", f"{'disabled' if new_disabled else 'enabled'}")
            rules = await asyncio.to_thread(get_firewall_rules, chain_type)
            context.bot_data[f'fw_{chain_type}'] = rules
            text, reply_markup = _format_firewall_page(rules, chain_type, 0)
            try: await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        except Exception:
            try:
                await query.edit_message_text(
                    generic_error_html("Gagal mengubah firewall rule"),
                    parse_mode='HTML',
                    reply_markup=get_back_button()
                )
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
# ============ /uptime ============

async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /uptime - Laporan uptime per host."""
    user = update.effective_user
    if await _check_access(update, user, "/uptime"): return

    if update.callback_query:
        await update.callback_query.answer()

    days = 7
    if context.args:
        try: days = int(context.args[0])
        except ValueError: pass
    days = min(days, 90)  # Max 90 hari

    try:
        stats = await asyncio.to_thread(database.get_uptime_stats, days)

        if not stats:
            text = with_menu_timestamp(f"📊 <b>Uptime Report ({days} hari)</b>\n\n<i>Tidak ada data insiden.</i>")
        else:
            text = (
                f"📊 <b>Uptime Report ({days} hari terakhir)</b>\n"
                f"{'━' * 28}\n\n"
            )
            for host, data in stats.items():
                pct = data['uptime_pct']
                if pct >= 99:
                    icon = "🟢"
                elif pct >= 95:
                    icon = "🟡"
                else:
                    icon = "🔴"

                text += (
                    f"{icon} <b>{host}</b>\n"
                    f"   Uptime: {pct:.2f}%\n"
                    f"   Insiden: {data['incident_count']}x\n"
                    f"   Total Down: {data['total_downtime_str']}\n\n"
                )
            text = with_menu_timestamp(text)

        keyboard = [
            [
                InlineKeyboardButton("7 Hari", callback_data="uptime_7"),
                InlineKeyboardButton("30 Hari", callback_data="uptime_30"),
                InlineKeyboardButton("90 Hari", callback_data="uptime_90"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        catat(user.id, user.username, f"/uptime {days}", "berhasil")
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))

    except Exception as e:
        catat(user.id, user.username, "/uptime", f"error: {e}")
        text = generic_error_html("Gagal memuat laporan uptime")
        if update.callback_query:
            try: await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=get_back_button())
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())


async def callback_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uptime period callbacks."""
    query = update.callback_query
    user = query.from_user
    if await _check_access(update, user, "callback_uptime"):
        return

    days = int(query.data.replace('uptime_', ''))
    context.args = [str(days)]
    await cmd_uptime(update, context)


# ============ /config ============

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /config - Lihat/ubah konfigurasi bot runtime.
    
    Usage:
        /config              → Tampilkan semua config
        /config set KEY VAL  → Set nilai config
        /config reset KEY    → Reset ke default .env
    """
    user = update.effective_user
    if await _check_access(update, user, "/config"): return

    if update.callback_query:
        await update.callback_query.answer()

    args = context.args or []
    
    # SET config
    if len(args) >= 3 and args[0].lower() == 'set':
        key = args[1].upper()
        value = args[2]
        
        from services.config_manager import set_config
        success, msg = set_config(key, value, user.id, user.username)
        
        catat(user.id, user.username, f"/config set {key} {value}", "berhasil" if success else "gagal")
        
        text = f"⚙️ <b>CONFIG SET</b>\n\n{msg}"
        if update.callback_query:
            try: await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=get_back_button())
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())
        return
    
    # RESET config
    if len(args) >= 2 and args[0].lower() == 'reset':
        key = args[1].upper()
        
        from services.config_manager import reset_config
        success, msg = reset_config(key, user.id, user.username)
        
        catat(user.id, user.username, f"/config reset {key}", "berhasil" if success else "gagal")
        
        text = f"⚙️ <b>CONFIG RESET</b>\n\n{msg}"
        if update.callback_query:
            try: await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=get_back_button())
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())
        return
    
    # SHOW all configs
    from services.config_manager import get_all_configs
    all_configs = get_all_configs()
    
    text = "⚙️ <b>KONFIGURASI BOT</b>\n"
    text += "━" * 25 + "\n\n"
    
    for category, items in all_configs.items():
        text += f"<b>{category}</b>\n"
        for item in items:
            icon = "🔧" if item['is_overridden'] else "📌"
            override_tag = " <i>(custom)</i>" if item['is_overridden'] else ""
            text += f"  {icon} {item['label']}: <b>{item['value']}</b>{override_tag}\n"
            text += f"     <code>{item['key']}</code>\n"
        text += "\n"
    
    text += (
        "━" * 25 + "\n"
        "<i>Cara set config (angka):</i>\n"
        "<code>/config set CPU_THRESHOLD 90</code>\n"
        "<code>/config set PING_COUNT 6</code>\n"
        "<i>Cara set config (boolean):</i>\n"
        "<code>/config set TOP_BW_ALERT_ENABLED false</code>\n"
        "<code>/config set MONITOR_VPN_ENABLED false</code>\n"
        "<i>Nilai boolean valid:</i> true/false, 1/0, yes/no, on/off\n"
        "<i>Reset config:</i>\n"
        "<code>/config reset CPU_THRESHOLD</code>"
    )
    text = with_menu_timestamp(text)
    
    catat(user.id, user.username, "/config", "berhasil")
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="cmd_config")],
        [InlineKeyboardButton("🗑️ Reset Semua Data", callback_data="config_reset_confirm")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        try: await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
    else:
        await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
