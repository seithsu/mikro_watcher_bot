# ============================================
# HANDLERS/JOBS - Scheduled Background Jobs
# Daily report dan auto-backup
# Dipindahkan dari bot.py untuk separation of concerns
# ============================================

import logging
import os
import asyncio
from datetime import datetime

from telegram.ext import ContextTypes

import core.config as cfg
from mikrotik import (
    get_status, get_interfaces, get_dhcp_usage_count,
    get_monitored_aps, get_monitored_servers, get_monitored_critical_devices, get_active_critical_device_names,
    get_default_gateway,
    export_router_backup, export_router_backup_ftp,
)
from handlers.utils import read_state_json
from core import database

logger = logging.getLogger(__name__)


async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    """Kirim ringkasan status router otomatis setiap hari."""
    try:
        try:
            cfg.reload_runtime_overrides(min_interval=5)
            cfg.reload_router_env(min_interval=10)
        except Exception as e:
            logger.debug("reload config gagal saat daily_report: %s", e)

        info = await asyncio.to_thread(get_status)

        total_ram = int(info['ram_total'])
        free_ram = int(info['ram_free'])
        ram_pct = ((total_ram - free_ram) / total_ram) * 100 if total_ram > 0 else 0
        ram_free_mb = free_ram / (1024*1024)

        total_disk = int(info['disk_total'])
        free_disk = int(info['disk_free'])
        disk_pct = ((total_disk - free_disk) / total_disk) * 100 if total_disk > 0 else 0

        # Hitung DHCP
        try:
            dhcp_count = await asyncio.to_thread(get_dhcp_usage_count)
        except Exception:
            dhcp_count = 0

        # Cek interface down
        try:
            interfaces, current_aps, current_servers, current_critical = await asyncio.gather(
                asyncio.to_thread(get_interfaces),
                asyncio.to_thread(get_monitored_aps),
                asyncio.to_thread(get_monitored_servers),
                asyncio.to_thread(get_monitored_critical_devices),
            )
            down_ifaces = [
                iface['name'] for iface in interfaces
                if iface['enabled'] and not iface['running'] and iface['name'] not in cfg.MONITOR_IGNORE_IFACE
            ]
            try:
                current_gw_wan = await asyncio.to_thread(get_default_gateway)
            except Exception:
                current_gw_wan = None
        except Exception:
            interfaces = []
            down_ifaces = []
            current_aps = {}
            current_servers = {}
            current_critical = {}
            current_gw_wan = None

        # Statistik Downtime & State Network
        if not current_gw_wan:
            current_gw_wan = cfg.GW_WAN
        try:
            today_incidents = await asyncio.to_thread(database.get_stats_today)
        except Exception:
            today_incidents = 0

        pool_pct = (dhcp_count / cfg.DHCP_POOL_SIZE) * 100 if cfg.DHCP_POOL_SIZE > 0 else 0

        # Load state.json via shared utility
        try:
            state = await asyncio.to_thread(read_state_json)
        except Exception:
            state = {'hosts': {}, 'kategori': '🟢 Data belum tersedia'}

        hosts = state.get('hosts', {})
        kategori_net = state.get('kategori', '\U0001f7e2 NORMAL')

        def up_icon(h): return "\u2705" if hosts.get(h, False) else "\u274c"

        # Interface detail
        indibiz = next((i for i in interfaces if 'indibiz' in i['name'].lower() or 'ether1' in i['name'].lower()), None)
        local = next((i for i in interfaces if 'local' in i['name'].lower() or 'ether2' in i['name'].lower()), None)

        pesan = (
            f"\U0001f4cb <b>LAPORAN HARIAN \u2014 {cfg.INSTITUTION_NAME}</b>\n\n"
            f"<b>\U0001f4e1 STATUS JARINGAN</b>\n"
            f"Kondisi: {kategori_net}\n"
        )

        # Network Matrix
        pesan += f"- Router ({cfg.MIKROTIK_IP}): {up_icon(cfg.MIKROTIK_IP)}\n"
        if current_gw_wan: pesan += f"- WAN Gateway ({current_gw_wan}): {up_icon(current_gw_wan)}\n"
        if cfg.GW_INET: pesan += f"- Internet ({cfg.GW_INET}): {up_icon(cfg.GW_INET)}\n"
        for k, v in current_servers.items():
            pesan += f"- {k} ({v}): {up_icon(v)}\n"
        for k, v in current_critical.items():
            pesan += f"- [Penting] {k} ({v}): {up_icon(v)}\n"
        active_critical_names = await asyncio.to_thread(get_active_critical_device_names)
        unresolved_critical = [n for n in active_critical_names if n not in current_critical]
        for name in unresolved_critical:
            pesan += f"- [Penting] {name}: ⚪ Unknown (hostname DHCP belum ditemukan)\n"

        # AP Summary
        ap_ups = sum(1 for v in current_aps.values() if hosts.get(v, False))
        ap_icon = "\u2705" if ap_ups == len(current_aps) else "\u26a0\ufe0f"
        pesan += f"- WiFi AP: {ap_icon} {ap_ups}/{len(current_aps)} UP\n"
        for ap_name, ap_ip in current_aps.items():
            pesan += f"  \u2514 {ap_ip} ({ap_name}): {up_icon(ap_ip)}\n"

        # DNS check
        dns_icon = "\u2705" if hosts.get('DNS_Resolv', False) else "\u274c"
        pesan += f"- DNS Resolver: {dns_icon}\n"

        pesan += (
            f"\n<b>\U0001f4ca STATISTIK KEANDALAN</b>\n"
            f"- Insiden Downtime (24 Jam): <b>{today_incidents}x</b>\n"
        )

        # Format CPU info
        cpu_info = f"{info['cpu']}%"
        if info.get('cpu_freq'): cpu_info += f" @ {info['cpu_freq']}MHz"
        if info.get('cpu_count', 1) > 1: cpu_info += f" ({info['cpu_count']} cores)"
        
        # Format Sensors
        sensors_str = ""
        sensors = []
        if info.get('cpu_temp'): sensors.append(f"🌡️ {info['cpu_temp']}°C")
        if info.get('voltage'):
            v = info['voltage']
            try:
                v_val = float(v)
                if v_val > 100: v_val = v_val / 10
                sensors.append(f"⚡ {v_val}V")
            except Exception:
                sensors.append(f"⚡ {v}V")
        if sensors:
            sensors_str = f"- Sensors: {' | '.join(sensors)}\n"

        pesan += (
            f"\n<b>💻 SYSTEM RESOURCE</b>\n"
            f"- Uptime: {info['uptime']}\n"
            f"- CPU: {cpu_info}\n"
            f"- RAM: {ram_pct:.1f}% terpakai (Free: {ram_free_mb:.1f} MB)\n"
            f"- Disk: {disk_pct:.1f}% terpakai\n"
            f"{sensors_str}"
        )

        # Interface Health
        pesan += f"\n<b>\U0001f50c INTERFACE HEALTH</b>\n"
        if indibiz:
            irun = "🟢 UP" if indibiz['running'] else "🔴 DOWN"
            pesan += f"- INDIBIZ: {irun} | link-downs: {indibiz.get('link_downs', 0)} | errors rx/tx: {indibiz.get('rx_error', 0)}/{indibiz.get('tx_error', 0)}\n"
        if local:
            lrun = "🟢 UP" if local['running'] else "🔴 DOWN"
            pesan += f"- LOCAL: {lrun} | link-downs: {local.get('link_downs', 0)} | errors rx/tx: {local.get('rx_error', 0)}/{local.get('tx_error', 0)}\n"

        pesan += (
            f"\n<b>\U0001f310 KAPASITAS JARINGAN</b>\n"
            f"- DHCP Pool: {dhcp_count}/{cfg.DHCP_POOL_SIZE} ({pool_pct:.0f}%)\n"
        )

        if down_ifaces:
            pesan += (
                f"\n<b>\u26a0\ufe0f INTERFACE DOWN</b>\n"
                f"- {', '.join(down_ifaces)}\n"
            )

        pesan += f"\n<i>Router: {info['board']} | OS: {info['version']}</i>"

        # Kirim ke semua admin
        for admin_id in cfg.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=pesan, parse_mode='HTML')
            except Exception as e:
                logger.warning(f"Gagal kirim daily report ke {admin_id}: {e}")

    except Exception as e:
        logger.error(f"Daily report gagal: {e}")


