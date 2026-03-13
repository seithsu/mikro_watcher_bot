import logging
import os
import re
from logging.handlers import RotatingFileHandler

from core.config import LOG_BACKUP_COUNT, LOG_MAX_SIZE


_TOKEN_PATTERNS = (
    re.compile(r"https://api\.telegram\.org/bot\d{6,}:[A-Za-z0-9_-]{20,}"),
    re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}"),
)

_KEYVALUE_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|pass|token|secret|api[_-]?key|mikrotik_pass|telegram_token|authorization)\b(\s*[:=]\s*)([^,\s]+)"
)

_ROUTER_CREDENTIAL_IN_URL = re.compile(r"(?i)(ftp://[^:\s/]+:)([^@\s/]+)(@)")


def _redact_sensitive(text):
    redacted = text
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub("[REDACTED_TELEGRAM_TOKEN]", redacted)
    redacted = _KEYVALUE_SECRET_PATTERN.sub(r"\1\2[REDACTED]", redacted)
    redacted = _ROUTER_CREDENTIAL_IN_URL.sub(r"\1[REDACTED]\3", redacted)
    return redacted


class SensitiveDataFilter(logging.Filter):
    """Redact credential-like patterns from log records."""

    def filter(self, record):
        try:
            rendered = record.getMessage()
        except Exception:
            return True

        redacted = _redact_sensitive(rendered)
        if redacted != rendered:
            record.msg = redacted
            record.args = ()
        return True


def configure_root_logging(level=logging.INFO):
    """Configure root logger with token redaction.

    Jika env `APP_LOG_FILE` diset, log utama juga ditulis ke file rotasi.
    `APP_LOG_TO_STDOUT=false` dapat dipakai agar stdout PM2 tidak menduplikasi log utama.
    """
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handlers = []

    log_file = str(os.getenv("APP_LOG_FILE", "") or "").strip()
    log_to_stdout = str(os.getenv("APP_LOG_TO_STDOUT", "true")).strip().lower() in ("1", "true", "yes", "on")

    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max(1024, int(LOG_MAX_SIZE)),
            backupCount=max(1, int(LOG_BACKUP_COUNT)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SensitiveDataFilter())
        handlers.append(file_handler)

    if log_to_stdout or not handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(SensitiveDataFilter())
        handlers.append(stream_handler)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)

    # Suppress verbose HTTP internals that often include request URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
