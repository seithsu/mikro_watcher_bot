# ============================================
# MONITOR/ALERTS - Enhanced Alert System
# Severity levels, escalation, digest batching
# Cross-process ACK via file (bot & monitor are separate PIDs)
# ============================================

import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from enum import Enum

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from core.config import (
    ADMIN_IDS,
    ALERT_REQUIRE_START,
    ALERT_DIGEST_THRESHOLD,
    ALERT_DIGEST_WINDOW,
    ALERT_ESCALATION_MINUTES,
    ALERT_IPC_LOCK_STALE_SEC,
    DATA_DIR,
    TOKEN,
)

logger = logging.getLogger(__name__)
_TIMEOUT_LOG_STATE = {}

# Cross-process IPC files
_ACK_FILE = DATA_DIR / "pending_acks.json"
_ACK_EVENTS_FILE = DATA_DIR / "ack_events.json"
_IPC_LOCK_FILE = DATA_DIR / "pending_acks.lock"
_MUTE_FILE = DATA_DIR / "mute.lock"
_ALERT_GATE_FILE = DATA_DIR / "alert_gate.json"


# ============ BOT LAZY INIT ============

_bot_instance = None


def _get_bot() -> Bot:
    """Lazy initialize bot instance."""
    global _bot_instance
    if _bot_instance is None:
        if not TOKEN:
            raise RuntimeError("TOKEN belum dikonfigurasi! Cek file .env")
        _bot_instance = Bot(token=TOKEN)
    return _bot_instance


class _BotProxy:
    """Proxy agar pemanggilan tetap `await bot.send_message(...)`."""

    def __getattr__(self, name):
        return getattr(_get_bot(), name)


bot = _BotProxy()


# ============ SEVERITY LEVELS ============