async def auto_backup(context: ContextTypes.DEFAULT_TYPE):
    """Jadwal backup otomatis ke telegram."""
    try:
        try:
            cfg.reload_router_env(min_interval=10)
        except Exception as e:
            logger.debug("reload config gagal saat auto_backup: %s", e)

        # Kita backup .rsc karena lebih ringkas dan cross-version
        try:
            filename = await asyncio.to_thread(export_router_backup_ftp, "export")
        except Exception as e:
            logger.debug("Auto backup FTP export gagal, fallback API: %s", e)
            filename = None

        if not filename:
             try:
                 filename = await asyncio.to_thread(export_router_backup, "export")
             except Exception as e:
                 logger.debug("Suppressed non-fatal exception: %s", e)
        if filename:
            pesan = f"🗓️ [AUTO-BACKUP]\nBackup Rutin Mingguan Config Router\nBerhasil tersimpan."
            for admin_id in cfg.ADMIN_IDS:
                try:
                    with open(filename, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=admin_id, document=f,
                            filename=filename, caption=pesan
                        )
                except Exception as e:
                    logger.warning("Gagal kirim auto-backup ke admin %s: %s", admin_id, e)
            # Cleanup: hapus file backup lokal setelah terkirim ke semua admin
            try:
                os.remove(filename)
            except OSError as e:
                logger.debug("Gagal hapus file auto-backup sementara: %s", e)
    except Exception as e:
        logger.error(f"Auto Backup gagal: {e}")
