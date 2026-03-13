from types import SimpleNamespace
from unittest.mock import MagicMock

import core.runtime_guard as rg


def test_install_global_exception_hooks_calls_logger_for_sys_and_thread(monkeypatch):
    critical = MagicMock()
    monkeypatch.setattr(rg.logger, "critical", critical)

    rg.install_global_exception_hooks(process_name="unit-test")

    rg.sys.excepthook(ValueError, ValueError("boom"), None)
    rg.threading.excepthook(
        SimpleNamespace(
            exc_type=RuntimeError,
            exc_value=RuntimeError("thread-fail"),
            exc_traceback=None,
            thread=SimpleNamespace(name="worker-1"),
        )
    )

    assert critical.call_count == 2
    first_msg = critical.call_args_list[0].args[0]
    second_msg = critical.call_args_list[1].args[0]
    assert "Unhandled exception" in first_msg
    assert "Unhandled thread exception" in second_msg


def test_install_global_exception_hooks_ignores_keyboard_interrupt(monkeypatch):
    critical = MagicMock()
    monkeypatch.setattr(rg.logger, "critical", critical)

    rg.install_global_exception_hooks(process_name="unit-test")
    rg.sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    rg.threading.excepthook(
        SimpleNamespace(
            exc_type=KeyboardInterrupt,
            exc_value=KeyboardInterrupt(),
            exc_traceback=None,
            thread=SimpleNamespace(name="worker-2"),
        )
    )

    critical.assert_not_called()
