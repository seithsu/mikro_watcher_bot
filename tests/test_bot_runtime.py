# ============================================
# TEST_BOT_RUNTIME - Runtime helpers in bot.py
# ============================================

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import time

import pytest

import bot


@pytest.mark.asyncio
async def test_cleanup_bot_data_cache_removes_stale_entries():
    now = time.time()
    bot_data = {
        "scan_result_ether1": [{"ip": "1.1.1.1"}],
        "ts_scan_result_ether1": now - 1900,  # stale (>1800)
        "freeip_res_192.168.1.0/24": {"free_count": 10},
        "ts_freeip_res_192.168.1.0/24": now - 60,  # fresh
    }
    ctx = SimpleNamespace(application=SimpleNamespace(bot_data=bot_data))

    await bot._cleanup_bot_data_cache(ctx)

    assert "scan_result_ether1" not in bot_data
    assert "ts_scan_result_ether1" not in bot_data
    assert "freeip_res_192.168.1.0/24" in bot_data


@pytest.mark.asyncio
async def test_cleanup_bot_data_cache_tolerates_non_string_key_and_bad_timestamp():
    bot_data = {
        object(): "ignore-me",
        "wol_test": "AA:BB",
        "ts_wol_test": "bad-ts",
    }
    ctx = SimpleNamespace(application=SimpleNamespace(bot_data=bot_data))

    await bot._cleanup_bot_data_cache(ctx)

    assert "wol_test" not in bot_data
    assert "ts_wol_test" not in bot_data


@pytest.mark.asyncio
async def test_cleanup_bot_data_cache_logs_debug_on_internal_error(monkeypatch):
    logger = MagicMock()
    ctx = SimpleNamespace(application=SimpleNamespace())
    monkeypatch.setattr(bot, "logger", logger)

    await bot._cleanup_bot_data_cache(ctx)

    logger.debug.assert_called_once()


def test_schedule_daily_jobs_sets_signature(monkeypatch):
    job_queue = MagicMock()
    job_queue.get_jobs_by_name.return_value = []
    app = SimpleNamespace(job_queue=job_queue, bot_data={})

    monkeypatch.setattr(bot.cfg, "DAILY_REPORT_HOUR", 8, raising=False)
    monkeypatch.setattr(bot.cfg, "AUTO_BACKUP_DAY", "monday", raising=False)

    bot._schedule_daily_jobs(app)

    assert app.bot_data.get("_schedule_signature") == (8, "monday")
    assert job_queue.run_daily.call_count == 2


def test_schedule_daily_jobs_returns_when_job_queue_missing():
    app = SimpleNamespace(job_queue=None, bot_data={})

    bot._schedule_daily_jobs(app)

    assert app.bot_data == {}


def test_schedule_daily_jobs_removes_existing_jobs(monkeypatch):
    old_job_1 = MagicMock()
    old_job_2 = MagicMock()
    job_queue = MagicMock()
    job_queue.get_jobs_by_name.side_effect = [[old_job_1], [old_job_2]]
    app = SimpleNamespace(job_queue=job_queue, bot_data={})

    monkeypatch.setattr(bot.cfg, "DAILY_REPORT_HOUR", 8, raising=False)
    monkeypatch.setattr(bot.cfg, "AUTO_BACKUP_DAY", "monday", raising=False)

    bot._schedule_daily_jobs(app)

    old_job_1.schedule_removal.assert_called_once()
    old_job_2.schedule_removal.assert_called_once()


@pytest.mark.asyncio
async def test_error_handler_returns_generic_message():
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    update = SimpleNamespace(effective_message=msg)
    context = SimpleNamespace(error=Exception("password=SuperSecret123"))

    await bot.error_handler(update, context)

    msg.reply_text.assert_called_once()
    sent = msg.reply_text.call_args[0][0]
    assert "password=SuperSecret123" not in sent
    assert "error internal" in sent.lower()


