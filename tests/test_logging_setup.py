import logging
import os
from logging.handlers import RotatingFileHandler

import core.logging_setup as ls


def test_redact_sensitive_masks_tokens_and_passwords():
    raw = (
        "hit https://api.telegram.org/bot123456:ABCDEFGHIJKLMNOPQRSTUV/sendMessage "
        "token=123456:ABCDEFGHIJKLMNOPQRSTUV "
        "password=SuperSecret ftp://admin:routerpass@192.168.3.1/file.rsc"
    )
    redacted = ls._redact_sensitive(raw)

    assert "SuperSecret" not in redacted
    assert "routerpass" not in redacted
    assert "ABCDEFGHIJKLMNOPQRSTUV" not in redacted
    assert "[REDACTED]" in redacted
    assert "[REDACTED_TELEGRAM_TOKEN]" in redacted


def test_sensitive_filter_redacts_record_message():
    filt = ls.SensitiveDataFilter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="authorization=BearerSecretToken",
        args=(),
        exc_info=None,
    )

    assert filt.filter(record) is True
    assert "BearerSecretToken" not in record.msg
    assert "[REDACTED]" in record.msg


def test_configure_root_logging_sets_handler_and_levels():
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    old_httpx = logging.getLogger("httpx").level
    old_httpcore = logging.getLogger("httpcore").level

    try:
        ls.configure_root_logging(level=logging.DEBUG)
        assert root.level == logging.DEBUG
        assert len(root.handlers) >= 1
        assert any(
            any(isinstance(f, ls.SensitiveDataFilter) for f in h.filters)
            for h in root.handlers
        )
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        root.handlers.clear()
        for h in old_handlers:
            root.addHandler(h)
        root.setLevel(old_level)
        logging.getLogger("httpx").setLevel(old_httpx)
        logging.getLogger("httpcore").setLevel(old_httpcore)


def test_configure_root_logging_adds_rotating_file_handler(monkeypatch, tmp_path):
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    old_file = os.getenv("APP_LOG_FILE")

    try:
        monkeypatch.setenv("APP_LOG_FILE", str(tmp_path / "app.log"))
        monkeypatch.setenv("APP_LOG_TO_STDOUT", "false")
        ls.configure_root_logging(level=logging.INFO)
        assert any(isinstance(h, RotatingFileHandler) for h in root.handlers)
        assert not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root.handlers)
        logging.getLogger("test").info("hello world")
        assert (tmp_path / "app.log").exists()
    finally:
        root.handlers.clear()
        for h in old_handlers:
            root.addHandler(h)
        root.setLevel(old_level)
        if old_file is None:
            monkeypatch.delenv("APP_LOG_FILE", raising=False)
        else:
            monkeypatch.setenv("APP_LOG_FILE", old_file)
        monkeypatch.delenv("APP_LOG_TO_STDOUT", raising=False)
