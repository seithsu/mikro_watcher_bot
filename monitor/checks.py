# ============================================
# MONITOR/CHECKS - System Check Functions
# CPU, RAM, disk, firmware, uptime, VPN, interface
# ============================================

import time
import asyncio
import logging
import json

import core.config as cfg
from mikrotik import get_interfaces, get_system_routerboard, get_vpn_tunnels
from .alerts import kirim_ke_semua_admin
from core import database

logger = logging.getLogger(__name__)

_STATE_FILE = cfg.DATA_DIR / "monitor_state.json"


def _state_snapshot():
    """Snapshot state persisten untuk mendeteksi perubahan nyata."""
    return {
        'cpu': bool(_last_alerts.get('cpu', False)),
        'ram': bool(_last_alerts.get('ram', False)),
        'disk': bool(_last_alerts.get('disk', False)),
        'firmware_checked': bool(_last_alerts.get('firmware_checked', False)),
        'firmware_last_check': int(_last_alerts.get('firmware_last_check', 0) or 0),
        'iface_down': tuple(sorted(_last_alerts.get('iface_down', set()))),
        'vpn_down': tuple(sorted(_last_alerts.get('vpn_down', set()))),
        '_initialized': bool(_last_alerts.get('_initialized', False)),
        'uptime_baseline': int(_last_alerts.get('uptime_baseline', 0) or 0),
    }


def _load_state():
    """W8 FIX: Load _last_alerts dari file agar state survive restart monitor."""
    try:
        if _STATE_FILE.exists():
            with open(_STATE_FILE, 'r') as f:
                saved = json.load(f)
            # Restore tipe data yang tepat
            return {
                'cpu': saved.get('cpu', False),
                'ram': saved.get('ram', False),
                'disk': saved.get('disk', False),
                'firmware_checked': saved.get('firmware_checked', False),
                'firmware_last_check': int(saved.get('firmware_last_check', 0) or 0),
                'iface_down': set(saved.get('iface_down', [])),
                'vpn_down': set(saved.get('vpn_down', [])),
                '_initialized': saved.get('_initialized', False),
                'uptime_baseline': int(saved.get('uptime_baseline', 0) or 0),
            }
    except Exception as e:
        logger.debug("_load_state error: %s", e)
    return {
        'cpu': False, 'ram': False, 'disk': False, 'firmware_checked': False,
        'firmware_last_check': 0,
        'iface_down': set(), 'vpn_down': set(), '_initialized': False,
        'uptime_baseline': 0,
    }


def _save_state():
    """W8 FIX: Simpan _last_alerts ke file untuk persistensi."""
    try:
        serializable = {
            'cpu': _last_alerts.get('cpu', False),
            'ram': _last_alerts.get('ram', False),
            'disk': _last_alerts.get('disk', False),
            'firmware_checked': _last_alerts.get('firmware_checked', False),
            'firmware_last_check': int(_last_alerts.get('firmware_last_check', 0) or 0),
            'iface_down': list(_last_alerts.get('iface_down', set())),
            'vpn_down': list(_last_alerts.get('vpn_down', set())),
            '_initialized': _last_alerts.get('_initialized', False),
            'uptime_baseline': int(_last_alerts.get('uptime_baseline', 0) or 0),
        }
        cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = str(_STATE_FILE) + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(serializable, f)
        import os
        os.replace(tmp_path, str(_STATE_FILE))
    except Exception as e:
        logger.debug(f"_save_state error: {e}")


def _save_state_if_changed(before_state):
    """Simpan state hanya jika ada perubahan pada field persisten."""
    if _state_snapshot() != before_state:
        _save_state()


# State untuk menghindari spam alert yang sama — load dari file saat startup
_last_alerts = _load_state()

_last_uptime_seconds = None
_firmware_last_check = float(_last_alerts.get('firmware_last_check', 0) or 0)


def clear_runtime_state():
    """Reset state checks in-memory setelah reset runtime bersama."""
    global _last_uptime_seconds, _firmware_last_check
    persisted_firmware_checked = bool(_last_alerts.get('firmware_checked', False))
    persisted_firmware_last_check = int(_last_alerts.get('firmware_last_check', 0) or 0)
    _last_alerts.clear()
    _last_alerts.update({
        'cpu': False,
        'ram': False,
        'disk': False,
        'firmware_checked': persisted_firmware_checked,
        'firmware_last_check': persisted_firmware_last_check,
        'iface_down': set(),
        'vpn_down': set(),
        '_initialized': False,
        'uptime_baseline': 0,
    })
    _last_uptime_seconds = None
    _firmware_last_check = float(persisted_firmware_last_check)