@pytest.mark.asyncio
async def test_sync_scheduled_jobs_reschedules_when_signature_changed(monkeypatch):
    context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
    schedule = MagicMock()
    reload_runtime = MagicMock()
    reload_router = MagicMock()

    monkeypatch.setattr(bot, "_schedule_daily_jobs", schedule)
    monkeypatch.setattr(bot.cfg, "reload_runtime_overrides", reload_runtime, raising=False)
    monkeypatch.setattr(bot.cfg, "reload_router_env", reload_router, raising=False)
    monkeypatch.setattr(bot.cfg, "DAILY_REPORT_HOUR", 9, raising=False)
    monkeypatch.setattr(bot.cfg, "AUTO_BACKUP_DAY", "friday", raising=False)

    await bot._sync_scheduled_jobs(context)

    reload_runtime.assert_called_once()
    reload_router.assert_called_once()
    schedule.assert_called_once_with(context.application)


@pytest.mark.asyncio
async def test_sync_scheduled_jobs_skips_when_signature_same(monkeypatch):
    app = SimpleNamespace(bot_data={"_schedule_signature": (9, "friday")})
    context = SimpleNamespace(application=app)
    schedule = MagicMock()
    reload_runtime = MagicMock()
    reload_router = MagicMock()

    monkeypatch.setattr(bot, "_schedule_daily_jobs", schedule)
    monkeypatch.setattr(bot.cfg, "reload_runtime_overrides", reload_runtime, raising=False)
    monkeypatch.setattr(bot.cfg, "reload_router_env", reload_router, raising=False)
    monkeypatch.setattr(bot.cfg, "DAILY_REPORT_HOUR", 9, raising=False)
    monkeypatch.setattr(bot.cfg, "AUTO_BACKUP_DAY", "friday", raising=False)

    await bot._sync_scheduled_jobs(context)

    reload_runtime.assert_called_once()
    reload_router.assert_called_once()
    schedule.assert_not_called()


@pytest.mark.asyncio
async def test_sync_scheduled_jobs_logs_warning_on_reload_error(monkeypatch):
    context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
    logger = MagicMock()

    def boom(*args, **kwargs):
        raise RuntimeError("reload failed")

    monkeypatch.setattr(bot, "logger", logger)
    monkeypatch.setattr(bot.cfg, "reload_runtime_overrides", boom, raising=False)
    monkeypatch.setattr(bot.cfg, "reload_router_env", MagicMock(), raising=False)

    await bot._sync_scheduled_jobs(context)

    logger.warning.assert_called_once()
    assert "sinkronisasi scheduler" in logger.warning.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_error_handler_ignores_telegram_network_glitch(monkeypatch):
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    update = SimpleNamespace(effective_message=msg)
    context = SimpleNamespace(error=Exception("TimedOut getaddrinfo failed"))
    logger = MagicMock()
    monkeypatch.setattr(bot, "logger", logger)

    await bot.error_handler(update, context)

    msg.reply_text.assert_not_called()
    logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_error_handler_logs_debug_when_reply_fails(monkeypatch):
    msg = MagicMock()
    msg.reply_text = AsyncMock(side_effect=RuntimeError("reply failed"))
    update = SimpleNamespace(effective_message=msg)
    context = SimpleNamespace(error=Exception("fatal"))
    logger = MagicMock()
    monkeypatch.setattr(bot, "logger", logger)

    await bot.error_handler(update, context)

    logger.error.assert_called()
    logger.debug.assert_called_once()


def test_main_returns_early_when_token_empty(monkeypatch):
    configure = MagicMock()
    hooks = MagicMock()
    rotate = MagicMock()
    builder = MagicMock()

    monkeypatch.setattr(bot, "TOKEN", "", raising=False)
    monkeypatch.setattr(bot, "configure_root_logging", configure)
    monkeypatch.setattr(bot, "install_global_exception_hooks", hooks)
    monkeypatch.setattr(bot, "rotate_log", rotate)
    monkeypatch.setattr(bot.Application, "builder", builder)
    monkeypatch.setattr(bot.cfg, "MIKROTIK_USE_SSL", False, raising=False)
    monkeypatch.setattr(bot.cfg, "MIKROTIK_TLS_VERIFY", True, raising=False)

    bot.main()

    configure.assert_called_once()
    hooks.assert_called_once_with(process_name="bot")
    rotate.assert_not_called()
    builder.assert_not_called()


