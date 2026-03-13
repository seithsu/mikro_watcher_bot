# ============================================
# SERVICES/CONFIG_MANAGER - Runtime Configuration Manager
# Allows changing config values via bot without restart
# ============================================

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from contextlib import contextmanager

from core.config import DATA_DIR

logger = logging.getLogger(__name__)

_CONFIG_FILE = DATA_DIR / "runtime_config.json"
_CONFIG_LOCK_FILE = DATA_DIR / "runtime_config.lock"

# Whitelist: config keys yang boleh diubah via bot, dengan validasi
_CONFIGURABLE = {
    'CPU_THRESHOLD': {'type': int, 'min': 10, 'max': 100, 'label': 'CPU Threshold (%)'},
    'RAM_THRESHOLD': {'type': int, 'min': 10, 'max': 100, 'label': 'RAM Threshold (%)'},
    'DISK_THRESHOLD': {'type': int, 'min': 10, 'max': 100, 'label': 'Disk Threshold (%)'},
    'MONITOR_INTERVAL': {'type': int, 'min': 10, 'max': 86400, 'label': 'Monitor Interval (detik)'},
    'NETWATCH_INTERVAL': {'type': int, 'min': 5, 'max': 3600, 'label': 'Netwatch Interval (detik)'},
    'MONITOR_LOG_INTERVAL': {'type': int, 'min': 5, 'max': 3600, 'label': 'Log Monitor Interval (detik)'},
    'MONITOR_LOG_FETCH_LINES': {'type': int, 'min': 20, 'max': 1000, 'label': 'Log Fetch Lines'},
    'NETWATCH_PING_CONCURRENCY': {'type': int, 'min': 1, 'max': 32, 'label': 'Netwatch Ping Concurrency'},
    'API_ACCOUNT_DEDUP_WINDOW_SEC': {'type': int, 'min': 30, 'max': 86400, 'label': 'API Account Dedup Window (detik)'},
    'PING_FAIL_THRESHOLD': {'type': int, 'min': 1, 'max': 20, 'label': 'Ping Fail Threshold'},
    'RECOVERY_CONFIRM_COUNT': {'type': int, 'min': 1, 'max': 20, 'label': 'Recovery Confirm Count'},
    'RECOVERY_MIN_UP_SECONDS': {'type': int, 'min': 0, 'max': 3600, 'label': 'Recovery Min Stable UP (detik)'},
    'CRITICAL_RECOVERY_CONFIRM_COUNT': {'type': int, 'min': 1, 'max': 20, 'label': 'Critical Recovery Confirm Count'},
    'CRITICAL_RECOVERY_MIN_UP_SECONDS': {'type': int, 'min': 0, 'max': 3600, 'label': 'Critical Recovery Min Stable UP (detik)'},
    'NETWATCH_UP_MIN_SUCCESS_RATIO': {'type': float, 'min': 0.1, 'max': 1.0, 'label': 'Netwatch Min Ping Success Ratio'},
    'RATE_LIMIT_PER_MINUTE': {'type': int, 'min': 1, 'max': 10000, 'label': 'Rate Limit (/menit)'},
    'DHCP_ALERT_THRESHOLD': {'type': int, 'min': 10, 'max': 100, 'label': 'DHCP Alert (%)'},
    'TRAFFIC_THRESHOLD_MBPS': {'type': int, 'min': 0, 'max': 1000000, 'label': 'Traffic Alert (Mbps)'},
    'TRAFFIC_LEAK_THRESHOLD_MBPS': {'type': int, 'min': 0, 'max': 1000000, 'label': 'Traffic Leak Alert per Host (Mbps)'},
    'MONITOR_VPN_ENABLED': {'type': bool, 'label': 'Monitor VPN Enabled'},
    'TOP_BW_ALERT_TOP_N': {'type': int, 'min': 1, 'max': 50, 'label': 'Top BW Alert: Top N Queue'},
    'TOP_BW_ALERT_ENABLED': {'type': bool, 'label': 'Top BW Alert: Enabled'},
    'TOP_BW_ALERT_WARN_MBPS': {'type': int, 'min': 1, 'max': 1000000, 'label': 'Top BW Alert: Warn Threshold (Mbps)'},
    'TOP_BW_ALERT_CRIT_MBPS': {'type': int, 'min': 1, 'max': 1000000, 'label': 'Top BW Alert: Crit Threshold (Mbps)'},
    'TOP_BW_ALERT_CONSECUTIVE_HITS': {'type': int, 'min': 1, 'max': 20, 'label': 'Top BW Alert: Consecutive Hits'},
    'TOP_BW_ALERT_RECOVERY_HITS': {'type': int, 'min': 1, 'max': 20, 'label': 'Top BW Alert: Recovery Hits'},
    'TOP_BW_ALERT_COOLDOWN_SEC': {'type': int, 'min': 0, 'max': 86400, 'label': 'Top BW Alert: Cooldown (detik)'},
    'TOP_BW_ALERT_MIN_TX_MBPS': {'type': int, 'min': 0, 'max': 1000000, 'label': 'Top BW Alert: Min TX (Mbps)'},
    'TOP_BW_ALERT_MIN_RX_MBPS': {'type': int, 'min': 0, 'max': 1000000, 'label': 'Top BW Alert: Min RX (Mbps)'},
    'DAILY_REPORT_HOUR': {'type': int, 'min': 0, 'max': 23, 'label': 'Daily Report Jam'},
    'ALERT_ESCALATION_MINUTES': {'type': int, 'min': 1, 'max': 10000, 'label': 'Alert Escalation (menit)'},
    'ALERT_DIGEST_THRESHOLD': {'type': int, 'min': 1, 'max': 10000, 'label': 'Digest Threshold'},
    'ALERT_DIGEST_WINDOW': {'type': int, 'min': 10, 'max': 86400, 'label': 'Digest Window (detik)'},
    'ALERT_REQUIRE_START': {'type': bool, 'label': 'Alert Require /start'},
    'MIKROTIK_RESET_ALL_COOLDOWN_SEC': {'type': int, 'min': 5, 'max': 3600, 'label': 'reset_all Cooldown (detik)'},
}

