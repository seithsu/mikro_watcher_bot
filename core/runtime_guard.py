import logging
import sys
import threading


logger = logging.getLogger(__name__)


def install_global_exception_hooks(process_name="app"):
    """Install global exception hooks agar error tak terduga selalu tercatat."""

    def _sys_hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logger.critical(
            "[PANIC][%s] Unhandled exception",
            process_name,
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def _thread_hook(args):
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        logger.critical(
            "[PANIC][%s] Unhandled thread exception in %s",
            process_name,
            getattr(args.thread, "name", "unknown"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _sys_hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook

