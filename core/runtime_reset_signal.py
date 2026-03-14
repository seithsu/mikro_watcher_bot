import json
import logging
import os
import time

from core.config import DATA_DIR


logger = logging.getLogger(__name__)

_RUNTIME_RESET_SIGNAL_FILE = DATA_DIR / "runtime_reset_signal.json"


def emit_runtime_reset_signal(reason="manual", clear_runtime_config=False, signal_file=None):
    """Tulis sinyal reset runtime lintas-proses secara atomik."""
    target_file = signal_file or _RUNTIME_RESET_SIGNAL_FILE
    payload = {
        "ts": float(time.time()),
        "reason": str(reason or "manual"),
        "clear_runtime_config": bool(clear_runtime_config),
    }
    target_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = str(target_file) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp_path, str(target_file))
    return payload


def read_runtime_reset_signal(signal_file=None):
    """Baca sinyal reset runtime terbaru. Return dict kosong jika tidak ada/invalid."""
    target_file = signal_file or _RUNTIME_RESET_SIGNAL_FILE
    if not target_file.exists():
        return {}
    try:
        with open(target_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.debug("Gagal membaca runtime reset signal: %s", exc)
        return {}
