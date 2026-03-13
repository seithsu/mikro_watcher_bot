import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.logger import catat
from .utils import (
    _check_access, get_back_button, append_back_button,
    escape_html, generic_error_html,
    set_cache_with_ts, get_cache_if_fresh, put_callback_payload, get_callback_payload,
    with_menu_timestamp
)
from mikrotik import (
    get_interfaces, get_traffic, get_dhcp_leases,
    run_ip_scan, find_free_ips, send_wol, get_ip_addresses
)

logger = logging.getLogger(__name__)


async def cmd_interface(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /interface - List semua interface."""
    user = update.effective_user

    if await _check_access(update, user, "/interface"):
        return

    if update.callback_query:
        await update.callback_query.answer()
        message_to_edit = update.effective_message
    else:
        message_to_edit = update.effective_message

    try:
        import asyncio
        interfaces = await asyncio.to_thread(get_interfaces)
        
        pesan = "🌐 Pilih interface untuk cek detail:\n"
        keyboard = []
        row = []
        for iface in interfaces:
            status = "🟢" if iface['running'] else "🔴"
            disabled_str = "⚠️ " if not iface['enabled'] else ""
            name = iface['name']

            btn_text = f"{disabled_str}{status} {name}"
            tok = put_callback_payload(context.bot_data, "ifacedetail", name)
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ifacedetailk_{tok}")])
            
        text = with_menu_timestamp(pesan.strip())
        reply_markup = append_back_button(InlineKeyboardMarkup(keyboard))

        catat(user.id, user.username, "/interface", "berhasil")
        try:
             await message_to_edit.edit_text(text, parse_mode='HTML', reply_markup=reply_markup)
        except Exception:
             await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)

    except Exception as e:
        catat(user.id, user.username, "/interface", f"gagal: {e}")
        safe_err = escape_html(e)
        try:
             await message_to_edit.edit_text(f"❌ <b>Error:</b> {safe_err}", parse_mode='HTML', reply_markup=get_back_button())
        except Exception:
             await update.effective_message.reply_text(f"❌ <b>Error:</b> {safe_err}", parse_mode='HTML', reply_markup=get_back_button())


async def callback_ifacedetail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback untuk melihat detail spesifik sebuah interface."""
    query = update.callback_query
    user = query.from_user

    if await _check_access(update, user, "callback_ifacedetail"):
        return
    
    await query.answer()
    data = query.data
    if data.startswith('ifacedetailk_'):
        token = data.replace('ifacedetailk_', '')
        iface_name = get_callback_payload(context.bot_data, "ifacedetail", token, ttl_seconds=1800)
        if not iface_name:
            await query.answer("Data kedaluwarsa. Buka ulang menu interface.", show_alert=True)
            return
    else:
        iface_name = data.replace('ifacedetail_', '')
    
    try:
        import asyncio
        interfaces = await asyncio.to_thread(get_interfaces)
        
        # Cari interface yang dimaksud
        detail = None
        for i in interfaces:
            if i['name'] == iface_name:
                detail = i
                break
                
        if not detail:
            safe_iface = escape_html(iface_name)
            await query.edit_message_text(
                f"❌ Interface <b>{safe_iface}</b> tidak ditemukan.",
                parse_mode='HTML',
                reply_markup=get_back_button()
            )
            return
            
        status_icon = "🟢 UP" if detail['running'] else "🔴 DOWN"
        disabled_str = "⚠️ DISABLED" if not detail['enabled'] else "✅ ENABLED"
        tipe = escape_html(str(detail['type']).upper())
        mac = escape_html(detail.get('mac-address', 'N/A'))
        mtu = escape_html(detail.get('actual-mtu', 'N/A'))
        rx_err = detail.get('rx_error', 0)
        tx_err = detail.get('tx_error', 0)
        rx_drop = detail.get('rx_drop', 0)
        tx_drop = detail.get('tx_drop', 0)
        
        note = ""
        if detail.get('comment'):
            note = f"\n📝 <i>Catatan: {escape_html(detail.get('comment'))}</i>"
        iface_name_safe = escape_html(iface_name.upper())
        
        pesan = (
            f"🌐 <b>INFO DEVICE: {iface_name_safe}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Status Link</b> : {status_icon}\n"
            f"<b>Status Admin</b>: {disabled_str}\n"
            f"<b>Tipe Port</b>   : <code>{tipe}</code>\n"
            f"<b>MAC Address</b> : <code>{mac}</code>\n"
            f"<b>MTU</b>         : <code>{mtu}</code>\n\n"
            f"⚠️ <b>Statistik Packet Jumps:</b>\n"
            f"┣ <b>RX Error:</b> <code>{rx_err}</code>\n"
            f"┣ <b>TX Error:</b> <code>{tx_err}</code>\n"
            f"┣ <b>RX Drop:</b>  <code>{rx_drop}</code>\n"
            f"┗ <b>TX Drop:</b>  <code>{tx_drop}</code>"
            f"{note}"
        )
        
        # Tambahkan tombol untuk langsung cek traffic atau kembali
        tok_detail = put_callback_payload(context.bot_data, "ifacedetail", iface_name)
        tok_traffic = put_callback_payload(context.bot_data, "traffic", iface_name)
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Detail", callback_data=f"ifacedetailk_{tok_detail}")],
            [InlineKeyboardButton(f"📈 Cek Traffic {iface_name}", callback_data=f"traffick_{tok_traffic}")],
            [InlineKeyboardButton("🔙 Kembali ke List Interface", callback_data="cmd_interface")],
            [InlineKeyboardButton("🔙 Menu Utama", callback_data="cmd_start")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(pesan, parse_mode='HTML', reply_markup=reply_markup)
        except Exception as err:
            if 'not modified' in str(err).lower():
                await query.answer("Info interface belum berubah", show_alert=False)
                return
            raise err
        
    except Exception as e:
        catat(user.id, user.username, f"/interface detail {iface_name}", f"gagal: {e}")
        try: 
            await query.edit_message_text(
                generic_error_html("Gagal ambil detail interface"),
                parse_mode='HTML',
                reply_markup=get_back_button()
            )
        except Exception as e: logger.debug("Non-fatal UI update error: %s", e)


async def cmd_traffic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /traffic [nama] - Cek traffic per interface."""
    user = update.effective_user

    if await _check_access(update, user, "/traffic"):
        return

    interface_name = None
    if update.callback_query and update.callback_query.data.startswith('traffic_'):
        interface_name = update.callback_query.data.replace('traffic_', '')
    elif update.callback_query and update.callback_query.data.startswith('traffick_'):
        token = update.callback_query.data.replace('traffick_', '')
        interface_name = get_callback_payload(context.bot_data, "traffic", token, ttl_seconds=1800)
        if not interface_name:
            await update.callback_query.answer("Data kedaluwarsa. Buka ulang menu traffic.", show_alert=True)
            return
    elif context.args:
        interface_name = context.args[0]

    if not interface_name:
        if update.callback_query:
            await update.callback_query.answer()
            
        try:
             import asyncio
             interfaces = await asyncio.to_thread(get_interfaces)
             keyboard = []
             for iface in interfaces:
                 name = iface['name']
                 tok = put_callback_payload(context.bot_data, "traffic", name)
                 keyboard.append([InlineKeyboardButton(f"📊 {name}", callback_data=f"traffick_{tok}")])
                 
             if not keyboard:
                 await update.effective_message.reply_text("❌ Tidak ada interface ditemukan.", reply_markup=get_back_button())
                 return
                 
             reply_markup = InlineKeyboardMarkup(keyboard)
             pesan_traffic = with_menu_timestamp("🌐 Pilih interface untuk cek traffic:")
             if update.callback_query:
                 try:
                     await update.callback_query.message.edit_text(pesan_traffic, reply_markup=append_back_button(reply_markup))
                     return
                 except Exception as e:
                     logger.debug("Suppressed non-fatal exception: %s", e)
             await update.effective_message.reply_text(pesan_traffic, reply_markup=append_back_button(reply_markup))
             return
        except Exception as e:
             await update.effective_message.reply_text(
                 generic_error_html("Gagal mengambil daftar interface"),
                 parse_mode='HTML',
                 reply_markup=get_back_button()
             )
             return

    import re
    if not re.match(r"^[a-zA-Z0-9_\-\s<>]+$", interface_name):
        await update.effective_message.reply_text("❌ Karakter tidak valid pada nama interface.", reply_markup=get_back_button())
        return

    try:
        msg_load = update.effective_message
        import asyncio
        data = await asyncio.to_thread(get_traffic, interface_name)

        if not data:
            safe_iface = escape_html(interface_name)
            await update.effective_message.reply_text(
                f"❌ Interface <b>{safe_iface}</b> tidak ditemukan!\n\n"
                f"<i>Gunakan /interface untuk melihat nama yang tersedia.</i>",
                parse_mode='HTML', reply_markup=get_back_button()
            )
            return

        data_name_safe = escape_html(data['name'].upper())
        pesan = (
            f"📈 <b>TRAFFIC LIVE: {data_name_safe}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 <b>Download (RX):</b> <code>{data['rx']}</code>\n"
            f"📤 <b>Upload (TX):</b>   <code>{data['tx']}</code>\n\n"
            f"📊 <b>Total Data Terpakai:</b>\n"
            f"┣ RX: <code>{data['rx_bytes']:,} bytes</code>\n"
            f"┗ TX: <code>{data['tx_bytes']:,} bytes</code>"
        )

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Traffic", callback_data=f"traffick_{put_callback_payload(context.bot_data, 'traffic', interface_name)}")],
            [InlineKeyboardButton("🔙 Kembali ke List Interface", callback_data="cmd_traffic")],
            [InlineKeyboardButton("🔙 Menu Utama", callback_data="cmd_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        catat(user.id, user.username, f"/traffic {interface_name}", "berhasil")
        if update.callback_query:
            try:
                await msg_load.edit_text(pesan, parse_mode='HTML', reply_markup=reply_markup)
                return
            except Exception as e:
                if 'not modified' in str(e).lower():
                    return
                pass
        await update.effective_message.reply_text(pesan, parse_mode='HTML', reply_markup=reply_markup)

    except Exception as e:
        catat(user.id, user.username, f"/traffic {interface_name}", f"gagal: {e}")
        if update.callback_query:
            try:
                await msg_load.edit_text(
                    generic_error_html(f"Gagal ambil traffic {interface_name}"),
                    parse_mode='HTML',
                    reply_markup=get_back_button()
                )
                return
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        await update.effective_message.reply_text(
            generic_error_html(f"Gagal ambil traffic {interface_name}"),
            parse_mode='HTML',
            reply_markup=get_back_button()
        )


def _format_scan_page(devices, interface, page, interface_token=None, per_page=10):
    """Format satu halaman hasil scan."""
    total = len(devices)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    
    start = page * per_page
    end = min(start + per_page, total)
    page_devices = devices[start:end]
    
    iface_safe = escape_html(interface)
    text = (
        f"📡 <b>IP Scan: {iface_safe}</b>\n"
        f"Ditemukan: {total} device | Hal {page + 1}/{total_pages}\n"
        f"{'━' * 30}\n\n"
    )
    
    for i, d in enumerate(page_devices, start=start + 1):
        hostname = d.get('hostname', '-')
        if not hostname or hostname == '-':
            hostname = 'No-Name'
        ip_safe = escape_html(d.get('ip', '-'))
        mac_safe = escape_html(d.get('mac', '-'))
        host_safe = escape_html(hostname)
        text += (
            f"<b>{i}.</b> <code>{ip_safe}</code>\n"
            f"   MAC: <code>{mac_safe}</code>\n"
            f"   Host: {host_safe}\n\n"
        )
    text = with_menu_timestamp(text)
    
    if not interface_token:
        # Safety fallback untuk legacy flow: paging dinonaktifkan jika token hilang.
        keyboard = [[InlineKeyboardButton("🔄 Rescan", callback_data="cmd_scan")]]
        return text, InlineKeyboardMarkup(keyboard)

    # Keyboard navigasi
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"scpk_{interface_token}_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"scpk_{interface_token}_{page + 1}"))
    
    keyboard = [nav_buttons] if nav_buttons else []
    keyboard.append([InlineKeyboardButton("🔄 Rescan", callback_data=f"sck_{interface_token}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    return text, reply_markup


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /scan - Scan device via IP Scan per interface."""
    user = update.effective_user
    if await _check_access(update, user, "/scan"):
        return

    if context.args:
        import re
        interface_name = " ".join(context.args)
        if not re.match(r"^[a-zA-Z0-9_\-\s<>]+$", interface_name):
            await update.effective_message.reply_text("❌ Karakter tidak valid pada nama interface.", reply_markup=get_back_button())
            return
        await _do_scan(update, context, interface_name)
        return

    if update.callback_query:
        await update.callback_query.answer()

    try:
        import asyncio
        interfaces = await asyncio.to_thread(get_interfaces)
        keyboard = []
        for iface in interfaces:
            name = iface['name']
            status = "📊" if iface['running'] else "📊"
            tok = put_callback_payload(context.bot_data, "scan_iface", name)
            keyboard.append([InlineKeyboardButton(
                f"{status} {name}", 
                callback_data=f"sck_{tok}"
            )])
        
        if not keyboard:
            await update.effective_message.reply_text("❌ Tidak ada interface ditemukan.", reply_markup=get_back_button())
            return
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        pesan_scan = with_menu_timestamp("🌐 Pilih interface yang ingin di-scan:")
        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(pesan_scan, reply_markup=append_back_button(reply_markup), parse_mode='HTML')
                return
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
        await update.effective_message.reply_text(pesan_scan, reply_markup=append_back_button(reply_markup), parse_mode='HTML')
    except Exception as e:
        await update.effective_message.reply_text(
            generic_error_html("Gagal membuka menu scan"),
            parse_mode='HTML',
            reply_markup=get_back_button()
        )


async def _do_scan(update: Update, context, interface_name, interface_token=None):
    """Eksekusi scan pada interface tertentu."""
    user = update.effective_user
    
    msg_to_edit = None
    if update.callback_query:
        await update.callback_query.answer()
        msg_to_edit = update.callback_query.message
        
    loading_text = (
        f"📡 <b>Scanning {interface_name}...</b>\n\n"
        f"⏳ <i>Real-time IP Scan (±10 detik)...</i>\n"
        f"<i>Metode: librouteros /tool/ip-scan</i>"
    )
    
    if msg_to_edit:
        try:
            await msg_to_edit.edit_text(loading_text, parse_mode='HTML')
        except Exception:
            msg_to_edit = await update.effective_message.reply_text(loading_text, parse_mode='HTML')
    else:
        msg_to_edit = await update.effective_message.reply_text(loading_text, parse_mode='HTML')
    
    try:
        import asyncio
        from mikrotik import run_ip_scan
        devices = await asyncio.to_thread(run_ip_scan, interface_name, duration=10)
        
        if not devices:
            await msg_to_edit.edit_text(
                f"📡 <b>Scan selesai: {interface_name}</b>\n\n"
                f"ℹ️ Tidak ada device terdeteksi pada interface ini.",
                parse_mode='HTML', reply_markup=get_back_button()
            )
            return
        
        if not interface_token:
            interface_token = put_callback_payload(context.bot_data, "scan_iface", interface_name)
        scan_key = f"scan_result_tok_{interface_token}"
        set_cache_with_ts(context.bot_data, scan_key, devices)
        
        text, reply_markup = _format_scan_page(devices, interface_name, page=0, interface_token=interface_token)
        await msg_to_edit.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        
        catat(user.id, user.username, f"/scan {interface_name}", f"berhasil ({len(devices)} devices)")
        
    except Exception as e:
        err_str = str(e)
        if '10038' in err_str or 'socket' in err_str.lower():
            pesan_err = f"❌ <b>Scan gagal:</b> Interface <b>{escape_html(interface_name)}</b> sedang tidak aktif (DOWN) atau terputus."
        else:
            pesan_err = generic_error_html(f"Scan {interface_name} gagal")
            
        catat(user.id, user.username, f"/scan {interface_name}", f"gagal: {e}")
        await msg_to_edit.edit_text(pesan_err, parse_mode='HTML', reply_markup=get_back_button())


async def callback_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback scan: interface selection dan pagination."""
    query = update.callback_query
    user = query.from_user

    if await _check_access(update, user, "callback_scan"):
        return
    
    data = query.data
    
    if data.startswith('scpk_'):
        parts = data.replace('scpk_', '').rsplit('_', 1)
        if len(parts) != 2:
            await query.answer("Data tidak valid.")
            return
        token, page_str = parts
        try:
            page = int(page_str)
        except ValueError:
            await query.answer("Data tidak valid.")
            return
        interface_name = get_callback_payload(context.bot_data, "scan_iface", token, ttl_seconds=1800)
        if not interface_name:
            await query.answer("Data scan expired. Silakan rescan.", show_alert=True)
            return
        scan_key = f"scan_result_tok_{token}"
        devices = get_cache_if_fresh(context.bot_data, scan_key, ttl_seconds=1800)
        if not devices:
            await query.answer("Data scan expired. Silakan rescan.", show_alert=True)
            return
        text, reply_markup = _format_scan_page(devices, interface_name, page, interface_token=token)
        await query.answer()
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as e:
            if 'not modified' not in str(e).lower():
                raise
        return

    if data.startswith('scp_'):
        parts = data.replace('scp_', '').rsplit('_', 1)
        if len(parts) != 2:
            await query.answer("Data tidak valid.")
            return
        interface_name, page_str = parts
        try:
            page = int(page_str)
        except ValueError:
            await query.answer("Data tidak valid.")
            return
        
        scan_key = f"scan_result_{interface_name}"
        devices = get_cache_if_fresh(context.bot_data, scan_key, ttl_seconds=1800)
        if not devices:
            await query.answer("Data scan expired. Silakan rescan.", show_alert=True)
            return
        
        token = put_callback_payload(context.bot_data, "scan_iface", interface_name)
        text, reply_markup = _format_scan_page(devices, interface_name, page, interface_token=token)
        await query.answer()
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as e:
            if 'not modified' not in str(e).lower():
                raise
        return
    
    if data.startswith('sc_'):
        interface_name = data.replace('sc_', '')
        try:
            await query.answer(f"Scanning {interface_name}...")
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
        await _do_scan(update, context, interface_name)
        return

    if data.startswith('sck_'):
        token = data.replace('sck_', '')
        interface_name = get_callback_payload(context.bot_data, "scan_iface", token, ttl_seconds=1800)
        if not interface_name:
            await query.answer("Data scan expired. Silakan pilih interface lagi.", show_alert=True)
            return
        try:
            await query.answer(f"Scanning {interface_name}...")
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
        await _do_scan(update, context, interface_name, interface_token=token)
        return


async def cmd_freeip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /freeip - Mencari IP kosong dalam jaringan."""
    user = update.effective_user
    if await _check_access(update, user, "/freeip"):
        return
        
    try:
        import asyncio
        addrs = await asyncio.to_thread(get_ip_addresses)
        
        keyboard = []
        for addr in addrs:
            network = addr.get('network', '')
            cidr = addr.get('address', '').split('/')[1] if '/' in addr.get('address', '') else '24'
            if network:
                full_network = f"{network}/{cidr}"
                tok = put_callback_payload(context.bot_data, "freeip_net", full_network)
                keyboard.append([InlineKeyboardButton(f"🔍 {full_network}", callback_data=f"freeipk_{tok}")])
                
        if not keyboard:
             await update.effective_message.reply_text("❌ Tidak ada subnet ditemukan di router.", reply_markup=get_back_button())
             return
             
        reply_markup = InlineKeyboardMarkup(keyboard)
        pesan_free = with_menu_timestamp("🔍 <b>IP KOSONG (FREE IP)</b>\nPilih sub-jaringan yang ingin diperiksa:")
        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(pesan_free, reply_markup=append_back_button(reply_markup), parse_mode='HTML')
                return
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
        await update.effective_message.reply_text(pesan_free, reply_markup=append_back_button(reply_markup), parse_mode='HTML')
    except Exception as e:
         await update.effective_message.reply_text(
             generic_error_html("Gagal mengambil daftar IP"),
             parse_mode='HTML',
             reply_markup=get_back_button()
         )


async def callback_freeip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler tombol pilihan network di menu freeip."""
    query = update.callback_query
    data = query.data
    user = update.effective_user

    if await _check_access(update, user, "callback_freeip"):
        return
    
    if data.startswith('fipagek_'):
        parts = data.replace('fipagek_', '').rsplit('_', 1)
        if len(parts) != 2:
            await query.answer("Data tidak valid.")
            return
        token, page_str = parts
        try:
            page = int(page_str)
        except ValueError:
            await query.answer("Data tidak valid.")
            return
        network = get_callback_payload(context.bot_data, "freeip_net", token, ttl_seconds=1800)
        if not network:
            await query.answer("Data waktu scan sudah kedaluwarsa. Silakan Rescan.", show_alert=True)
            return
        cache_key = f"freeip_res_tok_{token}"
        result = get_cache_if_fresh(context.bot_data, cache_key, ttl_seconds=1800)
        if not result:
            await query.answer("Data waktu scan sudah kedaluwarsa. Silakan Rescan.", show_alert=True)
            return
        text, reply_markup = _format_freeip_page(network, result, page, network_token=token)
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
        return

    if data.startswith('fipage_'):
        parts = data.split('_')
        network = parts[1]
        page = int(parts[2])
        
        cache_key = f"freeip_res_{network}"
        result = get_cache_if_fresh(context.bot_data, cache_key, ttl_seconds=1800)
        if not result:
            await query.answer("Data waktu scan sudah kedaluwarsa. Silakan Rescan.", show_alert=True)
            return

        token = put_callback_payload(context.bot_data, "freeip_net", network)
        text, reply_markup = _format_freeip_page(network, result, page, network_token=token)
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
        return

    if data.startswith('freeipk_'):
        token = data.replace('freeipk_', '')
        network = get_callback_payload(context.bot_data, "freeip_net", token, ttl_seconds=1800)
        if not network:
            await query.answer("Data tidak valid/kedaluwarsa.", show_alert=True)
            return
        await _do_freeip(update, context, network, network_token=token)
        return

    network = data.replace('freeip_', '')
    await _do_freeip(update, context, network)


def _format_freeip_page(network, result, page=0, limit=10, network_token=None):
    free_qty = result.get('free_count', 0)
    all_free_ips = result.get('free_ips', [])
    
    total_pages = (free_qty + limit - 1) // limit
    if total_pages == 0:
        total_pages = 1
        
    start_idx = page * limit
    end_idx = start_idx + limit
    page_ips = all_free_ips[start_idx:end_idx]
    
    text = f"✅ <b>ANALISIS SELESAI ({network})</b>\n\n"
    text += f"- Total Host: <b>{result.get('total_hosts')}</b> IP\n"
    text += f"- Sedang Dipakai: <b>{result.get('used_count')}</b> IP\n"
    text += f"- Tersedia (Kosong): <b>{free_qty}</b> IP\n\n"
    
    if free_qty == 0:
        text += "⚠️ <b>PERINGATAN: IP Pool sudah terpakai penuh!</b>"
    else:
        text += f"🟢 <b><u>Mencetak {limit} IP Kosong (Hal {page+1}/{total_pages}):</u></b>\n"
        for ip in page_ips:
            text += f"<code>{ip}</code>\n"
            
    text = with_menu_timestamp(text)

    if not network_token:
        keyboard = [[InlineKeyboardButton("🔄 Rescan", callback_data="cmd_freeip")]]
        return text, InlineKeyboardMarkup(keyboard)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"fipagek_{network_token}_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"fipagek_{network_token}_{page+1}"))
        
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    keyboard.append([InlineKeyboardButton("🔄 Rescan", callback_data=f"freeipk_{network_token}")])
        
    return text, InlineKeyboardMarkup(keyboard)


async def _do_freeip(update: Update, context, network, network_token=None):
    """Eksekusi pencarian IP kosong pada network tertentu."""
    user = update.effective_user
    
    msg_to_edit = None
    if update.callback_query:
        await update.callback_query.answer()
        msg_to_edit = update.callback_query.message
        
    loading_text = (
        f"🔍 <b>Menganalisis IP Kosong di {network}...</b>\n\n"
        f"⏳ <i>Membandingkan DHCP Leases dan ARP Table...</i>\n"
    )
    
    if msg_to_edit:
        loading_msg = msg_to_edit
    else:
        loading_msg = update.effective_message
    
    try:
        import asyncio
        from mikrotik import find_free_ips
        result = await asyncio.to_thread(find_free_ips, network)
        
        if not network_token:
            network_token = put_callback_payload(context.bot_data, "freeip_net", network)
        cache_key = f"freeip_res_tok_{network_token}"
        set_cache_with_ts(context.bot_data, cache_key, result)
        
        text, reply_markup = _format_freeip_page(network, result, page=0, network_token=network_token)
                
        catat(user.id, user.username, f"/freeip {network}", f"berhasil ({result.get('free_count', 0)} IP kosong)")
        try:
             await loading_msg.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        except Exception as err:
             if 'not modified' in str(err).lower():
                 if update.callback_query:
                     await update.callback_query.answer("Hasil rescan masih sama!", show_alert=False)
             else:
                 await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
        
    except Exception as e:
         catat(user.id, user.username, f"/freeip {network}", f"gagal: {e}")
         try:
             await loading_msg.edit_text(
                 generic_error_html("Gagal analisis Free IP"),
                 parse_mode='HTML',
                 reply_markup=get_back_button()
             )
         except Exception:
             await update.effective_message.reply_text(
                 generic_error_html("Gagal analisis Free IP"),
                 parse_mode='HTML',
                 reply_markup=get_back_button()
             )


def _format_dhcp_page(leases, page, per_page=10):
    """Format satu halaman DHCP leases."""
    total = len(leases)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    
    start = page * per_page
    end = min(start + per_page, total)
    page_leases = leases[start:end]
    
    text = (
        f"📋 <b>DHCP Clients ({total})</b>\n"
        f"Halaman {page + 1}/{total_pages}\n"
        f"{'━' * 30}\n\n"
    )
    
    for i, lease in enumerate(page_leases, start=start + 1):
        host = lease['host'] if lease['host'] != 'unknown' else 'No-Name'
        status_tag = "📌" if lease.get('dynamic') == False else "🔄"
        addr_safe = escape_html(lease.get('address', 'Unknown'))
        mac_safe = escape_html(lease.get('mac', 'Unknown'))
        host_safe = escape_html(host)
        
        text += (
            f"{status_tag} <b>{i}. {addr_safe}</b>\n"
            f"   MAC: <code>{mac_safe}</code>\n"
            f"   Host: {host_safe}\n"
        )
        if lease.get('comment'):
            text += f"   Note: <i>{escape_html(lease['comment'])}</i>\n"
        text += "\n"
    
    text += f"<i>📌 = Static | 🔄 = Dynamic</i>"
    text = with_menu_timestamp(text)
    
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"dhcp_page_{page - 1}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"dhcp_page_{page + 1}"))
    
    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"dhcp_page_{page}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    return text, reply_markup


async def cmd_dhcp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /dhcp - List DHCP leases dengan pagination."""
    user = update.effective_user

    if await _check_access(update, user, "/dhcp"):
        return

    try:
        import asyncio
        leases = await asyncio.to_thread(get_dhcp_leases)

        if not leases:
            if update.callback_query:
                await update.callback_query.answer("Tidak ada DHCP lease.", show_alert=True)
            else:
                await update.effective_message.reply_text(
                    "ℹ️ Tidak ada DHCP lease.\nMungkin DHCP server tidak aktif."
                )
            return

        text, reply_markup = _format_dhcp_page(leases, page=0)
        
        catat(user.id, user.username, "/dhcp", "berhasil")
        
        if update.callback_query:
            try:
                await update.callback_query.answer()
                await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
                return
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
        await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))

    except Exception as e:
        catat(user.id, user.username, "/dhcp", f"gagal: {e}")
        if update.callback_query:
            await update.callback_query.answer("Gagal mengambil data DHCP.", show_alert=True)
        await update.effective_message.reply_text(
            generic_error_html("Gagal mengambil data DHCP"),
            parse_mode='HTML',
            reply_markup=get_back_button()
        )


