# ============================================
# TEST_CONFIG - Tests for core/config.py
# ============================================

import os
import json
import pytest
from unittest.mock import patch


class TestConfigParsing:
    """Test konfigurasi parsing dari environment variables."""

    def test_admin_ids_multi(self, monkeypatch):
        """Multi admin IDs (comma-separated) harus di-parse benar."""
        monkeypatch.setenv("ADMIN_IDS", "111,222,333")
        
        # Reimport to pick up new env
        import importlib
        import core.config
        importlib.reload(core.config)
        
        assert core.config.ADMIN_IDS == [111, 222, 333]
        assert core.config.CHAT_ID == 111  # First admin

    def test_admin_ids_fallback_to_chat_id(self, monkeypatch):
        """Jika ADMIN_IDS kosong, fallback ke CHAT_ID."""
        monkeypatch.setenv("ADMIN_IDS", "")
        monkeypatch.setenv("CHAT_ID", "99999")
        
        import importlib
        import core.config
        importlib.reload(core.config)
        
        assert core.config.ADMIN_IDS == [99999]

    def test_default_values(self, monkeypatch, tmp_path):
        """Default values harus benar jika .env tidak set."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TOKEN", "dummy-token")
        monkeypatch.setenv("CHAT_ID", "123456")
        monkeypatch.setenv("MIKROTIK_IP", "192.0.2.1")
        monkeypatch.setenv("MIKROTIK_USER", "tester")
        monkeypatch.setenv("MIKROTIK_PASS", "secret")

        for key in (
            "CPU_THRESHOLD",
            "RAM_THRESHOLD",
            "DISK_THRESHOLD",
            "MONITOR_INTERVAL",
            "PING_COUNT",
            "RATE_LIMIT_PER_MINUTE",
            "REBOOT_COOLDOWN",
        ):
            monkeypatch.delenv(key, raising=False)

        import importlib
        import core.config
        importlib.reload(core.config)
        
        assert core.config.CPU_THRESHOLD == 80
        assert core.config.RAM_THRESHOLD == 90
        assert core.config.DISK_THRESHOLD == 85
        assert core.config.MONITOR_INTERVAL == 300
        assert isinstance(core.config.PING_COUNT, int)
        assert isinstance(core.config.RATE_LIMIT_PER_MINUTE, int)
        assert isinstance(core.config.REBOOT_COOLDOWN, int)

    def test_mikrotik_use_ssl(self, monkeypatch):
        """Boolean parsing untuk MIKROTIK_USE_SSL."""
        monkeypatch.setenv("MIKROTIK_USE_SSL", "true")
        
        import importlib
        import core.config
        importlib.reload(core.config)
        
        assert core.config.MIKROTIK_USE_SSL is True
        
        monkeypatch.setenv("MIKROTIK_USE_SSL", "False")
        importlib.reload(core.config)
        assert core.config.MIKROTIK_USE_SSL is False

    def test_servers_fallback_parsing(self, monkeypatch):
        """SERVERS env parsing ke dict {name: ip}."""
        monkeypatch.setenv("SERVERS", "WebServer:10.0.0.1,DBServer:10.0.0.2")
        
        import importlib
        import core.config
        importlib.reload(core.config)
        
        assert core.config.SERVERS_FALLBACK == {
            'WebServer': '10.0.0.1',
            'DBServer': '10.0.0.2'
        }

    def test_critical_devices_and_names_parsing(self, monkeypatch):
        """CRITICAL_DEVICES + CRITICAL_DEVICE_NAMES harus ter-parse benar."""
        monkeypatch.setenv("CRITICAL_DEVICES", "IGD:192.168.3.50,POLI:192.168.3.51")
        monkeypatch.setenv("CRITICAL_DEVICE_NAMES", "KOMP PENDAFTARAN IGD,KOMP PENDAFTARAN POLI")

        import importlib
        import core.config
        importlib.reload(core.config)

        assert core.config.CRITICAL_DEVICES_FALLBACK == {
            'IGD': '192.168.3.50',
            'POLI': '192.168.3.51',
        }
        assert core.config.CRITICAL_DEVICE_NAMES == [
            "KOMP PENDAFTARAN IGD",
            "KOMP PENDAFTARAN POLI",
        ]

    def test_tcp_services_parsing(self, monkeypatch):
        """TCP_SERVICES env parsing ke list of dicts."""
        monkeypatch.setenv("TCP_SERVICES", "MySQL:192.168.1.10:3306,Redis:192.168.1.11:6379")
        
        import importlib
        import core.config
        importlib.reload(core.config)
        
        assert len(core.config.TCP_SERVICES) == 2
        assert core.config.TCP_SERVICES[0] == {'name': 'MySQL', 'ip': '192.168.1.10', 'port': 3306}
        assert core.config.TCP_SERVICES[1] == {'name': 'Redis', 'ip': '192.168.1.11', 'port': 6379}

    def test_no_legacy_targets_when_env_empty(self, monkeypatch):
        """Jika env kosong, fallback server/TCP harus kosong (tidak inject host legacy)."""
        monkeypatch.setenv("SERVERS", "")
        monkeypatch.setenv("TCP_SERVICES", "")

        import importlib
        import core.config
        importlib.reload(core.config)

        assert core.config.SERVERS_FALLBACK == {}
        assert core.config.TCP_SERVICES == []

    def test_alert_config_defaults(self, monkeypatch):
        """Alert config defaults harus ada."""
        import importlib
        import core.config
        importlib.reload(core.config)
        
        assert core.config.ALERT_ESCALATION_MINUTES == 15
        assert core.config.ALERT_DIGEST_THRESHOLD == 5
        assert core.config.ALERT_DIGEST_WINDOW == 300

    def test_dns_check_domain_multi_parse(self, monkeypatch):
        """DNS_CHECK_DOMAIN bisa diisi multi-domain (comma-separated)."""
        monkeypatch.setenv("DNS_CHECK_DOMAIN", "google.com, cloudflare.com")

        import importlib
        import core.config
        importlib.reload(core.config)

        assert core.config.DNS_CHECK_DOMAINS == ["google.com", "cloudflare.com"]
        assert core.config.DNS_CHECK_DOMAIN == "google.com"

    def test_runtime_override_reload_and_reset(self, tmp_path, monkeypatch):
        """Reload override runtime harus apply nilai baru dan reset ke default saat file hilang."""
        import core.config as cfg

        runtime_file = tmp_path / "runtime_config.json"
        monkeypatch.setattr(cfg, "_RUNTIME_CONFIG_FILE", runtime_file, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_reload_ts", 0.0, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_mtime", None, raising=False)

        cpu_default = cfg._DEFAULT_OVERRIDABLES["CPU_THRESHOLD"]
        rec_default = cfg._DEFAULT_OVERRIDABLES["RECOVERY_CONFIRM_COUNT"]

        runtime_file.write_text(json.dumps({
            "CPU_THRESHOLD": 91,
            "RECOVERY_CONFIRM_COUNT": 4
        }))
        cfg.reload_runtime_overrides(force=True, min_interval=0)
        assert cfg.CPU_THRESHOLD == 91
        assert cfg.RECOVERY_CONFIRM_COUNT == 4

        runtime_file.unlink()
        cfg.reload_runtime_overrides(force=True, min_interval=0)
        assert cfg.CPU_THRESHOLD == cpu_default
        assert cfg.RECOVERY_CONFIRM_COUNT == rec_default

    def test_runtime_override_bool(self, tmp_path, monkeypatch):
        """Runtime override boolean harus diterapkan dengan benar."""
        import core.config as cfg

        runtime_file = tmp_path / "runtime_config.json"
        monkeypatch.setattr(cfg, "_RUNTIME_CONFIG_FILE", runtime_file, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_reload_ts", 0.0, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_mtime", None, raising=False)

        runtime_file.write_text(json.dumps({
            "MONITOR_VPN_ENABLED": False,
            "TOP_BW_ALERT_ENABLED": True,
            "ALERT_REQUIRE_START": True,
        }))
        cfg.reload_runtime_overrides(force=True, min_interval=0)
        assert cfg.MONITOR_VPN_ENABLED is False
        assert cfg.TOP_BW_ALERT_ENABLED is True
        assert cfg.ALERT_REQUIRE_START is True

    def test_runtime_override_ping_count_supported(self, tmp_path, monkeypatch):
        """PING_COUNT harus ikut mekanisme runtime override lintas-proses."""
        import core.config as cfg

        runtime_file = tmp_path / "runtime_config.json"
        monkeypatch.setattr(cfg, "_RUNTIME_CONFIG_FILE", runtime_file, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_reload_ts", 0.0, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_mtime", None, raising=False)

        default_ping = cfg._DEFAULT_OVERRIDABLES["PING_COUNT"]
        runtime_file.write_text(json.dumps({"PING_COUNT": 7}), encoding="utf-8")

        cfg.reload_runtime_overrides(force=True, min_interval=0)
        assert cfg.PING_COUNT == 7

        runtime_file.unlink()
        cfg.reload_runtime_overrides(force=True, min_interval=0)
        assert cfg.PING_COUNT == default_ping

    def test_reload_router_env_updates_runtime_fields(self, tmp_path, monkeypatch):
        """reload_router_env harus mengupdate field operasi penting saat .env berubah."""
        import core.config as cfg

        custom_env = tmp_path / ".env"
        custom_env.write_text(
            "\n".join([
                "ADMIN_IDS=111,222",
                "MIKROTIK_IP=192.0.2.10",
                "MONITOR_IGNORE_IFACE=ether3,ether4",
                "DNS_CHECK_DOMAIN=google.com,cloudflare.com",
                "GW_WAN=192.0.2.1",
                "GW_INET=1.1.1.1",
                "CRITICAL_DEVICES=IGD:192.0.2.50,POLI:192.0.2.51",
                "CRITICAL_DEVICE_NAMES=KOMP PENDAFTARAN IGD,KOMP PENDAFTARAN POLI",
                "DHCP_POOL_SIZE=120",
                "INSTITUTION_NAME=Test Site",
            ]),
            encoding="utf-8",
        )

        monkeypatch.setattr(cfg, "env_path", custom_env, raising=False)
        monkeypatch.setattr(cfg, "_router_env_last_reload_ts", 0.0, raising=False)
        monkeypatch.setattr(cfg, "_router_env_last_mtime", None, raising=False)

        changed = cfg.reload_router_env(force=True, min_interval=0)
        assert changed is True
        assert cfg.ADMIN_IDS == [111, 222]
        assert cfg.CHAT_ID == 111
        assert cfg.MIKROTIK_IP == "192.0.2.10"
        assert cfg.MONITOR_IGNORE_IFACE == {"ether3", "ether4"}
        assert cfg.DNS_CHECK_DOMAINS == ["google.com", "cloudflare.com"]
        assert cfg.CRITICAL_DEVICES_FALLBACK == {"IGD": "192.0.2.50", "POLI": "192.0.2.51"}
        assert cfg.CRITICAL_DEVICE_NAMES == ["KOMP PENDAFTARAN IGD", "KOMP PENDAFTARAN POLI"]
        assert cfg.DHCP_POOL_SIZE == 120
        assert cfg.INSTITUTION_NAME == "Test Site"

    def test_parse_hhmm_helpers(self):
        import core.config as cfg

        assert cfg._parse_hhmm_to_minutes("07:30") == 450
        assert cfg._parse_hhmm_to_minutes("25:00") is None
        assert cfg._parse_hhmm_to_minutes("bad") is None
        assert cfg._parse_critical_device_windows(
            "POLI=07:00-17:00,INVALID,IGD=08:00-bad, =09:00-10:00"
        ) == {"POLI": (420, 1020)}

    def test_critical_mac_parsing_and_guardrail(self, monkeypatch):
        monkeypatch.setenv("CRITICAL_MACS", "192.168.3.10=AA:BB:CC:DD:EE:FF,192.168.3.11:11:22:33")
        monkeypatch.setenv("TOP_BW_ALERT_WARN_MBPS", "90")
        monkeypatch.setenv("TOP_BW_ALERT_CRIT_MBPS", "40")

        import importlib
        import core.config
        importlib.reload(core.config)

        assert core.config.CRITICAL_MACS["192.168.3.10"] == "aa:bb:cc:dd:ee:ff"
        assert core.config.CRITICAL_MACS["192.168.3.11"] == "11:22:33"
        assert core.config.TOP_BW_ALERT_CRIT_MBPS == 90

    def test_assert_range_raises(self):
        import core.config as cfg

        with pytest.raises(ValueError):
            cfg._assert_range("CPU_THRESHOLD", 200, 10, 100)

    def test_runtime_override_skip_paths_and_guardrail(self, tmp_path, monkeypatch):
        import core.config as cfg

        runtime_file = tmp_path / "runtime_config.json"
        monkeypatch.setattr(cfg, "_RUNTIME_CONFIG_FILE", runtime_file, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_reload_ts", 0.0, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_mtime", None, raising=False)

        runtime_file.write_text(
            json.dumps(
                {
                    "UNKNOWN": 1,
                    "TOP_BW_ALERT_WARN_MBPS": 70,
                    "TOP_BW_ALERT_CRIT_MBPS": 50,
                    "MONITOR_VPN_ENABLED": "off",
                    "ALERT_REQUIRE_START": 1,
                    "CPU_THRESHOLD": "oops",
                }
            ),
            encoding="utf-8",
        )

        assert cfg.reload_runtime_overrides(force=True, min_interval=0) is True
        assert cfg.MONITOR_VPN_ENABLED is False
        assert cfg.ALERT_REQUIRE_START is True
        assert cfg.TOP_BW_ALERT_CRIT_MBPS == 70

        now = cfg._time.time()
        monkeypatch.setattr(cfg, "_last_runtime_reload_ts", now, raising=False)
        assert cfg.reload_runtime_overrides(force=False, min_interval=60) is False

        monkeypatch.setattr(cfg, "_last_runtime_reload_ts", 0.0, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_mtime", runtime_file.stat().st_mtime, raising=False)
        assert cfg.reload_runtime_overrides(force=False, min_interval=0) is True

    def test_runtime_override_handles_bad_json_and_stat_error(self, tmp_path, monkeypatch):
        import core.config as cfg

        runtime_file = tmp_path / "runtime_config.json"
        monkeypatch.setattr(cfg, "_RUNTIME_CONFIG_FILE", runtime_file, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_reload_ts", 0.0, raising=False)
        monkeypatch.setattr(cfg, "_last_runtime_mtime", None, raising=False)

        runtime_file.write_text("{bad json", encoding="utf-8")
        assert cfg.reload_runtime_overrides(force=True, min_interval=0) is True

        class BadStatPath:
            def exists(self):
                return True

            def stat(self):
                raise OSError("boom")

        monkeypatch.setattr(cfg, "_RUNTIME_CONFIG_FILE", BadStatPath(), raising=False)
        assert cfg.reload_runtime_overrides(force=True, min_interval=0) is True

    def test_reload_router_env_skip_and_error_paths(self, tmp_path, monkeypatch):
        import core.config as cfg

        custom_env = tmp_path / ".env"
        custom_env.write_text("MIKROTIK_IP=192.0.2.10\n", encoding="utf-8")
        monkeypatch.setattr(cfg, "env_path", custom_env, raising=False)

        now = cfg._time.time()
        monkeypatch.setattr(cfg, "_router_env_last_reload_ts", now, raising=False)
        assert cfg.reload_router_env(force=False, min_interval=60) is False

        monkeypatch.setattr(cfg, "_router_env_last_reload_ts", 0.0, raising=False)
        monkeypatch.setattr(cfg, "_router_env_last_mtime", custom_env.stat().st_mtime, raising=False)
        assert cfg.reload_router_env(force=False, min_interval=0) is False

        monkeypatch.setattr(cfg, "_router_env_last_mtime", None, raising=False)
        with patch("core.config.dotenv_values", side_effect=RuntimeError("broken")):
            assert cfg.reload_router_env(force=True, min_interval=0) is False

        with patch("core.config.dotenv_values", return_value={}):
            assert cfg.reload_router_env(force=True, min_interval=0) is False

    def test_reload_router_env_invalid_values_fall_back(self, tmp_path, monkeypatch):
        import core.config as cfg

        custom_env = tmp_path / ".env"
        custom_env.write_text(
            "\n".join(
                [
                    "ADMIN_IDS=bad",
                    "MIKROTIK_PORT=99999",
                    "MIKROTIK_FTP_PORT=99999",
                    "MIKROTIK_USE_SSL=yes",
                    "MIKROTIK_TLS_VERIFY=no",
                    "MIKROTIK_FTP_TLS=1",
                    "MIKROTIK_FTP_ALLOW_INSECURE=1",
                    "MIKROTIK_MAX_CONNECTIONS=9999",
                    "MIKROTIK_RECONNECT_BASE_BACKOFF=0",
                    "MIKROTIK_RECONNECT_MAX_BACKOFF=99999",
                    "ASYNC_THREAD_WORKERS=1",
                    "MIKROTIK_CONNECTION_MAX_AGE_SEC=999999",
                    "MONITOR_VPN_ENABLED=no",
                    "MONITOR_VPN_IGNORE_NAMES=vpn-a,Vpn-B",
                    "NETWATCH_INTERVAL=4",
                    "MONITOR_LOG_FETCH_LINES=5",
                    "NETWATCH_PING_CONCURRENCY=50",
                    "API_ACCOUNT_DEDUP_WINDOW_SEC=10",
                    "SERVERS=SRV1:192.168.3.10",
                    "WIFI_APS=AP1:192.168.3.20",
                    "CRITICAL_DEVICE_WINDOWS=POLI=07:00-17:00",
                    "TOP_BW_ALERT_WARN_MBPS=80",
                    "TOP_BW_ALERT_CRIT_MBPS=20",
                    "NETWATCH_UP_MIN_SUCCESS_RATIO=9.0",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(cfg, "env_path", custom_env, raising=False)
        monkeypatch.setattr(cfg, "_router_env_last_reload_ts", 0.0, raising=False)
        monkeypatch.setattr(cfg, "_router_env_last_mtime", None, raising=False)

        old_admin_ids = list(cfg.ADMIN_IDS)
        old_port = cfg.MIKROTIK_PORT
        old_ftp_port = cfg.MIKROTIK_FTP_PORT
        assert cfg.reload_router_env(force=True, min_interval=0) is True

        assert cfg.ADMIN_IDS == old_admin_ids
        assert cfg.MIKROTIK_PORT == old_port
        assert cfg.MIKROTIK_FTP_PORT == old_ftp_port
        assert cfg.MIKROTIK_USE_SSL is True
        assert cfg.MIKROTIK_TLS_VERIFY is False
        assert cfg.MIKROTIK_FTP_TLS is True
        assert cfg.MIKROTIK_FTP_ALLOW_INSECURE is True
        assert cfg.MONITOR_VPN_ENABLED is False
        assert cfg.MONITOR_VPN_IGNORE_NAMES == {"vpn-a", "vpn-b"}
        assert cfg.SERVERS_FALLBACK == {"SRV1": "192.168.3.10"}
        assert cfg.APS_FALLBACK == {"AP1": "192.168.3.20"}
        assert cfg.CRITICAL_DEVICE_WINDOWS == {"POLI": (420, 1020)}
        assert cfg.TOP_BW_ALERT_CRIT_MBPS == 80
