from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import monitor as mon
import monitor.netwatch as netwatch
import monitor.tasks as tasks


@pytest.mark.asyncio
async def test_main_async_runs_all_tasks_once(monkeypatch):
    called = {"count": 0}

    async def _tick():
        called["count"] += 1

    monkeypatch.setattr(tasks, "task_monitor_system", _tick)
    monkeypatch.setattr(tasks, "task_monitor_traffic", _tick)
    monkeypatch.setattr(tasks, "task_monitor_logs", _tick)
    monkeypatch.setattr(tasks, "task_monitor_dhcp_arp", _tick)
    monkeypatch.setattr(tasks, "task_monitor_alert_maintenance", _tick)
    monkeypatch.setattr(netwatch, "task_monitor_netwatch", _tick)

    fake_signal_loop = SimpleNamespace(add_signal_handler=lambda *a, **k: None)
    monkeypatch.setattr(mon.asyncio, "get_event_loop", lambda: fake_signal_loop)

    await mon.main_async()
    assert called["count"] == 6


def test_main_initializes_and_runs_with_alert_gate(monkeypatch):
    cfg_reload = [
        ("ALERT_REQUIRE_START", True),
        ("MIKROTIK_USE_SSL", False),
        ("MIKROTIK_TLS_VERIFY", True),
        ("MONITOR_INTERVAL", 300),
        ("MONITOR_LOG_INTERVAL", 30),
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
    monkeypatch.setattr("monitor.alerts.set_alert_delivery_enabled", gate)

    mon.main()

    configure.assert_called_once()
    hooks.assert_called_once_with(process_name="monitor")
    gate.assert_called_once_with(False, actor="monitor_boot", reason="require_start")
    assert captured["called"] == 1


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
