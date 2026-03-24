# ============================================
# TEST_BACKUP - Tests for core/backup.py
# ZIP archive creation
# ============================================

import os
import runpy
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    """Create test files and chdir to tmp_path."""
    monkeypatch.chdir(tmp_path)

    (tmp_path / "bot.py").write_text("print('bot')")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "config.py").write_text("TOKEN = 'test'")
    (tmp_path / "handlers").mkdir()
    (tmp_path / "handlers" / "general.py").write_text("pass")
    (tmp_path / ".env").write_text("TOKEN=abc")
    return tmp_path


class TestBackupSemua:
    """Test backup_semua function."""

    @patch('core.backup._FILES_TO_BACKUP', [
        "bot.py",
        "core/config.py",
    ])
    def test_creates_zip(self, backup_env):
        from core.backup import backup_semua
        result = backup_semua()
        assert result is not None
        assert result.endswith('.zip')
        assert os.path.exists(result)

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert len(names) == 2
            assert "bot.py" in names
            assert "core/config.py" in names

        os.remove(result)

    @patch('core.backup._FILES_TO_BACKUP', [])
    def test_empty_backup(self):
        """Backup dengan file list kosong tetap membuat ZIP."""
        from core.backup import backup_semua
        result = backup_semua()
        assert result is not None
        assert result.endswith('.zip')

        with zipfile.ZipFile(result) as zf:
            assert len(zf.namelist()) == 0

        os.remove(result)

    @patch('core.backup._FILES_TO_BACKUP', [
        "bot.py",
        "nonexistent_file.py",
    ])
    def test_missing_files_skipped(self, backup_env):
        """File yang tidak ada harus di-skip tanpa error."""
        from core.backup import backup_semua
        result = backup_semua()
        assert result is not None

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert "bot.py" in names
            assert "nonexistent_file.py" not in names

        os.remove(result)

    def test_module_main_runs_as_script(self, tmp_path, monkeypatch):
        """Menjalankan core.backup sebagai script harus masuk ke blok __main__."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "bot.py").write_text("print('bot')", encoding="utf-8")

        with patch("logging.basicConfig") as basic_config:
            runpy.run_module("core.backup", run_name="__main__")

        basic_config.assert_called_once()
        created = list(tmp_path.glob("backup_bot_*.zip"))
        assert len(created) == 1