def test_main_warns_when_tls_verify_disabled(monkeypatch):
    configure = MagicMock()
    hooks = MagicMock()
    rotate = MagicMock()
    builder = MagicMock()
    logger = MagicMock()

    monkeypatch.setattr(bot, "TOKEN", "", raising=False)
    monkeypatch.setattr(bot, "configure_root_logging", configure)
    monkeypatch.setattr(bot, "install_global_exception_hooks", hooks)
    monkeypatch.setattr(bot, "rotate_log", rotate)
    monkeypatch.setattr(bot.Application, "builder", builder)
    monkeypatch.setattr(bot, "logger", logger)
    monkeypatch.setattr(bot.cfg, "MIKROTIK_USE_SSL", True, raising=False)
    monkeypatch.setattr(bot.cfg, "MIKROTIK_TLS_VERIFY", False, raising=False)

    bot.main()

    logger.warning.assert_called_once()
    rotate.assert_not_called()
    builder.assert_not_called()


def test_main_builds_handlers_and_runs_polling(monkeypatch):
    class FakeJobQueue:
        def __init__(self):
            self.daily = []
            self.repeating = []

        def get_jobs_by_name(self, _name):
            return []

        def run_daily(self, cb, **kwargs):
            self.daily.append((cb, kwargs))

        def run_repeating(self, cb, **kwargs):
            self.repeating.append((cb, kwargs))

    class FakeApp:
        def __init__(self):
            self.job_queue = FakeJobQueue()
            self.bot_data = {}
            self.handlers = []
            self.error_handlers = []
            self.poll_kwargs = None

        def add_handler(self, handler):
            self.handlers.append(handler)

        def add_error_handler(self, handler):
            self.error_handlers.append(handler)

        def run_polling(self, **kwargs):
            self.poll_kwargs = kwargs

    class FakeBuilder:
        def __init__(self, app):
            self.app = app
            self.token_value = None
            self.post_init_fn = None
            self.post_shutdown_fn = None

        def token(self, value):
            self.token_value = value
            return self

        def post_init(self, fn):
            self.post_init_fn = fn
            return self

        def post_shutdown(self, fn):
            self.post_shutdown_fn = fn
            return self

        def build(self):
            return self.app

    fake_app = FakeApp()
    fake_builder = FakeBuilder(fake_app)

    monkeypatch.setattr(bot, "TOKEN", "123:TEST_TOKEN", raising=False)
    monkeypatch.setattr(bot, "configure_root_logging", MagicMock())
    monkeypatch.setattr(bot, "install_global_exception_hooks", MagicMock())
    monkeypatch.setattr(bot, "rotate_log", MagicMock())
    monkeypatch.setattr(bot.Application, "builder", lambda: fake_builder)
    monkeypatch.setattr(bot, "CallbackQueryHandler", lambda *a, **k: ("cb", a, k))
    monkeypatch.setattr(bot, "CommandHandler", lambda *a, **k: ("cmd", a, k))
    monkeypatch.setattr(bot, "MessageHandler", lambda *a, **k: ("msg", a, k))
    monkeypatch.setattr(bot.cfg, "MIKROTIK_USE_SSL", False, raising=False)
    monkeypatch.setattr(bot.cfg, "MIKROTIK_TLS_VERIFY", True, raising=False)
    monkeypatch.setattr(bot.cfg, "DAILY_REPORT_HOUR", 7, raising=False)
    monkeypatch.setattr(bot.cfg, "AUTO_BACKUP_DAY", "sunday", raising=False)
    monkeypatch.setattr(bot.cfg, "RATE_LIMIT_PER_MINUTE", 20, raising=False)
    monkeypatch.setattr(bot.cfg, "REBOOT_COOLDOWN", 300, raising=False)
    monkeypatch.setattr(bot.cfg, "ADMIN_IDS", [111], raising=False)

    bot.main()

    assert fake_builder.token_value == "123:TEST_TOKEN"
    assert fake_builder.post_init_fn is bot.post_init
    assert fake_builder.post_shutdown_fn is bot.post_shutdown
    assert len(fake_app.handlers) > 30
    assert len(fake_app.error_handlers) == 1
    assert len(fake_app.job_queue.daily) == 2
    assert len(fake_app.job_queue.repeating) == 2
    assert fake_app.poll_kwargs == {
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": True,
    }