async def cek_cpu_ram(info):
    """Cek CPU dan RAM, kirim alert jika melewati threshold."""
    state_before = _state_snapshot()
    cpu = int(info['cpu'])
    total_ram = int(info['ram_total'])
    free_ram = int(info['ram_free'])
    ram_pct = ((total_ram - free_ram) / total_ram) * 100 if total_ram > 0 else 0

    # Record metrics
    try:
        await asyncio.to_thread(
            database.record_metrics_batch,
            [('cpu_usage', cpu, None), ('ram_usage', ram_pct, None)]
        )
    except Exception as e:
        logger.debug(f"Failed to record CPU/RAM metrics: {e}")

    # Alert CPU tinggi
    if cpu > cfg.CPU_THRESHOLD:
        if not _last_alerts['cpu']:
            await kirim_ke_semua_admin(
                f"[WARN] <b>CPU Tinggi!</b>\n\n"
                f"CPU Load: <b>{cpu}%</b> (threshold: {cfg.CPU_THRESHOLD}%)\n"
                f"Uptime: {info['uptime']}\n\n"
                f"Cek router segera!",
                parse_mode='HTML'
            )
            _last_alerts['cpu'] = True
            logger.info(f"[SENT] Alert CPU: {cpu}%")
    else:
        if _last_alerts['cpu']:
            await kirim_ke_semua_admin(
                f"[OK] <b>CPU Kembali Normal</b>\nCPU Load: {cpu}%",
                parse_mode='HTML'
            )
        _last_alerts['cpu'] = False

    # Alert RAM tinggi
    if ram_pct > cfg.RAM_THRESHOLD:
        if not _last_alerts['ram']:
            await kirim_ke_semua_admin(
                f"[WARN] <b>RAM Tinggi!</b>\n\n"
                f"RAM Usage: <b>{ram_pct:.1f}%</b> (threshold: {cfg.RAM_THRESHOLD}%)\n"
                f"Uptime: {info['uptime']}\n\n"
                f"Cek router segera!",
                parse_mode='HTML'
            )
            _last_alerts['ram'] = True
            logger.info(f"[SENT] Alert RAM: {ram_pct:.1f}%")
    else:
        if _last_alerts['ram']:
            await kirim_ke_semua_admin(
                f"[OK] <b>RAM Kembali Normal</b>\nRAM Usage: {ram_pct:.1f}%",
                parse_mode='HTML'
            )
        _last_alerts['ram'] = False

    _save_state_if_changed(state_before)
    return cpu, ram_pct


async def cek_disk(info):
    """Cek disk usage, alert jika melewati threshold."""
    state_before = _state_snapshot()
    try:
        total = int(info.get('disk_total', '0'))
        free = int(info.get('disk_free', '0'))
        if total <= 0:
            return
        used_pct = ((total - free) / total) * 100

        try:
            await asyncio.to_thread(database.record_metric, 'disk_usage', used_pct)
        except Exception as e:
            logger.debug(f"Failed to record disk metric: {e}")

        if used_pct > cfg.DISK_THRESHOLD:
            if not _last_alerts.get('disk'):
                await kirim_ke_semua_admin(
                    f"[WARN] <b>Disk Penuh!</b>\n\n"
                    f"Disk Usage: <b>{used_pct:.1f}%</b> (threshold: {cfg.DISK_THRESHOLD}%)\n"
                    f"Free: {free // (1024*1024)} MB\n\n"
                    f"Segera bersihkan file backup/log di router!",
                    parse_mode='HTML'
                )
                _last_alerts['disk'] = True
                logger.info(f"[SENT] Alert Disk: {used_pct:.1f}%")
        else:
            if _last_alerts.get('disk'):
                await kirim_ke_semua_admin(
                    f"[OK] <b>Disk Kembali Normal</b>\nDisk Usage: {used_pct:.1f}%",
                    parse_mode='HTML'
                )
            _last_alerts['disk'] = False
        _save_state_if_changed(state_before)
    except Exception as e:
        logger.debug(f"cek_disk error: {e}")


