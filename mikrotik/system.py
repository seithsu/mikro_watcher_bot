# ============================================
# MIKROTIK/SYSTEM - System queries & operations
# get_status, reboot, backup, routerboard
# ============================================

import time
import logging
import ftplib

from .connection import pool
from .decorators import with_retry, cached, to_bool, to_int
import core.config as cfg

logger = logging.getLogger(__name__)


def _allow_plain_ftp_fallback(ftps_error):
    """Tentukan apakah fallback ke FTP plain aman dilakukan otomatis."""
    err = str(ftps_error or "").lower()
    if getattr(cfg, "MIKROTIK_FTP_ALLOW_INSECURE", False):
        return True
    # RouterOS/FTP server lawas sering menolak AUTH TLS dengan 500 AUTH not understood.
    # Pada kasus ini, fallback ke FTP plain jauh lebih pragmatis daripada gagal total.
    return ("auth" in err and "not understood" in err) or "500" in err


@with_retry
def get_status():
    """Ambil status lengkap: CPU, RAM, Uptime, Disk, Health, Routerboard.

    Hanya panggil pool.get_api() SATU KALI — gunakan objek api yang
    sama untuk semua sub-query agar tidak memicu reconnect berulang.
    """
    api = pool.get_api()
    resource = list(api.path('system', 'resource'))
    identity = list(api.path('system', 'identity'))

    if not resource:
        return None

    data = resource[0]
    name = identity[0].get('name', 'MikroTik') if identity else 'MikroTik'
    total_mem = to_int(data.get('total-memory', 0))
    free_mem = to_int(data.get('free-memory', 0))
    used_pct = round((1 - free_mem / total_mem) * 100, 1) if total_mem else 0

    result = {
        'identity': name,
        'cpu': to_int(data.get('cpu-load', 0)),
        'cpu_freq': to_int(data.get('cpu-frequency', 0)),
        'cpu_count': to_int(data.get('cpu-count', 1)),
        'ram_total': total_mem,
        'ram_free': free_mem,
        'ram_pct': used_pct,
        'uptime': data.get('uptime', '?'),
        'version': data.get('version', '?'),
        'board': data.get('board-name', '?'),
        'arch': data.get('architecture-name', '?'),
        'disk_total': to_int(data.get('total-hdd-space', 0)),
        'disk_free': to_int(data.get('free-hdd-space', 0)),
        # Extended fields (defaults)
        'cpu_temp': None,
        'voltage': None,
        'model': None,
        'serial': None,
        'current_firmware': None,
        'upgrade_firmware': None,
    }

    # /system/health — CPU temp & voltage (tidak semua RouterOS support)
    # Gunakan api yang SAMA — jangan panggil pool.get_api() lagi
    try:
        health = list(api.path('system', 'health'))
        if health:
            # RouterOS 7.x: health is list of {name, value, type}
            # RouterOS 6.x: health is single dict with keys
            h = health[0]
            if 'name' in h:
                # RouterOS 7 format: multiple entries
                health_map = {item.get('name', ''): item.get('value', '') for item in health}
                result['cpu_temp'] = health_map.get('cpu-temperature') or health_map.get('temperature')
                result['voltage'] = health_map.get('voltage')
            else:
                # RouterOS 6 format: single dict
                result['cpu_temp'] = h.get('cpu-temperature') or h.get('temperature')
                result['voltage'] = h.get('voltage')
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    # /system/routerboard — firmware & model
    try:
        rb = list(api.path('system', 'routerboard'))
        if rb:
            rb_data = rb[0]
            result['model'] = rb_data.get('model')
            result['serial'] = rb_data.get('serial-number')
            result['current_firmware'] = rb_data.get('current-firmware')
            result['upgrade_firmware'] = rb_data.get('upgrade-firmware')
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    return result


def reboot_router():
    """Reboot router. Koneksi akan di-reset setelahnya."""
    api = pool.get_api()
    try:
        tuple(api.path('system')('reboot'))
        return True
    finally:
        pool.reset()