@pytest.mark.asyncio
async def test_callback_reboot_returns_when_access_denied(monkeypatch):
    query = SimpleNamespace(
        data="reboot_confirm",
        from_user=SimpleNamespace(id=1, username="admin"),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    update = SimpleNamespace(callback_query=query)
    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=True))

    await bot.callback_reboot(update, SimpleNamespace())

    query.answer.assert_not_called()
    query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_callback_reboot_confirm_success(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(
        data="reboot_confirm",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "reboot_router", MagicMock())
    monkeypatch.setattr(bot, "set_last_reboot_time", MagicMock())
    monkeypatch.setattr(bot, "catat", MagicMock())
    monkeypatch.setattr(bot.database, "audit_log", MagicMock())

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_reboot(update, SimpleNamespace())

    query.answer.assert_called_once()
    query.edit_message_text.assert_called_once()
    bot.set_last_reboot_time.assert_called_once()
    bot.database.audit_log.assert_called_once()


@pytest.mark.asyncio
async def test_callback_reboot_confirm_failure(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(
        data="reboot_confirm",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "reboot_router", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(bot, "set_last_reboot_time", MagicMock())
    monkeypatch.setattr(bot, "catat", MagicMock())
    monkeypatch.setattr(bot.database, "audit_log", MagicMock())

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_reboot(update, SimpleNamespace())

    message.reply_text.assert_called_once()
    bot.set_last_reboot_time.assert_not_called()


@pytest.mark.asyncio
async def test_callback_reboot_cancel(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    query = SimpleNamespace(
        data="reboot_cancel",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    update = SimpleNamespace(callback_query=query)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))

    await bot.callback_reboot(update, SimpleNamespace())

    query.answer.assert_called_once_with("Reboot dibatalkan.")
    query.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_callback_backup_bot_success(monkeypatch, tmp_path):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock(), reply_document=AsyncMock(), delete=AsyncMock())
    query = SimpleNamespace(
        data="backup_bot",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)
    backup_file = tmp_path / "bot-backup.zip"
    backup_file.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "backup_semua", MagicMock(return_value=str(backup_file)))
    monkeypatch.setattr(bot, "catat", MagicMock())
    monkeypatch.setattr(bot.database, "audit_log", MagicMock())

    await bot.callback_backup(update, SimpleNamespace())

    query.answer.assert_called_once()
    message.reply_document.assert_called_once()
    message.delete.assert_called_once()
    assert not backup_file.exists()


@pytest.mark.asyncio
async def test_callback_backup_returns_when_access_denied(monkeypatch):
    query = SimpleNamespace(
        data="backup_bot",
        from_user=SimpleNamespace(id=1, username="admin"),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock(), reply_document=AsyncMock(), delete=AsyncMock()),
    )
    update = SimpleNamespace(callback_query=query)
    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=True))

    await bot.callback_backup(update, SimpleNamespace())

    query.answer.assert_not_called()


@pytest.mark.asyncio
async def test_callback_backup_rsc_success(monkeypatch, tmp_path):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock(), reply_document=AsyncMock(), delete=AsyncMock())
    query = SimpleNamespace(
        data="backup_rsc",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)
    backup_file = tmp_path / "router-export.rsc"
    backup_file.write_text("export", encoding="utf-8")

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "export_router_backup_ftp", MagicMock(return_value=str(backup_file)))
    monkeypatch.setattr(bot, "catat", MagicMock())
    monkeypatch.setattr(bot.database, "audit_log", MagicMock())

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_backup(update, SimpleNamespace())

    message.reply_document.assert_called_once()
    message.delete.assert_called_once()
    assert not backup_file.exists()


@pytest.mark.asyncio
async def test_callback_backup_rsc_fallback_failure(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock(), reply_document=AsyncMock(), delete=AsyncMock())
    query = SimpleNamespace(
        data="backup_rsc",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "export_router_backup_ftp", MagicMock(side_effect=RuntimeError("ftp fail")))
    monkeypatch.setattr(bot, "export_router_backup", MagicMock(side_effect=RuntimeError("api fail")))
    monkeypatch.setattr(bot, "catat", MagicMock())
    monkeypatch.setattr(bot.database, "audit_log", MagicMock())

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_backup(update, SimpleNamespace())

    query.edit_message_text.assert_called_once()
    message.reply_text.assert_called_once()
    message.delete.assert_called_once()


