import runpy
from unittest.mock import MagicMock


def test_run_monitor_executes_monitor_main(monkeypatch):
    mock_main = MagicMock()
    monkeypatch.setattr("monitor.main", mock_main)

    runpy.run_path("run_monitor.py", run_name="__main__")
    mock_main.assert_called_once()
