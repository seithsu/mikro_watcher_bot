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

_TASK_STARTUP_DELAYS = {
    "system": 0,
    "resources": 1,
    "alert_maintenance": 0,
    "top_bw": 2,
    "logs": 4,
    "traffic": 6,
    "netwatch": 8,
    "dhcp_arp": 10,
}


async def _run_task_with_startup_delay(name, task_factory):
    """Jalankan task dengan delay startup kecil agar burst koneksi tidak serentak."""
    delay = max(0, int(_TASK_STARTUP_DELAYS.get(name, 0) or 0))
    if delay:
        logger.info("[INIT] Menunda start task %s selama %ss untuk meratakan beban startup.", name, delay)
        await asyncio.sleep(delay)
    await task_factory()


async def main_async():
    """Main Loop Async dengan graceful shutdown."""
    from .tasks import (
        task_monitor_system, task_monitor_resources, task_monitor_logs, task_monitor_dhcp_arp,
        task_monitor_traffic, task_monitor_top_bandwidth, task_monitor_alert_maintenance
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
        asyncio.create_task(_run_task_with_startup_delay("system", task_monitor_system)),
        asyncio.create_task(_run_task_with_startup_delay("resources", task_monitor_resources)),
        asyncio.create_task(_run_task_with_startup_delay("traffic", task_monitor_traffic)),
        asyncio.create_task(_run_task_with_startup_delay("top_bw", task_monitor_top_bandwidth)),
        asyncio.create_task(_run_task_with_startup_delay("logs", task_monitor_logs)),
        asyncio.create_task(_run_task_with_startup_delay("netwatch", task_monitor_netwatch)),
        asyncio.create_task(_run_task_with_startup_delay("dhcp_arp", task_monitor_dhcp_arp)),
        asyncio.create_task(_run_task_with_startup_delay("alert_maintenance", task_monitor_alert_maintenance)),
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
            from .alerts import get_alert_delivery_state, set_alert_delivery_enabled
            gate_state = get_alert_delivery_state()
            if gate_state.get("exists"):
                if gate_state.get("enabled"):
                    logger.info("Alert gate tetap aktif dari state sebelumnya.")
                else:
                    logger.info("Alert gate tetap nonaktif dari state sebelumnya; menunggu /start admin.")
            else:
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
    resource_interval = int(getattr(cfg, "RESOURCE_MONITOR_INTERVAL", 60) or 60)
    admin_list = ", ".join(str(a) for a in getattr(cfg, "ADMIN_IDS", ADMIN_IDS))

    logger.info("=" * 40)
    logger.info("MONITOR OTOMATIS MIKROTIK")
    logger.info("=" * 40)
    logger.info(f"System Check: Tiap {interval_menit} menit")
    logger.info(f"Resource Check: Tiap {resource_interval} detik")
    logger.info("Traffic Check: Tiap 60 detik")
    logger.info(f"Top BW Check: Tiap {max(5, int(getattr(cfg, 'TOP_BW_ALERT_INTERVAL', 15)))} detik")
    logger.info(f"Log Check   : Tiap {int(getattr(cfg, 'MONITOR_LOG_INTERVAL', MONITOR_LOG_INTERVAL))} detik")
    logger.info("Alert Maint : Tiap 20 detik")
    logger.info(f"Admin IDs   : {admin_list}")
    logger.info("=" * 40)
    logger.info("Tekan Ctrl+C untuk berhenti")

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("[STOP] Monitor berhenti.")