async def cek_firmware():
    """Cek firmware RouterBoard, alert jika ada update (1x per 24 jam)."""
    global _firmware_last_check
    state_before = _state_snapshot()
    now = time.time()
    if now - _firmware_last_check < 86400:
        return
    _firmware_last_check = now
    _last_alerts['firmware_last_check'] = int(_firmware_last_check)

    try:
        rb = await asyncio.to_thread(get_system_routerboard)
        if rb and rb.get('needs_upgrade'):
            if not _last_alerts.get('firmware_checked'):
                await kirim_ke_semua_admin(
                    f"[INFO] <b>Firmware Update Tersedia</b>\n\n"
                    f"Board: {rb['board']}\n"
                    f"Current: <code>{rb['current_firmware']}</code>\n"
                    f"Available: <code>{rb['upgrade_firmware']}</code>\n\n"
                    f"Jalankan upgrade melalui Winbox -> System -> RouterBOARD -> Upgrade",
                    parse_mode='HTML'
                )
                _last_alerts['firmware_checked'] = True
                logger.info("[SENT] Firmware upgrade available")
        else:
            _last_alerts['firmware_checked'] = False
        _save_state_if_changed(state_before)
    except Exception as e:
        logger.debug(f"cek_firmware error: {e}")


async def cek_uptime_anomaly(info):
    """Deteksi jika router restart tanpa perintah dari bot."""
    global _last_uptime_seconds

    uptime_str = info.get('uptime', '')
    state_before = _state_snapshot()
    try:
        import re
        uptime_text = str(uptime_str or '').strip()
        if not uptime_text or uptime_text in {"?", "-", "unknown", "n/a", "N/A"}:
            logger.debug("cek_uptime_anomaly skip invalid uptime: %r", uptime_str)
            return

        pattern = r'(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
        m = re.fullmatch(pattern, uptime_text)
        if m and any(part is not None for part in m.groups()):
            w, d, h, mi, s = (int(x) if x else 0 for x in m.groups())
            total_seconds = w*604800 + d*86400 + h*3600 + mi*60 + s
        else:
            logger.debug("cek_uptime_anomaly skip unparseable uptime: %r", uptime_str)
            return

        if _last_uptime_seconds is None:
            persisted_baseline = int(_last_alerts.get('uptime_baseline', 0) or 0)
            if persisted_baseline > 0:
                _last_uptime_seconds = persisted_baseline

        restart_detected = False
        if _last_uptime_seconds is not None:
            restart_detected = total_seconds < _last_uptime_seconds

        _last_uptime_seconds = total_seconds
        _last_alerts['uptime_baseline'] = total_seconds
        _save_state_if_changed(state_before)

        if restart_detected:
            delivered = await kirim_ke_semua_admin(
                f"[WARN] <b>Router Restart Terdeteksi!</b>\n\n"
                f"Uptime baru: <b>{uptime_str}</b>\n\n"
                f"Router ter-restart tanpa perintah dari bot.\n"
                f"Kemungkinan: power cycle, crash, atau restart manual.",
                parse_mode='HTML'
            )
            if delivered:
                logger.info(f"[SENT] Uptime anomaly detected: {uptime_str}")
            else:
                logger.info(f"[SKIP] Uptime anomaly detected but delivery blocked/suppressed: {uptime_str}")
    except Exception as e:
        logger.debug(f"cek_uptime_anomaly error: {e}")