# Categories for organized display
_CATEGORIES = {
    '⚙️ Monitoring': [
        'CPU_THRESHOLD', 'RAM_THRESHOLD', 'DISK_THRESHOLD',
        'MONITOR_INTERVAL', 'NETWATCH_INTERVAL', 'MONITOR_LOG_INTERVAL', 'MONITOR_LOG_FETCH_LINES',
        'NETWATCH_PING_CONCURRENCY', 'API_ACCOUNT_DEDUP_WINDOW_SEC', 'MONITOR_VPN_ENABLED',
    ],
    '🔔 Alert': [
        'PING_FAIL_THRESHOLD', 'RECOVERY_CONFIRM_COUNT',
        'RECOVERY_MIN_UP_SECONDS', 'CRITICAL_RECOVERY_CONFIRM_COUNT', 'CRITICAL_RECOVERY_MIN_UP_SECONDS',
        'NETWATCH_UP_MIN_SUCCESS_RATIO',
        'ALERT_ESCALATION_MINUTES', 'ALERT_DIGEST_THRESHOLD',
        'ALERT_DIGEST_WINDOW', 'ALERT_REQUIRE_START',
    ],
    '📊 Traffic & DHCP': ['TRAFFIC_THRESHOLD_MBPS', 'TRAFFIC_LEAK_THRESHOLD_MBPS', 'DHCP_ALERT_THRESHOLD'],
    '🚨 Top BW Alert': [
        'TOP_BW_ALERT_ENABLED',
        'TOP_BW_ALERT_TOP_N',
        'TOP_BW_ALERT_WARN_MBPS',
        'TOP_BW_ALERT_CRIT_MBPS',
        'TOP_BW_ALERT_CONSECUTIVE_HITS',
        'TOP_BW_ALERT_RECOVERY_HITS',
        'TOP_BW_ALERT_COOLDOWN_SEC',
        'TOP_BW_ALERT_MIN_TX_MBPS',
        'TOP_BW_ALERT_MIN_RX_MBPS',
    ],
    '🕐 Schedule': ['DAILY_REPORT_HOUR'],
    '🛡️ Rate Limit': ['RATE_LIMIT_PER_MINUTE', 'MIKROTIK_RESET_ALL_COOLDOWN_SEC'],
}