class AlertSeverity(Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


_SEVERITY_PREFIX = {
    AlertSeverity.CRITICAL: "🔴",
    AlertSeverity.WARNING: "🟡",
    AlertSeverity.INFO: "ℹ️",
}


# ============ STATE ============

# { alert_key: { message, severity, time, escalated, _sync_ack_file } }
_pending_acks = {}
_recent_alerts = deque(maxlen=100)
_acknowledged = set()


# ============ IPC HELPERS ============


@contextmanager
def _ipc_lock(timeout=2.0, poll_interval=0.05):
    """Best-effort inter-process lock via lock file."""
    start = time.time()
    fd = None
    lock_path = str(_IPC_LOCK_FILE)

    def _is_stale_lock(path, stale_after):
        now = time.time()
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if raw:
                try:
                    meta = json.loads(raw)
                    ts = float(meta.get("ts", 0) or 0)
                    if ts > 0 and (now - ts) > stale_after:
                        return True
                except Exception as e:
                    logger.debug("Suppressed non-fatal exception: %s", e)
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
        # Fallback: pakai mtime bila metadata tidak valid.
        try:
            return (now - os.path.getmtime(path)) > stale_after
        except OSError:
            return False

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                payload = json.dumps({"pid": os.getpid(), "ts": time.time()})
                os.write(fd, payload.encode("utf-8"))
            except Exception as e:
                logger.debug("Suppressed non-fatal exception: %s", e)
            break
        except FileExistsError:
            if _is_stale_lock(lock_path, max(3, int(ALERT_IPC_LOCK_STALE_SEC))):
                try:
                    os.unlink(lock_path)
                    logger.warning("IPC lock stale terdeteksi, lock lama direclaim.")
                    continue
                except Exception as e:
                    logger.debug("Suppressed non-fatal exception: %s", e)
            if time.time() - start >= timeout:
                raise TimeoutError("IPC lock timeout")
            time.sleep(poll_interval)

    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.debug("Gagal menghapus IPC lock file.", exc_info=True)


def _parse_severity(value):
    if isinstance(value, AlertSeverity):
        return value
    if isinstance(value, str):
        raw = value.split(".")[-1].strip().upper()
        return AlertSeverity.__members__.get(raw, AlertSeverity.WARNING)
    return AlertSeverity.WARNING


def _read_json_unlocked(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning(f"Gagal membaca {path.name}", exc_info=True)
        # Self-heal: reset file korup ke default agar warning tidak berulang.
        try:
            _write_json_unlocked(path, default)
            logger.info("%s di-reset otomatis ke default.", path.name)
        except Exception:
            logger.debug("Auto-heal %s gagal.", path.name, exc_info=True)
        return default


def _write_json_unlocked(path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, str(path))


def _load_pending_acks_from_file():
    """Load pending ack snapshot. Return dict or None saat gagal read."""
    try:
        with _ipc_lock():
            data = _read_json_unlocked(_ACK_FILE, {})
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Gagal membaca {_ACK_FILE.name}: {e}")
        return None


def _write_ack_file(data):
    """Atomic write pending ack snapshot."""
    try:
        with _ipc_lock():
            _write_json_unlocked(_ACK_FILE, data)
    except Exception as e:
        logger.debug(f"_write_ack_file error: {e}")


def _append_ack_event(event_key):
    """Append ACK event agar monitor menghapus entry secara eksplisit, bukan inferensi."""
    try:
        with _ipc_lock():
            raw = _read_json_unlocked(_ACK_EVENTS_FILE, [])
            events = raw if isinstance(raw, list) else []
            events.append({"key": str(event_key), "ts": time.time()})
            _write_json_unlocked(_ACK_EVENTS_FILE, events[-1000:])
    except Exception as e:
        logger.debug(f"_append_ack_event error: {e}")


def _consume_ack_events():
    """Ambil dan kosongkan ack event file."""
    try:
        with _ipc_lock():
            raw = _read_json_unlocked(_ACK_EVENTS_FILE, [])
            events = raw if isinstance(raw, list) else []
            _write_json_unlocked(_ACK_EVENTS_FILE, [])
    except Exception as e:
        logger.debug(f"_consume_ack_events error: {e}")
        return []

    keys = []
    for event in events:
        if isinstance(event, dict):
            key = event.get("key")
        else:
            key = event
        if key:
            keys.append(str(key))
    return keys


def _save_pending_acks():
    """Persist _pending_acks snapshot ke file lintas proses."""
    try:
        serializable = {
            key: {
                "message": info.get("message", ""),
                "severity": _parse_severity(info.get("severity")).value,
                "time": float(info.get("time", 0) or 0),
                "escalated": int(info.get("escalated", 0) or 0),
            }
            for key, info in _pending_acks.items()
        }
        _write_ack_file(serializable)
    except Exception as e:
        logger.debug(f"_save_pending_acks error: {e}")


# ============ ACK PUBLIC API ============


def get_pending_alerts():
    """Return pending alerts gabungan snapshot file + memory."""
    file_data = _load_pending_acks_from_file() or {}

    combined = dict(file_data)
    for key, info in _pending_acks.items():
        combined[key] = {
            "message": info.get("message", ""),
            "severity": _parse_severity(info.get("severity")).value,
            "time": info.get("time", 0),
            "escalated": info.get("escalated", 0),
        }

    pending = []
    for key, info in combined.items():
        raw_time = info.get("time", 0)
        if isinstance(raw_time, (int, float)):
            try:
                time_str = datetime.fromtimestamp(raw_time).strftime("%H:%M:%S")
            except (ValueError, OSError):
                time_str = "-"
        else:
            time_str = "-"

        pending.append(
            {
                "key": key,
                "message": str(info.get("message", ""))[:100],
                "severity": _parse_severity(info.get("severity")).value,
                "time": time_str,
                "escalated": int(info.get("escalated", 0) or 0),
            }
        )
    return pending


def acknowledge_alert(alert_key=None):
    """Acknowledge satu alert atau semua alert.

    Returns: jumlah alert yang di-acknowledge.
    """
    file_data = _load_pending_acks_from_file()
    if file_data is None:
        file_data = {}

    if alert_key:
        found = False
        was_in_memory = alert_key in _pending_acks
        was_in_file = alert_key in file_data

        if was_in_memory:
            del _pending_acks[alert_key]
            found = True

        if was_in_file:
            del file_data[alert_key]
            _write_ack_file(file_data)
            found = True

        if found:
            _acknowledged.add(alert_key)
            _append_ack_event(alert_key)
            return 1
        return 0

    count = len(set(file_data.keys()) | set(_pending_acks.keys()))
    for key in list(_pending_acks.keys()):
        _acknowledged.add(key)
    _pending_acks.clear()
    _write_ack_file({})
    if count:
        _append_ack_event("*")
    return count


# ============ CORE ALERT FUNCTIONS ============


def _check_mute():
    """Check if alerts are muted (maintenance mode)."""
    if _MUTE_FILE.exists():
        try:
            with open(_MUTE_FILE, "r", encoding="utf-8") as f:
                expiry = float(f.read().strip())
            if time.time() < expiry:
                return True
            _MUTE_FILE.unlink(missing_ok=True)
        except (OSError, ValueError) as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    return False


def is_alert_delivery_enabled():
    """Gate global untuk pengiriman alert monitor."""
    if not ALERT_REQUIRE_START:
        return True
    try:
        with _ipc_lock():
            raw = _read_json_unlocked(_ALERT_GATE_FILE, {})
        if isinstance(raw, dict):
            return bool(raw.get("enabled", False))
    except Exception as e:
        logger.debug("is_alert_delivery_enabled error: %s", e)
    return False


def set_alert_delivery_enabled(enabled, actor="system", reason=""):
    """Set gate global alert monitor lintas proses (bot + monitor)."""
    payload = {
        "enabled": bool(enabled),
        "updated_at": time.time(),
        "actor": str(actor or "system"),
        "reason": str(reason or ""),
    }
    try:
        with _ipc_lock():
            _write_json_unlocked(_ALERT_GATE_FILE, payload)
    except Exception as e:
        logger.warning("Gagal menulis alert gate: %s", e)
        return False

    if not bool(enabled):
        # Bersihkan antrean agar tidak ada eskalasi stale saat di-enable lagi.
        _recent_alerts.clear()
        _pending_acks.clear()
        _write_ack_file({})
    return True


async def kirim_ke_semua_admin(pesan, parse_mode=None, severity=AlertSeverity.WARNING, alert_key=None):
    """Kirim pesan alert ke semua admin."""
    delivery_enabled = await asyncio.to_thread(is_alert_delivery_enabled)
    if not delivery_enabled:
        return

    is_muted = await asyncio.to_thread(_check_mute)
    if is_muted:
        return

    now = time.time()

    # Digest batching hanya untuk WARNING
    if severity == AlertSeverity.WARNING:
        _recent_alerts.append((now, pesan, severity))
        recent_count = sum(
            1
            for ts, _, sev in _recent_alerts
            if now - ts < ALERT_DIGEST_WINDOW and sev == AlertSeverity.WARNING
        )
        if recent_count > ALERT_DIGEST_THRESHOLD:
            logger.info(f"Alert suppressed (digest mode): {pesan[:50]}...")
            return

    timestamp_str = datetime.now().strftime("%H:%M:%S")
    prefix = _SEVERITY_PREFIX.get(severity, "")
    formatted = f"{prefix} [{timestamp_str}] {pesan}"

    reply_markup = None
    if severity == AlertSeverity.CRITICAL and alert_key:
        _pending_acks[alert_key] = {
            "message": pesan,
            "severity": severity,
            "time": now,
            "escalated": 0,
            # Entry lokal monitor, jangan auto-delete hanya dari diff snapshot.
            "_sync_ack_file": False,
        }
        _save_pending_acks()
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Acknowledge", callback_data="cmd_ack"),
                    InlineKeyboardButton("🔕 Silence 1h", callback_data="confirm_mute_1h"),
                ],
                [InlineKeyboardButton("🏠 Home", callback_data="cmd_start")],
            ]
        )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=formatted,
                parse_mode=parse_mode or "HTML",
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.warning(f"Gagal kirim alert ke {admin_id}: {e}")


