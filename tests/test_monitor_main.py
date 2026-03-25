from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import monitor as mon
import monitor.netwatch as netwatch
import monitor.tasks as tasks


@pytest.mark.asyncio
async def test_main_async_runs_all_tasks_once(monkeypatch):
    called = {"count": 0}
    exception_handler = {}

    async def _tick():
        called["count"] += 1

    monkeypatch.setattr(tasks, "task_monitor_system", _tick)
    monkeypatch.setattr(tasks, "task_monitor_resources", _tick)
    monkeypatch.setattr(tasks, "task_monitor_traffic", _tick)
    monkeypatch.setattr(tasks, "task_monitor_top_bandwidth", _tick)
    monkeypatch.setattr(tasks, "task_monitor_logs", _tick)
    monkeypatch.setattr(tasks, "task_monitor_dhcp_arp", _tick)
    monkeypatch.setattr(tasks, "task_monitor_alert_maintenance", _tick)
    monkeypatch.setattr(netwatch, "task_monitor_netwatch", _tick)
    monkeypatch.setattr(mon, "_TASK_STARTUP_DELAYS", {k: 0 for k in mon._TASK_STARTUP_DELAYS})

    fake_signal_loop = SimpleNamespace(
        add_signal_handler=lambda *a, **k: None,
        set_default_executor=lambda *a, **k: None,
        set_exception_handler=lambda handler: exception_handler.setdefault("handler", handler),
    )
    monkeypatch.setattr(mon.asyncio, "get_running_loop", lambda: fake_signal_loop)
    monkeypatch.setattr(mon.asyncio, "get_event_loop", lambda: fake_signal_loop)

    await mon.main_async()
    assert called["count"] == 8
    exception = RuntimeError("loop-fail")
    exception_handler["handler"](None, {"message": "boom", "exception": exception})