# Capture .env defaults SEBELUM override apapun diterapkan
# Ini memastikan reset_config() benar-benar mengembalikan ke default asli
import core.config as _cfg_module
_DEFAULTS = dict(getattr(_cfg_module, "_DEFAULT_OVERRIDABLES", {}))
for _k in _CONFIGURABLE:
    _DEFAULTS.setdefault(_k, getattr(_cfg_module, _k, None))

_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


def _parse_bool_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _BOOL_TRUE:
            return True
        if text in _BOOL_FALSE:
            return False
    raise ValueError("invalid bool")


@contextmanager
def _config_lock(timeout=2.0, poll_interval=0.05):
    """Best-effort inter-process lock for runtime_config.json."""
    start = time.time()
    fd = None
    lock_path = str(_CONFIG_LOCK_FILE)
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            break
        except FileExistsError:
            if (time.time() - start) >= timeout:
                raise TimeoutError("runtime config lock timeout")
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
        except OSError:
            pass


def _sanitize_overrides(overrides):
    """Drop invalid keys/types/ranges dari file override."""
    if not isinstance(overrides, dict):
        return {}
    clean = {}
    for key, value in overrides.items():
        meta = _CONFIGURABLE.get(key)
        if not meta:
            continue
        if meta['type'] is bool:
            try:
                clean[key] = _parse_bool_value(value)
            except ValueError:
                continue
        else:
            try:
                typed = meta['type'](value)
            except (TypeError, ValueError):
                continue
            if typed < meta['min'] or typed > meta['max']:
                continue
            clean[key] = typed
    return clean

def _apply_overrides_on_startup():
    """Apply saved runtime overrides saat module di-import."""
    overrides = _load_overrides()
    for key, value in overrides.items():
        if key in _CONFIGURABLE:
            setattr(_cfg_module, key, value)

# Auto-apply overrides at import time (moved to bottom of file)
def _load_overrides():
    """Load runtime overrides dari file."""
    if _CONFIG_FILE.exists():
        try:
            with _config_lock():
                with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            return _sanitize_overrides(raw)
        except Exception as e:
            logger.debug("Suppressed non-fatal exception: %s", e)
    return {}


