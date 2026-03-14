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
        
        with patch('core.database.audit_log', MagicMock()):
            success, msg = config_manager.set_config('CPU_THRESHOLD', '90', 12345, 'testuser')
        
        assert success is True
        assert '90' in msg
        
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
        
        with patch('core.database.audit_log', MagicMock()):
            success, msg = config_manager.reset_config('CPU_THRESHOLD', 12345, 'testuser')
        
        assert success is True
        
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
        assert '🚨 Top BW Alert' in all_configs
        keys = [item['key'] for item in all_configs['🚨 Top BW Alert']]
        assert 'TOP_BW_ALERT_WARN_MBPS' in keys
        assert 'TOP_BW_ALERT_CRIT_MBPS' in keys

        with patch('core.database.audit_log', MagicMock()):
            config_manager.set_config('TOP_BW_ALERT_CRIT_MBPS', '120', 1, 'tester')
            success, msg = config_manager.set_config('TOP_BW_ALERT_WARN_MBPS', '80', 1, 'tester')
        assert success is True
        assert '80' in msg

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['TOP_BW_ALERT_WARN_MBPS'] == 80

    def test_advanced_netwatch_keys_visible(self, tmp_path, monkeypatch):
        """Key tuning netwatch/retry harus muncul di /config."""
        from services import config_manager
        config_file = tmp_path / 'runtime_config.json'
        monkeypatch.setattr(config_manager, '_CONFIG_FILE', config_file)

        all_configs = config_manager.get_all_configs()
        monitoring_keys = [item['key'] for item in all_configs['⚙️ Monitoring']]
        alert_keys = [item['key'] for item in all_configs['🔔 Alert']]
        rate_keys = [item['key'] for item in all_configs['🛡️ Rate Limit']]

        assert 'NETWATCH_INTERVAL' in monitoring_keys
        assert 'PING_COUNT' in monitoring_keys
        assert 'NETWATCH_PING_CONCURRENCY' in monitoring_keys
        assert 'API_ACCOUNT_DEDUP_WINDOW_SEC' in monitoring_keys
        assert 'CRITICAL_RECOVERY_CONFIRM_COUNT' in alert_keys
        assert 'CRITICAL_RECOVERY_MIN_UP_SECONDS' in alert_keys
        assert 'MIKROTIK_RESET_ALL_COOLDOWN_SEC' in rate_keys

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