@pytest.mark.asyncio
async def test_callback_backup_full_success(monkeypatch, tmp_path):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock(), reply_document=AsyncMock(), delete=AsyncMock())
    query = SimpleNamespace(
        data="backup_full",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)
    backup_file = tmp_path / "router.backup"
    backup_file.write_text("binary", encoding="utf-8")

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "export_router_backup_ftp", MagicMock(return_value=str(backup_file)))
    monkeypatch.setattr(bot, "catat", MagicMock())
    monkeypatch.setattr(bot.database, "audit_log", MagicMock())

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_backup(update, SimpleNamespace())

    message.reply_document.assert_called_once()
    message.delete.assert_called_once()
    assert not backup_file.exists()


@pytest.mark.asyncio
async def test_callback_backup_full_fallback_failure(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock(), reply_document=AsyncMock(), delete=AsyncMock())
    query = SimpleNamespace(
        data="backup_full",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "export_router_backup_ftp", MagicMock(side_effect=RuntimeError("ftp fail")))
    monkeypatch.setattr(bot, "export_router_backup", MagicMock(side_effect=RuntimeError("api fail")))
    monkeypatch.setattr(bot, "catat", MagicMock())
    monkeypatch.setattr(bot.database, "audit_log", MagicMock())

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_backup(update, SimpleNamespace())

    query.edit_message_text.assert_called_once()
    message.reply_text.assert_called_once()
    message.delete.assert_called_once()