def _save_overrides(overrides):
    """Save runtime overrides ke file."""
    tmp_path = None
    try:
        clean = _sanitize_overrides(overrides)
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _config_lock():
            fd, tmp_path = tempfile.mkstemp(
                prefix=f"{_CONFIG_FILE.name}.",
                suffix=".tmp",
                dir=str(_CONFIG_FILE.parent),
                text=True,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(clean, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(_CONFIG_FILE))
    except Exception as e:
        logger.error(f"Gagal save runtime config: {e}")
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def get_config(key):
    """Get config value (runtime override > .env default).
    
    Returns: (value, is_overridden)
    """
    import core.config as cfg
    overrides = _load_overrides()
    
    if key in overrides:
        return overrides[key], True
    
    default = getattr(cfg, key, None)
    return default, False


def get_all_configs():
    """Get semua configurable values beserta status override.
    
    Returns: dict { category: [ { key, label, value, is_overridden, min, max } ] }
    """
    import core.config as cfg
    overrides = _load_overrides()
    
    result = {}
    for category, keys in _CATEGORIES.items():
        items = []
        for key in keys:
            meta = _CONFIGURABLE[key]
            is_overridden = key in overrides
            value = overrides[key] if is_overridden else getattr(cfg, key, '?')
            items.append({
                'key': key,
                'label': meta['label'],
                'value': value,
                'is_overridden': is_overridden,
                'min': meta.get('min'),
                'max': meta.get('max'),
                'type': 'bool' if meta['type'] is bool else meta['type'].__name__,
            })
        result[category] = items
    
    return result


def set_config(key, value, admin_id=None, username=None):
    """Set config value. Returns (success: bool, message: str).
    
    Validates key & value, saves to runtime_config.json,
    and applies to running config module.
    """
    if key not in _CONFIGURABLE:
        return False, f"Key '{key}' tidak ditemukan. Gunakan /config untuk melihat key yang valid."
    
    meta = _CONFIGURABLE[key]
    
    # Type conversion & validation
    if meta['type'] is bool:
        try:
            typed_value = _parse_bool_value(value)
        except ValueError:
            return False, "Nilai boolean harus true/false (atau 1/0, yes/no, on/off)."
    else:
        try:
            typed_value = meta['type'](value)
        except (ValueError, TypeError):
            return False, f"Nilai harus berupa {meta['type'].__name__}."

        if typed_value < meta['min'] or typed_value > meta['max']:
            return False, f"Nilai harus antara {meta['min']} - {meta['max']}."

    import core.config as cfg
    overrides = _load_overrides()

    # Guardrail: Top BW CRIT tidak boleh di bawah WARN.
    if key == 'TOP_BW_ALERT_WARN_MBPS':
        crit_now = overrides.get('TOP_BW_ALERT_CRIT_MBPS', getattr(cfg, 'TOP_BW_ALERT_CRIT_MBPS', typed_value))
        if typed_value > crit_now:
            return False, f"Nilai WARN ({typed_value}) tidak boleh lebih besar dari CRIT saat ini ({crit_now})."
    if key == 'TOP_BW_ALERT_CRIT_MBPS':
        warn_now = overrides.get('TOP_BW_ALERT_WARN_MBPS', getattr(cfg, 'TOP_BW_ALERT_WARN_MBPS', typed_value))
        if typed_value < warn_now:
            return False, f"Nilai CRIT ({typed_value}) tidak boleh lebih kecil dari WARN saat ini ({warn_now})."
    
    # Save to file
    old_value = overrides.get(key, getattr(cfg, key, '?'))
    overrides[key] = typed_value
    _save_overrides(overrides)
    
    # Apply to running config module
    setattr(cfg, key, typed_value)
    
    # Audit log
    try:
        from core import database
        database.audit_log(
            admin_id or 0,
            username or 'system',
            '/config set',
            f"{key}: {old_value} → {typed_value}",
            'berhasil'
        )
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    logger.info(f"Config updated: {key} = {typed_value} (by {username})")
    return True, f"✅ {meta['label']}: <b>{old_value}</b> → <b>{typed_value}</b>"


def reset_config(key, admin_id=None, username=None):
    """Reset config ke default .env value. Returns (success: bool, message: str)."""
    if key not in _CONFIGURABLE:
        return False, f"Key '{key}' tidak ditemukan."
    
    overrides = _load_overrides()
    if key not in overrides:
        return False, f"Key '{key}' tidak sedang di-override. Sudah menggunakan nilai default."
    
    old_value = overrides[key]
    del overrides[key]
    _save_overrides(overrides)
    
    # Restore actual .env default from captured _DEFAULTS (A3 fix)
    meta = _CONFIGURABLE[key]
    default_value = _DEFAULTS.get(key)
    # Apply the true default back to the running config module
    if default_value is not None:
        setattr(_cfg_module, key, default_value)
    
    try:
        from core import database
        database.audit_log(
            admin_id or 0,
            username or 'system',
            '/config reset',
            f"{key}: {old_value} → {default_value} (default)",
            'berhasil'
        )
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    logger.info(f"Config reset: {key} → {default_value} (by {username})")
    return True, f"✅ {meta['label']} di-reset ke default: <b>{default_value}</b>"


def get_configurable_keys():
    """Return list semua configurable keys."""
    return list(_CONFIGURABLE.keys())

# Auto-apply overrides at import time
_apply_overrides_on_startup()
