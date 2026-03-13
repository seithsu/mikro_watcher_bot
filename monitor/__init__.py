# ============================================
# MONITOR Package - Orchestrator
# ============================================

import asyncio
import signal
import logging
from concurrent.futures import ThreadPoolExecutor

from core.config import ADMIN_IDS, MONITOR_INTERVAL, MONITOR_LOG_INTERVAL, ASYNC_THREAD_WORKERS
import core.config as cfg
from core.logging_setup import configure_root_logging
from core.runtime_guard import install_global_exception_hooks

logger = logging.getLogger(__name__)


async def main_async():
    """Main Loop Async dengan graceful shutdown."""
    from .tasks import (
        task_monitor_system, task_monitor_logs, task_monitor_dhcp_arp,
        task_monitor_traffic, task_monitor_alert_maintenance
    )
    from .netwatch import task_monitor_netwatch

    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=max(2, int(getattr(cfg, "ASYNC_THREAD_WORKERS", ASYNC_THREAD_WORKERS))))
    loop.set_default_executor(executor)

    def _loop_exception_handler(_loop, context):
        logger.error("Unhandled asyncio loop exception: %s", context.get("message", "unknown"))
        if context.get("exception") is not None:
            logger.error("Async loop exception detail:", exc_info=context["exception"])

    loop.set_exception_handler(_loop_exception_handler)

    tasks = [
        asyncio.create_task(task_monitor_system()),
        asyncio.create_task(task_monitor_traffic()),  # B10-RC1: dedicated traffic task (60s interval)
        asyncio.create_task(task_monitor_logs()),
        asyncio.create_task(task_monitor_netwatch()),
        asyncio.create_task(task_monitor_dhcp_arp()),
        asyncio.create_task(task_monitor_alert_maintenance()),
    ]

    def _signal_handler():
        logger.info("[STOP] Sinyal shutdown diterima, menghentikan tasks...")
        for t in tasks:
            t.cancel()

    signal_loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal_loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows: add_signal_handler not supported, use signal.signal instead
            signal.signal(sig, lambda s, f: _signal_handler())

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("[STOP] Semua monitor tasks berhenti.")
        executor.shutdown(wait=False, cancel_futures=True)


def main():
    # Logging terpusat + redaction token sensitif.
    configure_root_logging(level=logging.INFO)
    install_global_exception_hooks(process_name="monitor")

    if getattr(cfg, "ALERT_REQUIRE_START", False):
        try:
            from .alerts import set_alert_delivery_enabled
            set_alert_delivery_enabled(False, actor="monitor_boot", reason="require_start")
            logger.info("Alert gate aktif: notifikasi monitor menunggu perintah /start dari admin.")
        except Exception as e:
            logger.warning("Gagal set alert gate saat startup monitor: %s", e)

    if not getattr(cfg, "MIKROTIK_USE_SSL", False):
        logger.info("MIKROTIK_USE_SSL=false: monitor berjalan dalam mode API non-SSL sesuai konfigurasi.")
    elif not getattr(cfg, "MIKROTIK_TLS_VERIFY", True):
        logger.warning(
            "MIKROTIK_TLS_VERIFY=false: monitor memakai TLS tanpa verifikasi sertifikat. "
            "Gunakan hanya sebagai mode transisi sampai CA file siap."
        )

    interval_menit = int(getattr(cfg, "MONITOR_INTERVAL", MONITOR_INTERVAL)) // 60
    admin_list = ", ".join(str(a) for a in getattr(cfg, "ADMIN_IDS", ADMIN_IDS))

    logger.info("=" * 40)
    logger.info("MONITOR OTOMATIS MIKROTIK")
    logger.info("=" * 40)
    logger.info(f"System Check: Tiap {interval_menit} menit")
    logger.info("Traffic Check: Tiap 60 detik")
    logger.info(f"Log Check   : Tiap {int(getattr(cfg, 'MONITOR_LOG_INTERVAL', MONITOR_LOG_INTERVAL))} detik")
    logger.info("Alert Maint : Tiap 20 detik")
    logger.info(f"Admin IDs   : {admin_list}")
    logger.info("=" * 40)
    logger.info("Tekan Ctrl+C untuk berhenti")

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("[STOP] Monitor berhenti.")