@pytest.mark.asyncio
async def test_callback_backup_reports_outer_error(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock(), reply_document=AsyncMock(), delete=AsyncMock())
    query = SimpleNamespace(
        data="backup_bot",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "backup_semua", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(bot, "catat", MagicMock())

    await bot.callback_backup(update, SimpleNamespace())

    message.reply_text.assert_called_once()
    message.delete.assert_not_called()


@pytest.mark.asyncio
async def test_callback_unban_success(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    query = SimpleNamespace(
        data="unban_192.168.3.3",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    update = SimpleNamespace(callback_query=query)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "unblock_ip", MagicMock(return_value=True))
    monkeypatch.setattr(bot, "catat", MagicMock())

    await bot.callback_unban(update, SimpleNamespace())

    query.answer.assert_called_once_with("Memproses unban...")
    query.edit_message_text.assert_called_once()
    bot.catat.assert_called_once()


@pytest.mark.asyncio
async def test_callback_unban_not_found(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    query = SimpleNamespace(
        data="unban_192.168.3.99",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    update = SimpleNamespace(callback_query=query)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "unblock_ip", MagicMock(return_value=False))
    monkeypatch.setattr(bot, "catat", MagicMock())

    await bot.callback_unban(update, SimpleNamespace())

    query.edit_message_text.assert_called_once()
    rendered = query.edit_message_text.call_args[0][0]
    assert "tidak ditemukan" in rendered


@pytest.mark.asyncio
async def test_callback_unban_error(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(
        data="unban_192.168.3.99",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "unblock_ip", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(bot, "catat", MagicMock())

    await bot.callback_unban(update, SimpleNamespace())

    message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_callback_wol_expired_session_clears_cache(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    query = SimpleNamespace(
        data="wol_AABBCC",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    bot_data = {"wol_AABBCC": "AA:BB:CC", "ts_wol_AABBCC": time.time() - 301}
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data=bot_data)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))

    await bot.callback_wol(update, context)

    query.answer.assert_called_once_with("Sesi kadaluarsa. Silakan ketik /wol lagi.")
    assert "wol_AABBCC" not in bot_data
    assert "ts_wol_AABBCC" not in bot_data
    query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_callback_wol_success(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    query = SimpleNamespace(
        data="wol_AABBCCDDEEFF",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    bot_data = {
        "wol_AABBCCDDEEFF": "AA:BB:CC:DD:EE:FF",
        "ts_wol_AABBCCDDEEFF": time.time(),
    }
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data=bot_data)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(
        bot,
        "get_interfaces",
        MagicMock(
            return_value=[
                {"name": "bridge", "running": True, "type": "bridge"},
                {"name": "ether2", "running": True, "type": "ether"},
                {"name": "ether1", "running": True, "type": "ether"},
                {"name": "wlan1", "running": True, "type": "wlan"},
            ]
        ),
    )
    monkeypatch.setattr(bot, "send_wol", MagicMock())
    monkeypatch.setattr(bot, "catat", MagicMock())

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_wol(update, context)

    assert bot.send_wol.call_count == 2
    query.edit_message_text.assert_called_once()
    assert "wol_AABBCCDDEEFF" not in bot_data
    assert "ts_wol_AABBCCDDEEFF" not in bot_data


@pytest.mark.asyncio
async def test_callback_wol_invalid_timestamp_is_expired(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    query = SimpleNamespace(
        data="wol_AABBCC",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    bot_data = {"wol_AABBCC": "AA:BB:CC", "ts_wol_AABBCC": "not-a-number"}
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data=bot_data)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))

    await bot.callback_wol(update, context)

    query.answer.assert_called_once_with("Sesi kadaluarsa. Silakan ketik /wol lagi.")
    query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_callback_wol_reports_when_no_valid_interfaces(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    query = SimpleNamespace(
        data="wol_AABBCCDDEEFF",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    bot_data = {
        "wol_AABBCCDDEEFF": "AA:BB:CC:DD:EE:FF",
        "ts_wol_AABBCCDDEEFF": time.time(),
    }
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data=bot_data)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(
        bot,
        "get_interfaces",
        MagicMock(return_value=[{"name": "ether1", "running": True, "type": "ether"}]),
    )
    monkeypatch.setattr(bot, "send_wol", MagicMock())

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_wol(update, context)

    query.edit_message_text.assert_called_once()
    rendered = query.edit_message_text.call_args[0][0]
    assert "tidak ada interface lan valid" in rendered.lower()


@pytest.mark.asyncio
async def test_callback_wol_logs_interface_send_errors(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    query = SimpleNamespace(
        data="wol_AABBCCDDEEFF",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    bot_data = {
        "wol_AABBCCDDEEFF": "AA:BB:CC:DD:EE:FF",
        "ts_wol_AABBCCDDEEFF": time.time(),
    }
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data=bot_data)
    logger = MagicMock()

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(
        bot,
        "get_interfaces",
        MagicMock(return_value=[{"name": "bridge", "running": True, "type": "bridge"}]),
    )
    monkeypatch.setattr(bot, "send_wol", MagicMock(side_effect=RuntimeError("send failed")))
    monkeypatch.setattr(bot, "logger", logger)

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_wol(update, context)

    logger.debug.assert_called()
    query.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_callback_wol_reports_global_error(monkeypatch):
    user = SimpleNamespace(id=12345, username="admin")
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(
        data="wol_AABBCCDDEEFF",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    bot_data = {
        "wol_AABBCCDDEEFF": "AA:BB:CC:DD:EE:FF",
        "ts_wol_AABBCCDDEEFF": time.time(),
    }
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data=bot_data)

    monkeypatch.setattr(bot, "_check_access", AsyncMock(return_value=False))
    monkeypatch.setattr(bot, "get_interfaces", MagicMock(side_effect=RuntimeError("iface fail")))
    monkeypatch.setattr(bot, "catat", MagicMock())

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", fake_to_thread)

    await bot.callback_wol(update, context)

    message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_post_init_sets_executor_and_commands(monkeypatch):
    class DummyLoop:
        def __init__(self):
            self.executor = None
            self.exception_handler = None

        def set_default_executor(self, executor):
            self.executor = executor

        def set_exception_handler(self, handler):
            self.exception_handler = handler

    loop = DummyLoop()
    app = SimpleNamespace(bot=SimpleNamespace(set_my_commands=AsyncMock()))
    monkeypatch.setattr(bot.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(bot.cfg, "ASYNC_THREAD_WORKERS", 4, raising=False)
    monkeypatch.setattr(bot, "_default_executor", None)

    await bot.post_init(app)

    assert loop.executor is not None
    assert loop.exception_handler is not None
    app.bot.set_my_commands.assert_called_once()
    assert bot._default_executor is loop.executor
    await bot.post_shutdown(app)


@pytest.mark.asyncio
async def test_post_shutdown_clears_executor(monkeypatch):
    class DummyExecutor:
        def __init__(self):
            self.calls = []

        def shutdown(self, **kwargs):
            self.calls.append(kwargs)

    executor = DummyExecutor()
    monkeypatch.setattr(bot, "_default_executor", executor)

    await bot.post_shutdown(SimpleNamespace())

    assert executor.calls == [{"wait": False, "cancel_futures": True}]
    assert bot._default_executor is None


@pytest.mark.asyncio
async def test_handle_unknown_text_deletes_message():
    message = SimpleNamespace(delete=AsyncMock())
    update = SimpleNamespace(message=message)

    await bot.handle_unknown_text(update, SimpleNamespace())

    message.delete.assert_called_once()


@pytest.mark.asyncio
async def test_handle_unknown_text_logs_debug_on_delete_failure(monkeypatch):
    logger = MagicMock()
    message = SimpleNamespace(delete=AsyncMock(side_effect=RuntimeError("delete failed")))
    update = SimpleNamespace(message=message)
    monkeypatch.setattr(bot, "logger", logger)

    await bot.handle_unknown_text(update, SimpleNamespace())

    logger.debug.assert_called_once()


def test_main_dns_text_handler_routes_dns_add_handler(monkeypatch):
    class FakeJobQueue:
        def get_jobs_by_name(self, _name):
            return []

        def run_daily(self, *args, **kwargs):
            return None

        def run_repeating(self, *args, **kwargs):
            return None

    class FakeApp:
        def __init__(self):
            self.job_queue = FakeJobQueue()
            self.bot_data = {}
            self.handlers = []
            self.error_handlers = []

        def add_handler(self, handler):
            self.handlers.append(handler)

        def add_error_handler(self, handler):
            self.error_handlers.append(handler)

        def run_polling(self, **kwargs):
            return None

    class FakeBuilder:
        def __init__(self, app):
            self.app = app

        def token(self, _value):
            return self

        def post_init(self, _fn):
            return self

        def post_shutdown(self, _fn):
            return self

        def build(self):
            return self.app

    captured = {}

    def fake_message_handler(_filters, callback):
        captured["dns_cb"] = callback
        return ("msg", callback)

    fake_app = FakeApp()
    monkeypatch.setattr(bot, "TOKEN", "123:TEST_TOKEN", raising=False)
    monkeypatch.setattr(bot, "configure_root_logging", MagicMock())
    monkeypatch.setattr(bot, "install_global_exception_hooks", MagicMock())
    monkeypatch.setattr(bot, "rotate_log", MagicMock())
    monkeypatch.setattr(bot.Application, "builder", lambda: FakeBuilder(fake_app))
    monkeypatch.setattr(bot, "CallbackQueryHandler", lambda *a, **k: ("cb", a, k))
    monkeypatch.setattr(bot, "CommandHandler", lambda *a, **k: ("cmd", a, k))
    monkeypatch.setattr(bot, "MessageHandler", fake_message_handler)
    monkeypatch.setattr(bot.cfg, "MIKROTIK_USE_SSL", False, raising=False)
    monkeypatch.setattr(bot.cfg, "MIKROTIK_TLS_VERIFY", True, raising=False)
    monkeypatch.setattr(bot.cfg, "DAILY_REPORT_HOUR", 7, raising=False)
    monkeypatch.setattr(bot.cfg, "AUTO_BACKUP_DAY", "sunday", raising=False)
    monkeypatch.setattr(bot.cfg, "RATE_LIMIT_PER_MINUTE", 20, raising=False)
    monkeypatch.setattr(bot.cfg, "REBOOT_COOLDOWN", 300, raising=False)
    monkeypatch.setattr(bot.cfg, "ADMIN_IDS", [111], raising=False)

    bot.main()

    assert "dns_cb" in captured