@with_retry
def export_router_backup(backup_type="backup"):
    """
    Backup router. `backup_type` bisa "backup" (.backup binary) atau "export" (.rsc script).
    File akan disimpan lokal di folder bot, mereturn nama file.

    Catatan: Untuk .backup binary, content tidak bisa didownload via API.
    Gunakan export_router_backup_ftp() untuk binary backup yang lebih stabil.
    """
    api = pool.get_api()
    filename = f"router_backup_{int(time.time())}"
    # C3 FIX: simpan ke DATA_DIR agar file tidak tersebar di root bot
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if backup_type == "backup":
            target_file = f"{filename}.backup"
            local_target = str(cfg.DATA_DIR / target_file)
            tuple(api.path('system', 'backup')('save', name=filename))
        else:
            target_file = f"{filename}.rsc"
            local_target = str(cfg.DATA_DIR / target_file)
            # Export menggunakan system script karena /export adalah root-level command
            _run_export_script(api, filename)

        # Beri jeda agar RouterOS selesai menulis file
        time.sleep(3)

        # Baca file dari router
        files = list(api.path('file'))
        target_entry = None
        target_content = ""

        for f in files:
            if f.get('name') == target_file:
                target_entry = f
                target_content = f.get('contents', '')
                break

        if not target_entry:
            logger.warning(f"File {target_file} tidak ditemukan di router setelah backup")
            return None

        # Untuk .rsc: simpan content ke file lokal di DATA_DIR
        if target_content:
            with open(local_target, "w", encoding="utf-8") as file_out:
                file_out.write(str(target_content))

            # Hapus file dari router
            try:
                file_id = target_entry.get('.id')
                if file_id:
                    api.path('file').remove(file_id)
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
            return local_target

        # Untuk .backup binary: content kosong via API
        if backup_type == "backup":
            logger.info("Binary backup tidak bisa didownload via API, gunakan FTP method")
            return None

        return None

    except Exception as e:
        logger.error(f"Gagal backup router: {e}")
        raise e