@pytest.mark.asyncio
async def test_run_task_with_startup_delay_waits_before_start(monkeypatch):
    calls = []

    async def _fake_sleep(delay):
        calls.append(("sleep", delay))

    async def _tick():
        calls.append(("task", None))

    monkeypatch.setattr(mon.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(mon, "_TASK_STARTUP_DELAYS", {"logs": 4})

    await mon._run_task_with_startup_delay("logs", _tick)

    assert calls == [("sleep", 4), ("task", None)]


@pytest.mark.asyncio
async def test_run_task_with_startup_delay_zero_runs_immediately(monkeypatch):
    calls = []

    async def _tick():
        calls.append("task")

    monkeypatch.setattr(mon, "_TASK_STARTUP_DELAYS", {"system": 0})

    await mon._run_task_with_startup_delay("system", _tick)

    assert calls == ["task"]


@pytest.mark.asyncio
async def test_main_async_windows_signal_fallback_and_cancel(monkeypatch):
    called = {"count": 0}
    fallback_handlers = []

    async def _tick():
        called["count"] += 1

    monkeypatch.setattr(tasks, "task_monitor_system", _tick)
    monkeypatch.setattr(tasks, "task_monitor_resources", _tick)
    monkeypatch.setattr(tasks, "task_monitor_traffic", _tick)
    monkeypatch.setattr(tasks, "task_monitor_top_bandwidth", _tick)
    monkeypatch.setattr(tasks, "task_monitor_logs", _tick)
    monkeypatch.setattr(tasks, "task_monitor_dhcp_arp", _tick)
    monkeypatch.setattr(tasks, "task_monitor_alert_maintenance", _tick)
    monkeypatch.setattr(netwatch, "task_monitor_netwatch", _tick)
    monkeypatch.setattr(mon, "_TASK_STARTUP_DELAYS", {k: 0 for k in mon._TASK_STARTUP_DELAYS})

    fake_signal_loop = SimpleNamespace(add_signal_handler=lambda *a, **k: (_ for _ in ()).throw(NotImplementedError()))
    monkeypatch.setattr(mon.asyncio, "get_running_loop", lambda: SimpleNamespace(
        set_default_executor=lambda *a, **k: None,
        set_exception_handler=lambda *a, **k: None,
    ))
    monkeypatch.setattr(mon.asyncio, "get_event_loop", lambda: fake_signal_loop)

    original_gather = mon.asyncio.gather

    async def _fake_gather(*args, **kwargs):
        result = await original_gather(*args, **kwargs)
        for handler in fallback_handlers:
            handler(None, None)
        return result

    monkeypatch.setattr(mon.asyncio, "gather", _fake_gather)
    monkeypatch.setattr(mon.signal, "signal", lambda _sig, handler: fallback_handlers.append(handler))

    await mon.main_async()

    assert len(fallback_handlers) == 2
    assert called["count"] == 8


@pytest.mark.asyncio
async def test_main_async_handles_cancelled_gather(monkeypatch):
    async def _tick():
        return None

    monkeypatch.setattr(tasks, "task_monitor_system", _tick)
    monkeypatch.setattr(tasks, "task_monitor_resources", _tick)
    monkeypatch.setattr(tasks, "task_monitor_traffic", _tick)
    monkeypatch.setattr(tasks, "task_monitor_top_bandwidth", _tick)
    monkeypatch.setattr(tasks, "task_monitor_logs", _tick)
    monkeypatch.setattr(tasks, "task_monitor_dhcp_arp", _tick)
    monkeypatch.setattr(tasks, "task_monitor_alert_maintenance", _tick)
    monkeypatch.setattr(netwatch, "task_monitor_netwatch", _tick)
    monkeypatch.setattr(mon, "_TASK_STARTUP_DELAYS", {k: 0 for k in mon._TASK_STARTUP_DELAYS})

    fake_signal_loop = SimpleNamespace(add_signal_handler=lambda *a, **k: None)
    monkeypatch.setattr(mon.asyncio, "get_running_loop", lambda: SimpleNamespace(
        set_default_executor=lambda *a, **k: None,
        set_exception_handler=lambda *a, **k: None,
    ))
    monkeypatch.setattr(mon.asyncio, "get_event_loop", lambda: fake_signal_loop)

    async def _raise_cancelled(*_args, **_kwargs):
        raise mon.asyncio.CancelledError()

    monkeypatch.setattr(mon.asyncio, "gather", _raise_cancelled)

    await mon.main_async()


def test_main_initializes_and_runs_with_alert_gate(monkeypatch):
    cfg_reload = [
        ("ALERT_REQUIRE_START", True),
        ("MIKROTIK_USE_SSL", False),
        ("MIKROTIK_TLS_VERIFY", True),
        ("MONITOR_INTERVAL", 300),
        ("RESOURCE_MONITOR_INTERVAL", 60),
        ("MONITOR_LOG_INTERVAL", 30),
        ("TOP_BW_ALERT_INTERVAL", 15),
        ("ADMIN_IDS", [123456]),
    ]
    for key, val in cfg_reload:
        monkeypatch.setattr(mon.cfg, key, val, raising=False)

    configure = MagicMock()
    hooks = MagicMock()
    captured = {"called": 0}

    def _fake_run(coro):
        captured["called"] += 1
        coro.close()
        return None
    gate = MagicMock()

    monkeypatch.setattr(mon, "configure_root_logging", configure)
    monkeypatch.setattr(mon, "install_global_exception_hooks", hooks)
    monkeypatch.setattr(mon.asyncio, "run", _fake_run)
    monkeypatch.setattr("monitor.alerts.get_alert_delivery_state", MagicMock(return_value={"enabled": False, "exists": False}))
    monkeypatch.setattr("monitor.alerts.set_alert_delivery_enabled", gate)

    mon.main()

    configure.assert_called_once()
    hooks.assert_called_once_with(process_name="monitor")
    gate.assert_called_once_with(False, actor="monitor_boot", reason="require_start")
    assert captured["called"] == 1


def test_main_preserves_existing_enabled_alert_gate(monkeypatch):
    monkeypatch.setattr(mon.cfg, "ALERT_REQUIRE_START", True, raising=False)
    monkeypatch.setattr(mon.cfg, "MIKROTIK_USE_SSL", False, raising=False)
    monkeypatch.setattr(mon.cfg, "MIKROTIK_TLS_VERIFY", True, raising=False)
    monkeypatch.setattr(mon.cfg, "MONITOR_INTERVAL", 300, raising=False)
    monkeypatch.setattr(mon.cfg, "RESOURCE_MONITOR_INTERVAL", 60, raising=False)
    monkeypatch.setattr(mon.cfg, "MONITOR_LOG_INTERVAL", 30, raising=False)
    monkeypatch.setattr(mon.cfg, "TOP_BW_ALERT_INTERVAL", 15, raising=False)
    monkeypatch.setattr(mon.cfg, "ADMIN_IDS", [123456], raising=False)
    monkeypatch.setattr(mon, "configure_root_logging", MagicMock())
    monkeypatch.setattr(mon, "install_global_exception_hooks", MagicMock())
    monkeypatch.setattr(mon.asyncio, "run", lambda coro: coro.close())

    monkeypatch.setattr(
        "monitor.alerts.get_alert_delivery_state",
        MagicMock(return_value={"enabled": True, "exists": True}),
    )
    gate = MagicMock()
    monkeypatch.setattr("monitor.alerts.set_alert_delivery_enabled", gate)

    mon.main()

    gate.assert_not_called()


def test_main_handles_keyboard_interrupt(monkeypatch):
    monkeypatch.setattr(mon.cfg, "ALERT_REQUIRE_START", False, raising=False)
    monkeypatch.setattr(mon.cfg, "MIKROTIK_USE_SSL", True, raising=False)
    monkeypatch.setattr(mon.cfg, "MIKROTIK_TLS_VERIFY", False, raising=False)
    monkeypatch.setattr(mon, "configure_root_logging", MagicMock())
    monkeypatch.setattr(mon, "install_global_exception_hooks", MagicMock())
    def _fake_run_interrupt(coro):
        coro.close()
        raise KeyboardInterrupt()

    monkeypatch.setattr(mon.asyncio, "run", _fake_run_interrupt)

    mon.main()


def test_main_handles_alert_gate_setup_error(monkeypatch):
    monkeypatch.setattr(mon.cfg, "ALERT_REQUIRE_START", True, raising=False)
    monkeypatch.setattr(mon.cfg, "MIKROTIK_USE_SSL", True, raising=False)
    monkeypatch.setattr(mon.cfg, "MIKROTIK_TLS_VERIFY", True, raising=False)
    monkeypatch.setattr(mon, "configure_root_logging", MagicMock())
    monkeypatch.setattr(mon, "install_global_exception_hooks", MagicMock())
    monkeypatch.setattr(mon.asyncio, "run", lambda coro: coro.close())
    monkeypatch.setattr("monitor.alerts.set_alert_delivery_enabled", MagicMock(side_effect=RuntimeError("gate-fail")))

    mon.main()
