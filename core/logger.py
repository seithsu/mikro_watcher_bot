# ============================================
# LOGGER - Pencatat Aktivitas Bot (dengan Rotation)
# ============================================

import json
import os
import glob
import logging
from datetime import datetime
from pathlib import Path
from core.config import LOG_MAX_SIZE, LOG_BACKUP_COUNT, DATA_DIR

LOG_FILE = str(DATA_DIR / "aktivitas.log")
logger = logging.getLogger(__name__)
_last_rotate_check_ts = 0.0
_ROTATE_CHECK_INTERVAL = 60  # Cek rotasi maksimal 1x per 60 detik


# ============ LOG ROTATION ============

def rotate_log():
    """Rotate log jika ukuran melebihi batas.

    Hasil: aktivitas.log.1, aktivitas.log.2, dst.
    File lama di atas LOG_BACKUP_COUNT akan dihapus.
    """
    if not Path(LOG_FILE).exists():
        return

    ukuran = os.path.getsize(LOG_FILE)
    if ukuran < LOG_MAX_SIZE:
        return

    # Hapus backup tertua jika melebihi limit
    for i in range(LOG_BACKUP_COUNT, 0, -1):
        old_file = f"{LOG_FILE}.{i}"
        new_file = f"{LOG_FILE}.{i + 1}"
        if Path(old_file).exists():
            if i >= LOG_BACKUP_COUNT:
                os.remove(old_file)
            else:
                os.rename(old_file, new_file)

    # Rename current log ke .1
    os.rename(LOG_FILE, f"{LOG_FILE}.1")


# ============ CORE FUNCTIONS ============

def catat(user_id, username, perintah, status):
    """Catat setiap aktivitas ke file log."""
    global _last_rotate_check_ts
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data = {
        "waktu": waktu,
        "user_id": user_id,
        "username": username,
        "perintah": perintah,
        "status": status
    }

    try:
        # Throttle rotasi: cek hanya 1x per _ROTATE_CHECK_INTERVAL detik.
        import time as _time
        now = _time.time()
        if (now - _last_rotate_check_ts) >= _ROTATE_CHECK_INTERVAL:
            rotate_log()
            _last_rotate_check_ts = now
        with open(LOG_FILE, "a", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Gagal catat log aktivitas: {e}")

    logger.info(f"Audit activity: {waktu} | {user_id} | {perintah} | {status}")


def baca_log(jumlah=10):
    """Baca log terakhir dari file aktif."""
    if not Path(LOG_FILE).exists():
        return []

    with open(LOG_FILE, "r", encoding="utf-8") as file:
        lines = file.readlines()

    logs = []
    for line in lines[-jumlah:]:
        try:
            logs.append(json.loads(line.strip()))
        except (json.JSONDecodeError, ValueError):
            continue

    return logs


def format_log_pretty(logs):
    """Format log jadi text HTML yang rapi untuk Telegram."""
    if not logs:
        return "ℹ️ <i>Belum ada aktivitas tercatat.</i>"

    text = "📝 <b>LOG AKTIVITAS BOT</b>\n"
    text += "━" * 20 + "\n\n"

    for log in logs:
        icon = "✅" if log.get('status') == "berhasil" else "❌"
        waktu = log.get('waktu', 'Unknown Time')
        username = log.get('username') or 'Unknown'
        user_id = log.get('user_id', '?')
        perintah = log.get('perintah', '?')
        status = log.get('status', 'Unknown')
        text += (
            f"{icon} <b>{waktu}</b>\n"
            f"   👤 {username} (<code>{user_id}</code>)\n"
            f"   💬 <code>{perintah}</code>\n"
            f"   📌 {status}\n\n"
        )

    return text


def hitung_total_log():
    """Hitung total log entries di semua file (aktif + backup)."""
    total = 0

    # File aktif
    if Path(LOG_FILE).exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            total += sum(1 for _ in f)

    # File backup
    for backup in glob.glob(f"{LOG_FILE}.*"):
        with open(backup, "r", encoding="utf-8") as f:
            total += sum(1 for _ in f)

    return total
