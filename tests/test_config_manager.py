# ============================================
# TEST_CONFIG_MANAGER - Tests for services/config_manager.py
# ============================================

import json
import time
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestConfigManager:
    """Test runtime config manager."""

    def test_get_config_default(self, tmp_path, monkeypatch):
        """Get config harus return default dari core.config jika tidak di-override."""
        from services import config_manager
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', tmp_path / 'runtime_config.json')
        
        value, is_overridden = config_manager.get_config('CPU_THRESHOLD')
        assert is_overridden is False
        assert isinstance(value, int)

    def test_set_config_valid(self, tmp_path, monkeypatch):
        """Set config dengan nilai valid harus berhasil."""
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)
        
        with patch('core.database.audit_log', MagicMock()), patch('core.runtime_reset_signal.emit_runtime_reset_signal', MagicMock()) as signal_mock:
            success, msg = config_manager.set_config('CPU_THRESHOLD', '90', 12345, 'testuser')
        
        assert success is True
        assert '90' in msg
        signal_mock.assert_called_once()
        
        # Verify persisted
        with open(config_file) as f:
            data = json.load(f)
        assert data['CPU_THRESHOLD'] == 90

    def test_set_config_invalid_key(self, tmp_path, monkeypatch):
        """Set config dengan key yang tidak ada harus gagal."""
        from services import config_manager
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', tmp_path / 'runtime_config.json')
        
        success, msg = config_manager.set_config('NONEXISTENT_KEY', '100')
        assert success is False
        assert 'tidak ditemukan' in msg

    def test_set_config_out_of_range(self, tmp_path, monkeypatch):
        """Set config dengan nilai di luar range harus gagal."""
        from services import config_manager
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', tmp_path / 'runtime_config.json')
        
        success, msg = config_manager.set_config('CPU_THRESHOLD', '200')  # Max is 100
        assert success is False
        assert 'antara' in msg

    def test_set_config_invalid_type(self, tmp_path, monkeypatch):
        """Set config dengan tipe data salah harus gagal."""
        from services import config_manager
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', tmp_path / 'runtime_config.json')
        
        success, msg = config_manager.set_config('CPU_THRESHOLD', 'abc')
        assert success is False

    def test_reset_config(self, tmp_path, monkeypatch):
        """Reset config harus menghapus override."""
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)
        
        # Set first
        with open(config_file, 'w') as f:
            json.dump({'CPU_THRESHOLD': 95}, f)
        
        with patch('core.database.audit_log', MagicMock()), patch('core.runtime_reset_signal.emit_runtime_reset_signal', MagicMock()) as signal_mock:
            success, msg = config_manager.reset_config('CPU_THRESHOLD', 12345, 'testuser')
        
        assert success is True
        signal_mock.assert_called_once()
        
        # Verify removed from file
        with open(config_file) as f:
            data = json.load(f)
        assert 'CPU_THRESHOLD' not in data

    def test_reset_config_not_overridden(self, tmp_path, monkeypatch):
        """Reset config yang tidak di-override harus gagal."""
        from services import config_manager
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', tmp_path / 'runtime_config.json')
        
        success, msg = config_manager.reset_config('CPU_THRESHOLD')
        assert success is False

    def test_get_all_configs(self, tmp_path, monkeypatch):
        """get_all_configs harus return dict dengan categories."""
        from services import config_manager
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', tmp_path / 'runtime_config.json')
        
        result = config_manager.get_all_configs()
        
        assert isinstance(result, dict)
        assert len(result) > 0
        
        # Check structure
        for category, items in result.items():
            assert isinstance(items, list)
            for item in items:
                assert 'key' in item
                assert 'label' in item
                assert 'value' in item
                assert 'is_overridden' in item

    def test_top_bw_keys_visible_and_settable(self, tmp_path, monkeypatch):
        """Top BW alert keys harus muncul di /config dan bisa di-set."""
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)

        all_configs = config_manager.get_all_configs()
        category = next(name for name in all_configs if 'Top BW Alert' in name)
        keys = [item['key'] for item in all_configs[category]]
        assert 'TOP_BW_ALERT_WARN_MBPS' in keys
        assert 'TOP_BW_ALERT_CRIT_MBPS' in keys
        assert 'TOP_BW_ALERT_INTERVAL' in keys
        assert 'TOP_BW_ALERT_IGNORE_QUEUES' in keys

        with patch('core.database.audit_log', MagicMock()):
            config_manager.set_config('TOP_BW_ALERT_CRIT_MBPS', '120', 1, 'tester')
            success, msg = config_manager.set_config('TOP_BW_ALERT_WARN_MBPS', '80', 1, 'tester')
        assert success is True
        assert '80' in msg

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['TOP_BW_ALERT_WARN_MBPS'] == 80

        with patch('core.database.audit_log', MagicMock()):
            success, _ = config_manager.set_config('TOP_BW_ALERT_IGNORE_QUEUES', 'TOTAL-BANDWIDTH,GLOBAL-QUEUE', 1, 'tester')
        assert success is True

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['TOP_BW_ALERT_IGNORE_QUEUES'] == 'TOTAL-BANDWIDTH,GLOBAL-QUEUE'

    def test_advanced_netwatch_keys_visible(self, tmp_path, monkeypatch):
        """Key tuning netwatch/retry harus muncul di /config."""
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)

        all_configs = config_manager.get_all_configs()
        flattened = {
            item['key']
            for items in all_configs.values()
            for item in items
        }

        assert 'NETWATCH_INTERVAL' in flattened
        assert 'NETWATCH_IGNORE_HOSTS' in flattened
        assert 'NETWATCH_FAIL_THRESHOLD_OVERRIDES' in flattened
        assert 'PING_COUNT' in flattened
        assert 'NETWATCH_PING_CONCURRENCY' in flattened
        assert 'API_ACCOUNT_DEDUP_WINDOW_SEC' in flattened
        assert 'CRITICAL_RECOVERY_CONFIRM_COUNT' in flattened
        assert 'CRITICAL_RECOVERY_MIN_UP_SECONDS' in flattened
        assert 'MIKROTIK_RESET_ALL_COOLDOWN_SEC' in flattened

    def test_ping_count_can_be_set_via_config(self, tmp_path, monkeypatch):
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)

        with patch('core.database.audit_log', MagicMock()):
            success, msg = config_manager.set_config('PING_COUNT', '6', 1, 'tester')

        assert success is True
        assert '6' in msg

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['PING_COUNT'] == 6

    def test_netwatch_ignore_hosts_can_be_set_via_config(self, tmp_path, monkeypatch):
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)

        with patch('core.database.audit_log', MagicMock()):
            success, _ = config_manager.set_config(
                'NETWATCH_IGNORE_HOSTS',
                '192.168.3.145,192.168.3.146,192.168.3.147',
                1,
                'tester',
            )

        assert success is True

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['NETWATCH_IGNORE_HOSTS'] == '192.168.3.145,192.168.3.146,192.168.3.147'

    def test_netwatch_fail_threshold_overrides_can_be_set_via_config(self, tmp_path, monkeypatch):
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)

        with patch('core.database.audit_log', MagicMock()):
            success, _ = config_manager.set_config(
                'NETWATCH_FAIL_THRESHOLD_OVERRIDES',
                '192.168.3.145:8,192.168.3.146:8',
                1,
                'tester',
            )

        assert success is True

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['NETWATCH_FAIL_THRESHOLD_OVERRIDES'] == '192.168.3.145:8,192.168.3.146:8'

    def test_top_bw_reject_warn_above_crit(self, tmp_path, monkeypatch):
        """WARN tidak boleh lebih besar dari CRIT."""
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)
        config_file.write_text(json.dumps({'TOP_BW_ALERT_CRIT_MBPS': 70}), encoding='utf-8')

        with patch('core.database.audit_log', MagicMock()):
            success, msg = config_manager.set_config('TOP_BW_ALERT_WARN_MBPS', '80', 1, 'tester')
        assert success is False
        assert 'WARN' in msg and 'CRIT' in msg

    def test_set_config_bool_valid(self, tmp_path, monkeypatch):
        """Boolean key bisa di-set via true/false."""
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)

        with patch('core.database.audit_log', MagicMock()):
            success, _ = config_manager.set_config('MONITOR_VPN_ENABLED', 'false', 12345, 'testuser')
        assert success is True

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['MONITOR_VPN_ENABLED'] is False

    def test_set_config_bool_invalid(self, tmp_path, monkeypatch):
        """Boolean key dengan nilai non-bool harus gagal."""
        from services import config_manager
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', tmp_path / 'runtime_config.json')

        success, msg = config_manager.set_config('MONITOR_VPN_ENABLED', 'abc')
        assert success is False
        assert 'boolean' in msg.lower()

    def test_config_lock_reclaims_stale_lock(self, tmp_path, monkeypatch):
        from services import config_manager

        lock_file = tmp_path / "runtime_config.lock"
        monkeypatch.setattr(config_manager, "_CONFIG_LOCK_FILE", lock_file, raising=False)
        monkeypatch.setattr(config_manager, "_CONFIG_LOCK_STALE_SEC", 1, raising=False)

        lock_file.write_text(json.dumps({"pid": 999, "ts": time.time() - 60}), encoding="utf-8")

        with config_manager._config_lock(timeout=0.2, poll_interval=0.01):
            assert lock_file.exists()

    def test_config_lock_times_out_on_active_lock(self, tmp_path, monkeypatch):
        from services import config_manager

        lock_file = tmp_path / "runtime_config.lock"
        monkeypatch.setattr(config_manager, "_CONFIG_LOCK_FILE", lock_file, raising=False)
        monkeypatch.setattr(config_manager, "_CONFIG_LOCK_STALE_SEC", 3600, raising=False)
        lock_file.write_text(json.dumps({"pid": 999, "ts": time.time()}), encoding="utf-8")

        with pytest.raises(TimeoutError):
            with config_manager._config_lock(timeout=0.01, poll_interval=0.001):
                pass

    def test_parse_bool_value_numeric_and_invalid(self):
        from services import config_manager

        assert config_manager._parse_bool_value(1) is True
        assert config_manager._parse_bool_value(0.0) is False
        with pytest.raises(ValueError):
            config_manager._parse_bool_value(object())

    def test_sanitize_overrides_filters_invalid_values(self):
        from services import config_manager

        result = config_manager._sanitize_overrides({
            "CPU_THRESHOLD": "70",
            "MONITOR_VPN_ENABLED": "yes",
            "INVALID_KEY": 1,
            "RAM_THRESHOLD": "999",
            "ALERT_REQUIRE_START": "not-bool",
            "PING_COUNT": "nope",
        })

        assert result["CPU_THRESHOLD"] == 70
        assert result["MONITOR_VPN_ENABLED"] is True
        assert "INVALID_KEY" not in result
        assert "RAM_THRESHOLD" not in result
        assert "ALERT_REQUIRE_START" not in result
        assert "PING_COUNT" not in result

    def test_sanitize_overrides_non_dict_returns_empty(self):
        from services import config_manager

        assert config_manager._sanitize_overrides([]) == {}

    def test_load_overrides_invalid_json_returns_empty(self, tmp_path, monkeypatch):
        from services import config_manager
        config_file = tmp_path / "runtime_config.json"
        config_file.write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(config_manager, "_CONFIG_FILE", config_file, raising=False)

        assert config_manager._load_overrides() == {}

    def test_apply_overrides_on_startup_parses_ignore_queue_list(self, monkeypatch):
        from services import config_manager

        monkeypatch.setattr(
            config_manager,
            "_load_overrides",
            lambda: {"TOP_BW_ALERT_IGNORE_QUEUES": "A,B", "CPU_THRESHOLD": 55},
            raising=False,
        )
        monkeypatch.setattr(config_manager._cfg_module, "TOP_BW_ALERT_IGNORE_QUEUES", [], raising=False)
        monkeypatch.setattr(config_manager._cfg_module, "CPU_THRESHOLD", 80, raising=False)

        config_manager._apply_overrides_on_startup()

        assert config_manager._cfg_module.TOP_BW_ALERT_IGNORE_QUEUES == ["A", "B"]
        assert config_manager._cfg_module.CPU_THRESHOLD == 55

    def test_save_overrides_cleanup_on_failure(self, tmp_path, monkeypatch):
        from services import config_manager

        config_file = tmp_path / "runtime_config.json"
        monkeypatch.setattr(config_manager, "_CONFIG_FILE", config_file, raising=False)
        monkeypatch.setattr(config_manager, "_config_lock", lambda: __import__("contextlib").nullcontext(), raising=False)

        created_tmp = {}
        import tempfile

        original_mkstemp = tempfile.mkstemp
        def fake_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            created_tmp["path"] = path
            return fd, path

        monkeypatch.setattr(config_manager.tempfile, "mkstemp", fake_mkstemp, raising=False)
        monkeypatch.setattr(config_manager.os, "replace", MagicMock(side_effect=RuntimeError("replace-fail")), raising=False)

        config_manager._save_overrides({"CPU_THRESHOLD": 60})

        assert created_tmp["path"]
        assert not Path(created_tmp["path"]).exists()

    def test_config_lock_cleanup_tolerates_os_errors(self, tmp_path, monkeypatch):
        from services import config_manager
        import os

        lock_file = tmp_path / "runtime_config.lock"
        monkeypatch.setattr(config_manager, "_CONFIG_LOCK_FILE", lock_file, raising=False)

        original_open = config_manager.os.open
        original_write = config_manager.os.write
        original_close = os.close
        original_unlink = os.unlink
        state = {"fd": None}

        def fake_open(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            state["fd"] = fd
            return fd

        monkeypatch.setattr(config_manager.os, "open", fake_open, raising=False)
        monkeypatch.setattr(config_manager.os, "write", original_write, raising=False)
        monkeypatch.setattr(config_manager.os, "close", MagicMock(side_effect=OSError("close-fail")), raising=False)
        monkeypatch.setattr(config_manager.os, "unlink", MagicMock(side_effect=OSError("unlink-fail")), raising=False)

        with config_manager._config_lock(timeout=0.2, poll_interval=0.01):
            assert lock_file.exists()

        if state["fd"] is not None:
            try:
                original_close(state["fd"])
            except OSError:
                pass
        if lock_file.exists():
            original_unlink(lock_file)

    def test_set_config_ignores_runtime_reset_emit_failure(self, tmp_path, monkeypatch):
        from services import config_manager

        config_file = tmp_path / "runtime_config.json"
        monkeypatch.setattr(config_manager, "_CONFIG_FILE", config_file, raising=False)

        with patch('core.database.audit_log', MagicMock()), patch(
            'core.runtime_reset_signal.emit_runtime_reset_signal',
            MagicMock(side_effect=RuntimeError("signal-fail"))
        ):
            success, _ = config_manager.set_config('CPU_THRESHOLD', '60', 1, 'tester')

        assert success is True

    def test_set_config_ignores_audit_log_failure(self, tmp_path, monkeypatch):
        from services import config_manager

        config_file = tmp_path / "runtime_config.json"
        monkeypatch.setattr(config_manager, "_CONFIG_FILE", config_file, raising=False)

        with patch('core.database.audit_log', MagicMock(side_effect=RuntimeError("audit-fail"))), patch(
            'core.runtime_reset_signal.emit_runtime_reset_signal',
            MagicMock()
        ):
            success, _ = config_manager.set_config('CPU_THRESHOLD', '61', 1, 'tester')

        assert success is True

    def test_set_config_crit_below_warn_rejected(self, tmp_path, monkeypatch):
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)
        config_file.write_text(json.dumps({'TOP_BW_ALERT_WARN_MBPS': 80}), encoding='utf-8')

        with patch('core.database.audit_log', MagicMock()):
            success, msg = config_manager.set_config('TOP_BW_ALERT_CRIT_MBPS', '70', 1, 'tester')
        assert success is False
        assert 'CRIT' in msg and 'WARN' in msg

    def test_reset_config_invalid_key(self):
        from services import config_manager

        success, msg = config_manager.reset_config("MISSING_KEY")

        assert success is False
        assert "tidak ditemukan" in msg

    def test_reset_config_ignores_runtime_reset_and_audit_failures(self, tmp_path, monkeypatch):
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)
        config_file.write_text(json.dumps({'CPU_THRESHOLD': 95}), encoding='utf-8')

        with patch('core.database.audit_log', MagicMock(side_effect=RuntimeError("audit-fail"))), patch(
            'core.runtime_reset_signal.emit_runtime_reset_signal',
            MagicMock(side_effect=RuntimeError("signal-fail"))
        ):
            success, msg = config_manager.reset_config('CPU_THRESHOLD', 1, 'tester')

        assert success is True
        assert 'di-reset' in msg

    def test_get_configurable_keys_returns_known_key(self):
        from services import config_manager

        keys = config_manager.get_configurable_keys()

        assert "CPU_THRESHOLD" in keys