async def cek_vpn_tunnels():
    """Monitor VPN tunnel status changes."""
    state_before = _state_snapshot()
    if not cfg.MONITOR_VPN_ENABLED:
        # Pastikan state bersih saat monitor VPN dimatikan agar tidak memicu recovery palsu.
        if _last_alerts.get('vpn_down'):
            _last_alerts['vpn_down'] = set()
        try:
            await asyncio.to_thread(database.close_open_incidents_by_tag, "vpn", "monitor-disabled")
        except Exception as dbe:
            logger.debug(f"VPN disable cleanup DB error: {dbe}")
        _save_state_if_changed(state_before)
        return

    try:
        tunnels = await asyncio.to_thread(get_vpn_tunnels)
        if not tunnels:
            return

        currently_down = set()
        ignore_names = set(cfg.MONITOR_VPN_IGNORE_NAMES or set())
        for t in tunnels:
            name = str(t.get('name', '')).strip()
            if not name:
                continue
            if name.lower() in ignore_names:
                continue
            if not t.get('disabled') and not t.get('running'):
                currently_down.add(name)

        prev_down = _last_alerts.get('vpn_down', set())

        if _last_alerts.get('_initialized'):
            new_down = currently_down - prev_down
            for name in new_down:
                tinfo = next((t for t in tunnels if t['name'] == name), {})
                await kirim_ke_semua_admin(
                    f"[WARN] <b>[VPN DOWN] {name}</b>\n\n"
                    f"Type: {tinfo.get('type', 'unknown')}\n"
                    f"Remote: {tinfo.get('remote', '-')}\n\n"
                    f"Tunnel VPN terputus!",
                    parse_mode='HTML'
                )
                # W6 FIX: Rekam VPN incident ke database
                try:
                    await asyncio.to_thread(
                        database.log_incident_down, name,
                        f"[WARN] VPN DOWN (type: {tinfo.get('type','?')}, remote: {tinfo.get('remote','-')})",
                        f"VPN tunnel {name} terputus", "vpn"
                    )
                except Exception as dbe:
                    logger.debug(f"VPN incident DB error: {dbe}")
                logger.info(f"[SENT] VPN DOWN: {name}")

            recovered = prev_down - currently_down
            for name in recovered:
                await kirim_ke_semua_admin(
                    f"[OK] <b>[VPN UP] {name}</b>\n\nTunnel VPN kembali terhubung.",
                    parse_mode='HTML'
                )
                # W6 FIX: Close VPN incident di database
                try:
                    await asyncio.to_thread(database.log_incident_up, name)
                except Exception as dbe:
                    logger.debug(f"VPN recovery DB error: {dbe}")
                logger.info(f"[SENT] VPN UP: {name}")

        _last_alerts['vpn_down'] = currently_down

        _save_state_if_changed(state_before)
    except Exception as e:
        logger.debug(f"cek_vpn_tunnels error: {e}")


async def cek_interface(interfaces=None):
    """Cek interface yang enabled tapi down.

    Hanya alert jika ada PERUBAHAN status (UP -> DOWN atau DOWN -> UP).
    Run pertama hanya record state, tidak alert.
    Interface di MONITOR_IGNORE_IFACE di-skip.
    
    Args:
        interfaces: list interface yang sudah di-fetch sebelumnya (opsional).
                    Jika None, akan fetch sendiri dari router.
    """
    state_before = _state_snapshot()
    try:
        if interfaces is None:
            interfaces = await asyncio.to_thread(get_interfaces)
    except Exception as e:
        logger.debug(f"cek_interface get_interfaces error: {e}")
        return

    currently_down = set()
    for iface in interfaces:
        if iface['name'] in cfg.MONITOR_IGNORE_IFACE:
            continue
        if iface['enabled'] and not iface['running']:
            currently_down.add(iface['name'])

    if not _last_alerts['_initialized']:
        _last_alerts['iface_down'] = currently_down
        _last_alerts['_initialized'] = True
        if currently_down:
            logger.info(f"[INIT] Interface awal down (tidak alert): {', '.join(currently_down)}")
        _save_state_if_changed(state_before)
        return

    newly_down = currently_down - _last_alerts['iface_down']
    if newly_down:
        iface_list = ", ".join(newly_down)
        await kirim_ke_semua_admin(
            f"[WARN] <b>Interface DOWN!</b>\n\n"
            f"Interface: <b>{iface_list}</b>\n\n"
            f"Cek koneksi fisik/konfigurasi!",
            parse_mode='HTML'
        )
        logger.info(f"[SENT] Alert interface down: {iface_list}")

    recovered = _last_alerts['iface_down'] - currently_down
    if recovered:
        iface_list = ", ".join(recovered)
        await kirim_ke_semua_admin(
            f"[OK] <b>Interface Kembali UP</b>\n\n"
            f"Interface: <b>{iface_list}</b>",
            parse_mode='HTML'
        )
        logger.info(f"[SENT] Interface recovered: {iface_list}")

    _last_alerts['iface_down'] = currently_down
    _save_state_if_changed(state_before)

