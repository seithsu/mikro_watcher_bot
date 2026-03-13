# ============================================
# TEST_LOGGER - Tests for core/logger.py
# catat, baca_log, rotate_log, format_log_pretty
# ============================================

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def log_env(tmp_path, monkeypatch):
    """Setup temporary log environment."""
    import core.logger as logger_mod
    log_file = str(tmp_path / "aktivitas.log")
    monkeypatch.setattr(logger_mod, 'LOG_FILE', log_file)
    return log_file, logger_mod


class TestCatat:
    """Test log writing function."""

    def test_catat_creates_file(self, log_env):
        log_file, mod = log_env
        mod.catat(12345, "admin", "/status", "berhasil")
        assert Path(log_file).exists()

    def test_catat_writes_json(self, log_env):
        log_file, mod = log_env
        mod.catat(12345, "admin", "/reboot", "berhasil")

        with open(log_file, 'r', encoding='utf-8') as f:
            line = f.readline().strip()
        data = json.loads(line)

        assert data['user_id'] == 12345
        assert data['username'] == "admin"
        assert data['perintah'] == "/reboot"
        assert data['status'] == "berhasil"
        assert 'waktu' in data

    def test_catat_multiple_entries(self, log_env):
        log_file, mod = log_env
        mod.catat(1, "a", "/start", "ok")
        mod.catat(2, "b", "/help", "ok")
        mod.catat(3, "c", "/status", "ok")

        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        assert len(lines) == 3


class TestBacaLog:
    """Test log reading function."""

    def test_baca_log_empty(self, log_env):
        log_file, mod = log_env
        result = mod.baca_log()
        assert result == []

    def test_baca_log_returns_last_n(self, log_env):
        log_file, mod = log_env
        for i in range(20):
            mod.catat(i, f"user{i}", f"/cmd{i}", "ok")

        result = mod.baca_log(5)
        assert len(result) == 5
        assert result[-1]['username'] == "user19"

    def test_baca_log_default_10(self, log_env):
        log_file, mod = log_env
        for i in range(15):
            mod.catat(i, f"user{i}", f"/cmd{i}", "ok")

        result = mod.baca_log()
        assert len(result) == 10

    def test_baca_log_skips_corrupt(self, log_env):
        log_file, mod = log_env
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write('{"user_id": 1, "username": "a", "perintah": "/x", "status": "ok", "waktu": "2026-01-01"}\n')
            f.write("corrupt line\n")
            f.write('{"user_id": 2, "username": "b", "perintah": "/y", "status": "ok", "waktu": "2026-01-02"}\n')

        result = mod.baca_log(10)
        assert len(result) == 2


class TestFormatLogPretty:
    """Test HTML log formatting."""

    def test_empty_logs(self, log_env):
        _, mod = log_env
        result = mod.format_log_pretty([])
        assert "Belum ada aktivitas" in result

    def test_format_success(self, log_env):
        _, mod = log_env
        logs = [{'waktu': '2026-01-01 12:00:00', 'user_id': 1, 'username': 'admin', 'perintah': '/status', 'status': 'berhasil'}]
        result = mod.format_log_pretty(logs)
        assert "✅" in result
        assert "admin" in result
        assert "/status" in result

    def test_format_error(self, log_env):
        _, mod = log_env
        logs = [{'waktu': '2026-01-01', 'user_id': 1, 'username': 'admin', 'perintah': '/reboot', 'status': 'gagal'}]
        result = mod.format_log_pretty(logs)
        assert "❌" in result


class TestRotateLog:
    """Test log rotation."""

    def test_rotation_under_limit(self, log_env):
        log_file, mod = log_env
        # Write small file
        with open(log_file, 'w') as f:
            f.write("small\n")
        mod.rotate_log()
        assert Path(log_file).exists()
        assert not Path(f"{log_file}.1").exists()

    def test_rotation_over_limit(self, log_env, monkeypatch):
        log_file, mod = log_env
        monkeypatch.setattr(mod, 'LOG_MAX_SIZE', 10)  # Tiny limit

        with open(log_file, 'w') as f:
            f.write("x" * 100)  # Over limit

        mod.rotate_log()
        assert Path(f"{log_file}.1").exists()

    def test_rotation_no_file(self, log_env):
        log_file, mod = log_env
        mod.rotate_log()  # Should not raise when file doesn't exist


class TestHitungTotalLog:
    """Test total log counter."""

    def test_count_empty(self, log_env):
        _, mod = log_env
        assert mod.hitung_total_log() == 0

    def test_count_with_entries(self, log_env):
        log_file, mod = log_env
        mod.catat(1, "a", "/x", "ok")
        mod.catat(2, "b", "/y", "ok")
        assert mod.hitung_total_log() == 2

    def test_count_with_backup(self, log_env):
        log_file, mod = log_env
        mod.catat(1, "a", "/x", "ok")

        # Create backup file
        with open(f"{log_file}.1", 'w', encoding='utf-8') as f:
            f.write("line1\nline2\nline3\n")

        assert mod.hitung_total_log() == 4  # 1 active + 3 backup
