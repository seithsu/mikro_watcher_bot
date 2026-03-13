# ============================================
# BACKUP - Backup config & file penting ke ZIP
# ============================================

import zipfile
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# File yang wajib di-backup
_FILES_TO_BACKUP = [
    "core/config.py",
    "requirements.txt",
    "ecosystem.config.js",
    "data/aktivitas.log",
    "data/downtime.db",
    "data/state.json",
    "mikrotik/__init__.py",
    "mikrotik/connection.py",
    "mikrotik/decorators.py",
    "mikrotik/system.py",
    "mikrotik/network.py",
    "mikrotik/scan.py",
    "mikrotik/queue.py",
    "mikrotik/dns.py",
    "mikrotik/scheduler.py",
    "mikrotik/vpn.py",
    "mikrotik/firewall.py",
    "mikrotik/tools.py",
    "bot.py",
    "monitor/__init__.py",
    "monitor/alerts.py",
    "monitor/checks.py",
    "monitor/tasks.py",
    "monitor/netwatch.py",
    "run_monitor.py",
    "core/logger.py",
    "core/database.py",
    "core/backup.py",
    "core/classification.py",
    "handlers/general.py",
    "handlers/network.py",
    "handlers/queue.py",
    "handlers/alert.py",
    "handlers/utils.py",
    "handlers/tools.py",
    "handlers/report.py",
    "handlers/jobs.py",
    "handlers/charts.py",
    "services/chart_service.py",
    "services/config_manager.py",
]


def backup_semua():
    """Backup semua file penting ke ZIP. Return nama file ZIP."""
    waktu = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_bot_{waktu}.zip"

    count = 0
    with zipfile.ZipFile(backup_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in _FILES_TO_BACKUP:
            if Path(file).exists():
                zipf.write(file)
                count += 1
                logger.info(f"[PACK] {file}")

    logger.info(f"[OK] Backup selesai: {backup_name} ({count} files)")
    return backup_name


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logger.info("[BACKUP] BACKUP BOT MIKROTIK")
    logger.info("=" * 30)
    backup_semua()
    logger.info("=" * 30)
