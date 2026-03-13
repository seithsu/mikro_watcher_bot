import os
from unittest.mock import MagicMock, patch

import pytest


def test_reboot_router_resets_pool():
    from mikrotik import system as ms

    api = MagicMock()
    cmd = MagicMock(return_value=[])
    api.path.side_effect = lambda *args: cmd if args == ("system",) else MagicMock()

    with patch.object(ms.pool, "get_api", return_value=api), patch.object(ms.pool, "reset") as mock_reset:
        assert ms.reboot_router() is True
        mock_reset.assert_called_once()


def test_get_system_routerboard_fallback_to_resource_and_identity():
    from mikrotik import system as ms

    api = MagicMock()

    def _path(*args):
        if args == ("system", "routerboard"):
            raise Exception("unsupported")
        if args == ("system", "resource"):
            return iter([{"board-name": "hEX"}])
        if args == ("system", "identity"):
            return iter([{"name": "RSIA"}])
        return iter([])

    api.path.side_effect = _path

    with patch.object(ms.pool, "get_api", return_value=api):
        result = ms.get_system_routerboard.__wrapped__.__wrapped__()

    assert result["board"] == "hEX"
    assert result["model"] == "RSIA"


def test_export_router_backup_rsc_success(tmp_path, monkeypatch):
    from mikrotik import system as ms

    monkeypatch.setattr(ms.cfg, "DATA_DIR", tmp_path, raising=False)
    with patch("mikrotik.system.time.time", return_value=1000), patch("mikrotik.system.time.sleep", return_value=None):
        target_file = "router_backup_1000.rsc"

        api = MagicMock()
        file_path = MagicMock()
        file_path.__iter__.return_value = iter([{"name": target_file, ".id": "*1", "contents": "/ip address print"}])
        api.path.side_effect = lambda *args: (
            MagicMock(return_value=[]) if args == ("system", "backup")
            else file_path if args == ("file",)
            else MagicMock()
        )

        with patch.object(ms.pool, "get_api", return_value=api), patch("mikrotik.system._run_export_script") as mock_export:
            out = ms.export_router_backup.__wrapped__("export")

        assert out.endswith(target_file)
        assert os.path.exists(out)
        with open(out, "r", encoding="utf-8") as f:
            assert "/ip address print" in f.read()
        file_path.remove.assert_called_once_with("*1")
        mock_export.assert_called_once()


def test_export_router_backup_backup_binary_returns_none(tmp_path, monkeypatch):
    from mikrotik import system as ms

    monkeypatch.setattr(ms.cfg, "DATA_DIR", tmp_path, raising=False)
    with patch("mikrotik.system.time.time", return_value=1001), patch("mikrotik.system.time.sleep", return_value=None):
        target_file = "router_backup_1001.backup"
        api = MagicMock()
        file_path = MagicMock()
        file_path.__iter__.return_value = iter([{"name": target_file, ".id": "*1", "contents": ""}])
        api.path.side_effect = lambda *args: (
            MagicMock(return_value=[]) if args == ("system", "backup")
            else file_path if args == ("file",)
            else MagicMock()
        )

        with patch.object(ms.pool, "get_api", return_value=api):
            out = ms.export_router_backup.__wrapped__("backup")

        assert out is None


def test_run_export_script_add_run_and_cleanup():
    from mikrotik import system as ms

    scripts = MagicMock()
    scripts.return_value = []
    scripts.__iter__.side_effect = [
        iter([]),  # existing check
        iter([{"name": "_temp_export_bot", ".id": "*1"}]),  # re-fetch for run
        iter([{"name": "_temp_export_bot", ".id": "*1"}]),  # cleanup fetch
    ]

    api = MagicMock()
    api.path.side_effect = lambda *args: scripts if args == ("system", "script") else MagicMock()

    ms._run_export_script(api, "my_export")

    scripts.add.assert_called_once()
    scripts.remove.assert_called_once_with("*1")


def test_export_router_backup_ftp_plain_fallback_success(tmp_path, monkeypatch):
    from mikrotik import system as ms

    monkeypatch.setattr(ms.cfg, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(ms.cfg, "MIKROTIK_IP", "192.168.3.1", raising=False)
    monkeypatch.setattr(ms.cfg, "MIKROTIK_USER", "admin", raising=False)
    monkeypatch.setattr(ms.cfg, "MIKROTIK_PASS", "admin", raising=False)
    monkeypatch.setattr(ms.cfg, "MIKROTIK_FTP_PORT", 21, raising=False)
    monkeypatch.setattr(ms.cfg, "MIKROTIK_FTP_TLS", False, raising=False)
    monkeypatch.setattr(ms.cfg, "MIKROTIK_FTP_ALLOW_INSECURE", True, raising=False)
    monkeypatch.setattr(ms.cfg, "reload_router_env", lambda min_interval=5: None, raising=False)

    class FakeFTP:
        def connect(self, host, port, timeout=10):
            return None

        def login(self, user, password):
            return None

        def retrbinary(self, cmd, callback):
            callback(b"binary-backup")

        def quit(self):
            return None

    with patch("mikrotik.system.time.time", return_value=1000), patch("mikrotik.system.time.sleep", return_value=None):
        target_file = "MikroTik_Backup_1000.backup"
        file_path = MagicMock()
        file_path.__iter__.return_value = iter([{"name": target_file, ".id": "*9"}])

        api = MagicMock()
        api.path.side_effect = lambda *args: (
            MagicMock(return_value=[]) if args == ("system", "backup")
            else file_path if args == ("file",)
            else MagicMock()
        )

        with patch.object(ms.pool, "get_api", return_value=api), patch("mikrotik.system.ftplib.FTP", return_value=FakeFTP()):
            out = ms.export_router_backup_ftp.__wrapped__("backup")

    assert out.endswith(target_file)
    assert os.path.exists(out)
    with open(out, "rb") as f:
        assert f.read() == b"binary-backup"
    file_path.remove.assert_called_once_with("*9")
