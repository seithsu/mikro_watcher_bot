# ============================================
# MIKROTIK/DECORATORS - Retry, Cache & Helpers
# ============================================

import time
import logging
import threading
from functools import wraps
import core.config as cfg

logger = logging.getLogger(__name__)
_last_reset_all_ts = 0.0
_retry_warning_state = {}


# ============ RETRY DECORATOR ============

def with_retry(func):
    """Decorator: retry hingga 3x jika koneksi gagal.

    Menggunakan exponential backoff (1s, 2s) agar tidak
    langsung membanjiri router dengan reconnect.
    Reset koneksi hanya di thread saat ini (thread-local).
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        global _last_reset_all_ts
        from .connection import pool
        disable_global_reset = func.__name__ in {"ping_host"}
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                err = str(e).lower()
                is_session_issue = any(k in err for k in (
                    "not logged in", "not a socket", "10038", "handshake",
                ))
                is_conn_issue = is_session_issue or any(k in err for k in (
                    "timeout", "timed out", "connection", "broken pipe",
                    "refused", "network", "closed",
                ))
                cooldown = 120
                retry_key = f"{func.__name__}|conn" if is_conn_issue else f"{func.__name__}|other"
                now = time.time()
                last_warn = _retry_warning_state.get(retry_key)
                should_warn = (attempt == 2) or (last_warn is None) or ((now - float(last_warn)) >= cooldown)
                if should_warn:
                    logger.warning("[RETRY] %s attempt %s/3: %s", func.__name__, attempt + 1, e)
                    _retry_warning_state[retry_key] = now
                else:
                    logger.debug("[RETRY-suppressed] %s attempt %s/3: %s", func.__name__, attempt + 1, e)

                if attempt == 0 and is_session_issue and not disable_global_reset:
                    # Saat router di-hot-swap, reset_all mempercepat recovery
                    # untuk thread lain yang mungkin memegang koneksi lama.
                    # Namun reset_all yang terlalu sering justru memicu storm.
                    reset_cooldown = max(5, int(getattr(cfg, "MIKROTIK_RESET_ALL_COOLDOWN_SEC", 15)))
                    if (now - _last_reset_all_ts) >= reset_cooldown:
                        pool.reset_all()
                        _last_reset_all_ts = now
                    else:
                        pool.reset()
                else:
                    pool.reset()  # Reset hanya koneksi thread ini (thread-local)
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)  # Exponential backoff: 1s, 2s
    return wrapper


# ============ CACHE DECORATOR ============

def cached(ttl=5, maxsize=64):
    """Decorator: cache response API dengan batas ukuran dan TTL."""

    def decorator(func):
        _entries = {}
        _lock = threading.Lock()

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()

            # Cache hit (tanpa lock agar read concurrent tetap cepat)
            if key in _entries:
                val, ts = _entries[key]
                if now - ts < ttl:
                    return val

            # Cache miss — panggil fungsi asli
            result = func(*args, **kwargs)

            with _lock:
                # Evict jika cache penuh
                if len(_entries) >= maxsize:
                    oldest_key = min(_entries, key=lambda k: _entries[k][1])
                    del _entries[oldest_key]
                _entries[key] = (result, now)

            return result
        return wrapper
    return decorator


# ============ TYPE HELPERS ============

def to_bool(val, default=False):
    """Convert RouterOS value ke bool (handle string dan native type)."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() == 'true'
    return bool(val) if val is not None else default


def to_int(val, default=0):
    """Convert RouterOS value ke int (handle string dan native type)."""
    if isinstance(val, int):
        return val
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def format_bytes(b):
    """Konversi bytes ke human readable."""
    b = to_int(b)
    if b < 1024:
        return f"{b} B"
    elif b < 1024**2:
        return f"{b/1024:.1f} KB"
    elif b < 1024**3:
        return f"{b/(1024**2):.1f} MB"
    else:
        return f"{b/(1024**3):.2f} GB"