async def check_escalation():
    """Check dan kirim escalation untuk CRITICAL alerts yang belum di-ack."""
    delivery_enabled = await asyncio.to_thread(is_alert_delivery_enabled)
    if not delivery_enabled:
        return

    now = time.time()
    escalation_timeout = ALERT_ESCALATION_MINUTES * 60

    # Hydrate snapshot file
    file_data = _load_pending_acks_from_file()
    if isinstance(file_data, dict):
        for key, raw in file_data.items():
            if key not in _pending_acks:
                _pending_acks[key] = {
                    "message": raw.get("message", ""),
                    "severity": _parse_severity(raw.get("severity")),
                    "time": float(raw.get("time", now)),
                    "escalated": int(raw.get("escalated", 0) or 0),
                    "_sync_ack_file": True,
                }

    # Apply explicit ack events from bot process
    ack_events = _consume_ack_events()
    if ack_events:
        ack_all = "*" in ack_events
        target_keys = list(_pending_acks.keys()) if ack_all else list(dict.fromkeys(ack_events))
        for key in target_keys:
            if key in _pending_acks:
                _acknowledged.add(key)
                del _pending_acks[key]
                logger.info(f"Alert '{key}' acknowledged via bot (cross-process).")

    for key, info in list(_pending_acks.items()):
        elapsed = now - float(info.get("time", now))
        if elapsed > escalation_timeout and int(info.get("escalated", 0)) < 3:
            info["escalated"] = int(info.get("escalated", 0)) + 1
            escalation_msg = (
                f"⚠️ <b>ESCALATION #{info['escalated']}</b>\n\n"
                f"{_SEVERITY_PREFIX[AlertSeverity.CRITICAL]} Alert belum di-acknowledge "
                f"selama {int(elapsed // 60)} menit:\n\n"
                f"{str(info.get('message', ''))[:300]}"
            )
            esc_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ Acknowledge", callback_data="cmd_ack"),
                        InlineKeyboardButton("🔕 Silence 1h", callback_data="confirm_mute_1h"),
                    ]
                ]
            )

            if info["escalated"] >= 3 or len(ADMIN_IDS) == 1:
                target_admins = ADMIN_IDS
            else:
                idx = (info["escalated"] - 1) % len(ADMIN_IDS)
                target_admins = [ADMIN_IDS[idx]]

            for admin_id in target_admins:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=escalation_msg,
                        parse_mode="HTML",
                        reply_markup=esc_markup,
                    )
                except Exception as e:
                    logger.warning(f"Gagal kirim escalation ke {admin_id}: {e}")

            info["time"] = now
            _save_pending_acks()