async def callback_dhcp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback pagination DHCP."""
    query = update.callback_query
    user = query.from_user

    if await _check_access(update, user, "callback_dhcp"):
        return
    
    data = query.data
    try:
        page = int(data.replace('dhcp_page_', ''))
    except ValueError:
        await query.answer("Data tidak valid.")
        return
    
    try:
        import asyncio
        leases = await asyncio.to_thread(get_dhcp_leases)
        if not leases:
            await query.answer("Tidak ada DHCP lease.", show_alert=True)
            return
        
        text, reply_markup = _format_dhcp_page(leases, page)
        await query.answer()
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
    except Exception as e:
        await query.answer("Gagal memuat halaman DHCP.", show_alert=True)


async def cmd_wol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perintah /wol - Menampilkan PC yang bisa dihidupkan via Wake on LAN."""
    user = update.effective_user

    if await _check_access(update, user, "/wol"):
        return
        
    try:
        msg = None
        if update.callback_query:
            try:
                msg = update.callback_query.message
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        import asyncio
        leases = await asyncio.to_thread(get_dhcp_leases)
        
        if not leases:
             text = with_menu_timestamp("ℹ️ Tidak ada perangkat tersimpan di DHCP leases.")
             if msg:
                 await msg.edit_text(text, parse_mode='HTML', reply_markup=get_back_button())
             else:
                 await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=get_back_button())
             return
             
        keyboard = []
        for l in leases:
             name = l.get('host', l.get('comment', l['address']))
             mac = l.get('mac')
             
             if not mac or mac == 'unknown': continue
             
             if len(name) > 15: name = name[:15] + ".."
             label = f"💻 {name} ({l['address']})"
             mac_clean = mac.replace(':', '') 
             cb_data = f"wol_{mac_clean}"
             
             context.bot_data[cb_data] = mac
             # W8 FIX: Store timestamp for 5-minute TTL (cek di callback_wol di bot.py)
             context.bot_data[f"ts_{cb_data}"] = time.time()

             
             keyboard.append([InlineKeyboardButton(label, callback_data=cb_data)])
             
        if not keyboard:
             await update.effective_message.reply_text(
                 with_menu_timestamp("❌ Tidak ditemukan MAC Address yang valid."),
                 parse_mode='HTML',
                 reply_markup=get_back_button()
             )
             return
             
        reply_markup = InlineKeyboardMarkup(keyboard)
        catat(user.id, user.username, "/wol", "menunggu-pilihan")
        pesan_wol = with_menu_timestamp(
            "⚡ <b>WAKE ON LAN</b>\n\n"
            "Silakan pilih perangkat yang ingin dihidupkan:"
        )
        if update.callback_query:
            try:
                await msg.edit_text(pesan_wol, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
            except Exception as e: logger.debug("Non-fatal UI update error: %s", e)
        else:
            await update.effective_message.reply_text(pesan_wol, parse_mode='HTML', reply_markup=append_back_button(reply_markup))
    except Exception as e:
        catat(user.id, user.username, "/wol", f"gagal: {e}")
        await update.effective_message.reply_text(
            generic_error_html("Gagal menarik data WoL"),
            parse_mode='HTML',
            reply_markup=get_back_button()
        )