def _run_export_script(api, filename):
    """Jalankan /export via system script (workaround untuk root-level command)."""
    script_name = "_temp_export_bot"
    source = f'/export file={filename}'
    scripts = api.path('system', 'script')

    try:
        # Cek apakah script sudah ada
        all_scripts = list(scripts)
        existing = [s for s in all_scripts if s.get('name') == script_name]

        if existing:
            scripts.update(**{'.id': existing[0]['.id'], 'source': source})
        else:
            scripts.add(name=script_name, source=source)

        # Re-fetch untuk dapat ID
        all_scripts = list(scripts)
        target = [s for s in all_scripts if s.get('name') == script_name]

        if target:
            tuple(scripts('run', **{'.id': target[0]['.id']}))

    finally:
        # Bersihkan script
        try:
            all_scripts = list(scripts)
            target = [s for s in all_scripts if s.get('name') == script_name]
            if target:
                scripts.remove(target[0]['.id'])
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
@with_retry
def export_router_backup_ftp(backup_type="backup"):
    """
    Membuat backup dan mengambil via FTP (Paling stabil untuk RouterOS).
    Pastikan service FTP di MikroTik menyala.
    """
    api = pool.get_api()
    filename_base = f"MikroTik_Backup_{int(time.time())}"

    if backup_type == "backup":
        target_file = f"{filename_base}.backup"
        tuple(api.path('system', 'backup')('save', name=filename_base))
    else:
        target_file = f"{filename_base}.rsc"
        _run_export_script(api, filename_base)

    time.sleep(3)

    # C3 FIX: Simpan ke DATA_DIR
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Tarik via FTPS (default) atau FTP fallback jika diizinkan
    local_filename = None
    try:
        # Reload env ringan agar swap kredensial/IP tanpa restart bisa terbaca.
        cfg.reload_router_env(min_interval=5)
        ftp = None
        mode = None
        errors = []

        ftps_error = None
        if cfg.MIKROTIK_FTP_TLS:
            try:
                ftps = ftplib.FTP_TLS()
                ftps.connect(cfg.MIKROTIK_IP, int(cfg.MIKROTIK_FTP_PORT), timeout=10)
                ftps.login(cfg.MIKROTIK_USER, cfg.MIKROTIK_PASS)
                ftps.prot_p()
                ftp = ftps
                mode = "FTPS"
            except Exception as e:
                ftps_error = e
                errors.append(f"FTPS: {e}")
                if _allow_plain_ftp_fallback(e):
                    logger.info("FTPS tidak tersedia (%s), fallback otomatis ke FTP plain.", e)
                else:
                    logger.warning("FTPS gagal dan belum ada fallback aman: %s", e)

        if ftp is None and _allow_plain_ftp_fallback(ftps_error):
            try:
                plain = ftplib.FTP()
                plain.connect(cfg.MIKROTIK_IP, int(cfg.MIKROTIK_FTP_PORT), timeout=10)
                plain.login(cfg.MIKROTIK_USER, cfg.MIKROTIK_PASS)
                ftp = plain
                mode = "FTP"
            except Exception as e:
                errors.append(f"FTP: {e}")

        if ftp is None:
            hint = "Aktifkan FTPS di router atau set MIKROTIK_FTP_ALLOW_INSECURE=true jika benar-benar diperlukan."
            raise Exception("; ".join(errors) + f" | {hint}")

        local_filename = str(cfg.DATA_DIR / target_file)
        with open(local_filename, 'wb') as f:
            ftp.retrbinary(f"RETR {target_file}", f.write)

        logger.info(f"Backup file diunduh via {mode}: {target_file}")
        ftp.quit()

        # Bersihkan file di router
        files = list(api.path('file'))
        for f in files:
            if f.get('name') == target_file:
                api.path('file').remove(f.get('.id'))
                break

    except Exception as e:
        logger.error(f"Gagal narik file backup via FTP/FTPS: {e}")
        raise Exception(
            f"Gagal download backup via FTP/FTPS (port {cfg.MIKROTIK_FTP_PORT}). "
            f"Pastikan service aktif dan kredensial benar: {str(e)}"
        )

    return local_filename


@cached(ttl=3600)
@with_retry
def get_system_routerboard():
    """Ambil info routerboard untuk cek firmware, dengan fallback ke resource."""
    api = pool.get_api()
    result = {
        'board': 'unknown',
        'model': 'unknown',
        'serial': 'unknown',
        'current_firmware': 'unknown',
        'upgrade_firmware': 'unknown',
        'needs_upgrade': False
    }
    
    # Coba via /system/routerboard (terutama buat firmware & model detail)
    try:
        rb = list(api.path('system', 'routerboard'))
        if rb:
            data = rb[0]
            result.update({
                'board': data.get('board-name', 'unknown'),
                'model': data.get('model', 'unknown'),
                'serial': data.get('serial-number', 'unknown'),
                'current_firmware': data.get('current-firmware', 'unknown'),
                'upgrade_firmware': data.get('upgrade-firmware', 'unknown'),
                'needs_upgrade': data.get('current-firmware', '') != data.get('upgrade-firmware', ''),
            })
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    # Fallback ke /system/resource jika nama board masih unknown (lebih reliable)
    if result['board'] == 'unknown' or result['model'] == 'unknown':
        try:
            res = list(api.path('system', 'resource'))
            if res:
                r_data = res[0]
                if result['board'] == 'unknown':
                    result['board'] = r_data.get('board-name', 'unknown')
                if result['model'] == 'unknown':
                    # Fallback ke identity atau biarkan unknown jika model tidak ada di resource
                    ident = list(api.path('system', 'identity'))
                    if ident:
                        result['model'] = ident[0].get('name', 'unknown')
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    return result