async def send_digest():
    """Kirim digest summary jika alert warning menumpuk."""
    delivery_enabled = await asyncio.to_thread(is_alert_delivery_enabled)
    if not delivery_enabled:
        return

    now = time.time()
    batched = [
        (ts, msg, sev)
        for ts, msg, sev in _recent_alerts
        if now - ts < ALERT_DIGEST_WINDOW and sev != AlertSeverity.CRITICAL
    ]

    if len(batched) <= ALERT_DIGEST_THRESHOLD:
        return

    batched_timestamps = {ts for ts, _, _ in batched}
    fresh_alerts = deque((ts, msg, sev) for ts, msg, sev in _recent_alerts if ts not in batched_timestamps)
    _recent_alerts.clear()
    _recent_alerts.extend(fresh_alerts)

    summary_lines = []
    for _, msg, sev in batched[-10:]:
        prefix = _SEVERITY_PREFIX.get(sev, "")
        summary_lines.append(f"{prefix} {msg[:80]}...")

    digest_msg = (
        f"🔔 <b>ALERT DIGEST</b>\n\n"
        f"<b>{len(batched)}</b> alert dalam {ALERT_DIGEST_WINDOW // 60} menit terakhir:\n\n"
        + "\n".join(summary_lines)
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=digest_msg, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Gagal kirim digest ke {admin_id}: {e}")


# ============ TIMEOUT WRAPPER ============


async def with_timeout(coro, timeout=30, default=None, log_key=None, warn_every_sec=300):
    """Wrapper asyncio timeout protection."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        key = str(log_key or f"timeout:{int(timeout)}")
        now = time.time()
        last_ts = float(_TIMEOUT_LOG_STATE.get(key, 0.0) or 0.0)
        if (now - last_ts) >= max(10, int(warn_every_sec or 300)):
            logger.warning("Operation timed out after %ss [%s]", timeout, key)
            _TIMEOUT_LOG_STATE[key] = now
        return default
    except Exception as e:
        if log_key:
            logger.error("Operation error [%s]: %s", log_key, e)
        else:
            logger.error(f"Operation error: {e}")
        return default



