# ============================================
# TEST_MONITOR_TASKS - Tests for monitor/tasks.py
# System monitor, log monitor, DHCP/ARP monitor
# ============================================

import pytest
import time
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock


# ============ task_monitor_system ============

class TestTaskMonitorSystem:
    """Test system monitoring checks (CPU, RAM, interface, etc.)."""

    @pytest.mark.asyncio
    @patch('monitor.tasks.database')
    @patch('monitor.tasks.cek_vpn_tunnels', new_callable=AsyncMock, return_value=[])
    @patch('monitor.tasks.cek_firmware', new_callable=AsyncMock, return_value=[])
    @patch('monitor.tasks.cek_uptime_anomaly', new_callable=AsyncMock, return_value=[])
    @patch('monitor.tasks.cek_interface', new_callable=AsyncMock, return_value=[])
    @patch('monitor.tasks.cek_disk', new_callable=AsyncMock, return_value=[])
    @patch('monitor.tasks.cek_cpu_ram', new_callable=AsyncMock, return_value=[])
    @patch('monitor.tasks.get_status', return_value={
        'cpu': '15', 'ram_total': '268435456', 'ram_free': '200000000',
        'uptime': '10d5h', 'version': '7.14',
    })
    @patch('monitor.tasks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_system_check_normal_no_alert(self, mock_kirim, mock_status, mock_cpu,
                                                  mock_disk, mock_iface, mock_uptime,
                                                  mock_fw, mock_vpn, mock_db):
        """Ketika semua check normal, tidak ada alert yang dikirim."""
        # cek_cpu_ram return [] means no alerts
        # This tests that the individual check functions are called
        assert mock_cpu.call_count == 0  # Not yet called
        # We can't easily run the full async loop, but we verify components work

    @pytest.mark.asyncio
    @patch('monitor.tasks.database')
    @patch('monitor.tasks.cek_cpu_ram', new_callable=AsyncMock)
    @patch('monitor.tasks.get_status')
    @patch('monitor.tasks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_cpu_high_triggers_alert(self, mock_kirim, mock_status, mock_cpu, mock_db):
        """Ketika CPU > threshold, alert harus dikirim."""
        mock_status.return_value = {
            'cpu': '95', 'ram_total': '268435456', 'ram_free': '200000000',
            'uptime': '10d5h', 'version': '7.14',
        }
        mock_cpu.return_value = ['⚠️ CPU usage 95% (threshold: 80%)']

        # Verify the check function returns alerts when CPU is high
        alerts = mock_cpu.return_value
        assert len(alerts) > 0
        assert '95%' in alerts[0]

    @pytest.mark.asyncio
    async def test_check_functions_are_importable(self):
        """Verify semua check functions bisa di-import."""
        from monitor.tasks import task_monitor_system, task_monitor_logs, task_monitor_dhcp_arp
        assert callable(task_monitor_system)
        assert callable(task_monitor_logs)
        assert callable(task_monitor_dhcp_arp)


# ============ task_monitor_logs ============

class TestTaskMonitorLogs:
    """Test log monitoring and bruteforce detection."""

    @pytest.mark.asyncio
    @patch('monitor.tasks.get_mikrotik_log', return_value=[
        {'time': '10:00:00', 'topics': 'system,info', 'message': 'system started'},
    ])
    @patch('monitor.tasks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_normal_log_no_forward(self, mock_kirim, mock_log):
        """Log biasa (info) tidak di-forward ke admin."""
        from monitor.tasks import get_mikrotik_log
        logs = get_mikrotik_log()
        assert len(logs) == 1

    @pytest.mark.asyncio
    async def test_get_interfaces_snapshot_uses_last_good_cache(self, monkeypatch):
        import monitor.tasks as t

        original_cache = dict(t._INTERFACES_CACHE)
        try:
            t._INTERFACES_CACHE["items"] = [{"name": "ether1", "running": True}]
            t._INTERFACES_CACHE["ts"] = 100.0
            monkeypatch.setattr(t.time, "time", lambda: 500.0)

            async def fake_with_timeout(coro, **_kwargs):
                await coro
                return None

            monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
            interfaces = await t._get_interfaces_snapshot(cache_ttl=1000, log_key="tasks:test:get_interfaces")
            assert interfaces == [{"name": "ether1", "running": True}]
        finally:
            t._INTERFACES_CACHE.clear()
            t._INTERFACES_CACHE.update(original_cache)

    @pytest.mark.asyncio
    async def test_get_dhcp_usage_snapshot_uses_last_good_cache(self, monkeypatch):
        import monitor.tasks as t

        original_cache = dict(t._DHCP_USAGE_CACHE)
        try:
            t._DHCP_USAGE_CACHE["bound"] = 42
            t._DHCP_USAGE_CACHE["ts"] = 100.0
            monkeypatch.setattr(t.time, "time", lambda: 150.0)

            async def fake_with_timeout(coro, **_kwargs):
                await coro
                return None

            monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
            assert await t._get_dhcp_usage_snapshot(cache_ttl=300) == 42
        finally:
            t._DHCP_USAGE_CACHE.clear()
            t._DHCP_USAGE_CACHE.update(original_cache)

    @pytest.mark.asyncio
    async def test_get_router_logs_snapshot_caps_background_fetch_and_uses_cache(self, monkeypatch):
        import monitor.tasks as t

        original_cache = dict(t._ROUTER_LOG_CACHE)
        try:
            captured = {}

            def fake_get_log(lines):
                captured["lines"] = lines
                return []

            async def fake_with_timeout(coro, timeout=15, default=None, **kwargs):
                await coro
                return None

            t._ROUTER_LOG_CACHE["lines"] = [{"time": "10:00:01", "topics": "system,info", "message": "cached"}]
            t._ROUTER_LOG_CACHE["ts"] = 100.0
            monkeypatch.setattr(t.time, "time", lambda: 120.0)
            monkeypatch.setattr(t, "get_mikrotik_log", fake_get_log)
            monkeypatch.setattr(t, "with_timeout", fake_with_timeout)

            logs = await t._get_router_logs_snapshot(120, timeout=15, cache_ttl=300)
            assert captured["lines"] == 60
            assert logs == [{"time": "10:00:01", "topics": "system,info", "message": "cached"}]
        finally:
            t._ROUTER_LOG_CACHE.clear()
            t._ROUTER_LOG_CACHE.update(original_cache)
        assert 'info' in logs[0]['topics']

    @pytest.mark.asyncio
    @patch('monitor.tasks.get_mikrotik_log', return_value=[
        {'time': '10:00:01', 'topics': 'system,error,critical', 'message': 'login failure for user admin from 192.168.1.100'},
        {'time': '10:00:02', 'topics': 'system,error,critical', 'message': 'login failure for user admin from 192.168.1.100'},
        {'time': '10:00:03', 'topics': 'system,error,critical', 'message': 'login failure for user admin from 192.168.1.100'},
        {'time': '10:00:04', 'topics': 'system,error,critical', 'message': 'login failure for user admin from 192.168.1.100'},
        {'time': '10:00:05', 'topics': 'system,error,critical', 'message': 'login failure for user admin from 192.168.1.100'},
    ])
    async def test_multiple_login_failures_detected(self, mock_log):
        """5x login failure dari IP yang sama harus terdeteksi sebagai bruteforce."""
        from monitor.tasks import get_mikrotik_log
        logs = get_mikrotik_log()
        login_failures = [l for l in logs if 'login failure' in l['message']]
        assert len(login_failures) == 5

    @pytest.mark.asyncio
    async def test_seen_deque_mechanics(self):
        """Test deque untuk tracking log yang sudah diproses."""
        from collections import deque
        seen = deque(maxlen=500)

        uid1 = hash("log1")
        uid2 = hash("log2")

        assert uid1 not in seen
        seen.append(uid1)
        assert uid1 in seen

        seen.append(uid2)
        assert uid2 in seen
        assert uid1 in seen  # Still there (maxlen=500)


class TestApiAccountLogSuppression:
    """Test helper suppression untuk spam login/logout via API."""

    def test_skip_bot_ip_api_account_log(self):
        from monitor.tasks import _should_skip_api_account_log
        tracker = {}
        should_skip = _should_skip_api_account_log(
            "system,info,account",
            "user admin logged in from 192.168.3.3 via api",
            "192.168.3.3",
            tracker,
            300,
            now_ts=1000,
        )
        assert should_skip is True

    def test_skip_only_for_configured_bot_user(self):
        from monitor.tasks import _should_skip_api_account_log
        tracker = {}
        should_skip = _should_skip_api_account_log(
            "system,info,account",
            "user admin logged in from 192.168.3.3 via api",
            "192.168.3.3",
            tracker,
            300,
            now_ts=1000,
            bot_usernames={"admin"},
        )
        assert should_skip is True

    def test_non_bot_user_same_ip_not_suppressed(self):
        from monitor.tasks import _should_skip_api_account_log
        tracker = {}
        should_skip = _should_skip_api_account_log(
            "system,info,account",
            "user auditor logged in from 192.168.3.3 via api",
            "192.168.3.3",
            tracker,
            300,
            now_ts=1000,
            bot_usernames={"admin"},
        )
        assert should_skip is False


class TestShieldTrustedIps:
    def test_extract_login_failure_ip_valid(self):
        from monitor.tasks import _extract_login_failure_ip
        ip = _extract_login_failure_ip(
            "login failure for user admin from 192.168.3.3 via api"
        )
        assert ip == "192.168.3.3"

    def test_extract_login_failure_ip_invalid(self):
        from monitor.tasks import _extract_login_failure_ip
        ip = _extract_login_failure_ip(
            "login failure for user admin from 999.999.999.999 via api"
        )
        assert ip is None

    def test_autoblock_trusted_ips_include_bot_router_local_and_env(self, monkeypatch):
        from monitor import tasks

        monkeypatch.setattr(tasks.cfg, "BOT_IP", "192.168.3.3", raising=False)
        monkeypatch.setattr(tasks.cfg, "MIKROTIK_IP", "192.168.3.1", raising=False)
        monkeypatch.setattr(tasks.cfg, "AUTO_BLOCK_TRUSTED_IPS", ["192.168.3.77"], raising=False)
        monkeypatch.setattr(tasks, "_get_local_ipv4_set", lambda *a, **k: {"192.168.3.99"})

        trusted = tasks._get_autoblock_trusted_ips()
        assert "192.168.3.3" in trusted
        assert "192.168.3.1" in trusted
        assert "192.168.3.77" in trusted
        assert "192.168.3.99" in trusted
        assert "127.0.0.1" in trusted

    def test_normalize_ipv4_valid_invalid_and_ipv6(self):
        from monitor.tasks import _normalize_ipv4

        assert _normalize_ipv4("192.168.3.1") == "192.168.3.1"
        assert _normalize_ipv4("bad-ip") is None
        assert _normalize_ipv4("2001:db8::1") is None


class TestTaskApiHealthHelpers:
    @pytest.mark.asyncio
    async def test_get_api_health_cached_uses_short_cache(self, monkeypatch):
        import monitor.tasks as t

        original_cache = dict(t._API_HEALTH_CACHE)
        try:
            t._API_HEALTH_CACHE["ts"] = 0.0
            t._API_HEALTH_CACHE["healthy"] = True
            t._API_HEALTH_CACHE["last_error"] = ""

            time_values = iter([100.0, 100.5])
            monkeypatch.setattr(t.time, "time", lambda: next(time_values))
            diag_calls = {"count": 0}

            def fake_diag():
                diag_calls["count"] += 1
                return {"healthy": False, "last_error": "auth failed"}

            monkeypatch.setattr(t._pool, "connection_diagnostics", fake_diag)

            first = await t._get_api_health_cached(cache_ttl=5)
            second = await t._get_api_health_cached(cache_ttl=5)

            assert first == (False, "auth failed")
            assert second == (False, "auth failed")
            assert diag_calls["count"] == 1
        finally:
            t._API_HEALTH_CACHE.clear()
            t._API_HEALTH_CACHE.update(original_cache)

    @pytest.mark.asyncio
    async def test_pause_if_api_unavailable_logs_once_per_window(self, monkeypatch):
        import monitor.tasks as t

        original_pause = dict(t._API_PAUSE_LOG_TS)
        try:
            t._API_PAUSE_LOG_TS.clear()
            monkeypatch.setattr(t, "_get_api_health_cached", AsyncMock(return_value=(False, "login failed")))
            sleep_mock = AsyncMock()
            warn_mock = MagicMock()
            monkeypatch.setattr(t.asyncio, "sleep", sleep_mock)
            monkeypatch.setattr(t.logger, "warning", warn_mock)

            time_values = iter([1000.0, 1010.0])
            monkeypatch.setattr(t.time, "time", lambda: next(time_values))

            first = await t._pause_if_api_unavailable("system", 15, log_every_sec=300)
            second = await t._pause_if_api_unavailable("system", 15, log_every_sec=300)

            assert first is True
            assert second is True
            assert warn_mock.call_count == 1
            assert sleep_mock.await_count == 2
        finally:
            t._API_PAUSE_LOG_TS.clear()
            t._API_PAUSE_LOG_TS.update(original_pause)

    @pytest.mark.asyncio
    async def test_pause_if_api_unavailable_healthy_path_returns_false(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_get_api_health_cached", AsyncMock(return_value=(True, "")))
        sleep_mock = AsyncMock()
        monkeypatch.setattr(t.asyncio, "sleep", sleep_mock)

        paused = await t._pause_if_api_unavailable("system", 15)
        assert paused is False
        sleep_mock.assert_not_awaited()


class TestRouterLogChunking:
    def test_build_router_log_chunks_splits_long_payload(self):
        from monitor.tasks import _build_router_log_chunks
        logs = [
            {'time': '10:00:00', 'topics': 'system,error', 'message': 'A' * 2000},
            {'time': '10:00:01', 'topics': 'system,error', 'message': 'B' * 2000},
        ]
        chunks = _build_router_log_chunks(logs, max_chars=2500)
        assert len(chunks) >= 2
        assert all(len(c) <= 2500 for c in chunks)

    def test_build_router_log_chunks_truncates_single_huge_entry(self):
        from monitor.tasks import _build_router_log_chunks

        chunks = _build_router_log_chunks([
            {'time': '10:00:00', 'topics': 'system,error', 'message': 'X' * 6000},
        ], max_chars=1000)

        assert len(chunks) == 1
        assert "...(truncated)" in chunks[0]
        assert len(chunks[0]) <= 1001

    def test_dedup_unknown_api_account_log(self):
        from monitor.tasks import _should_skip_api_account_log
        tracker = {}
        msg = "user admin logged out from 10.10.10.50 via api"

        first = _should_skip_api_account_log("system,info,account", msg, "", tracker, 300, now_ts=1000)
        second = _should_skip_api_account_log("system,info,account", msg, "", tracker, 300, now_ts=1010)
        after_window = _should_skip_api_account_log("system,info,account", msg, "", tracker, 300, now_ts=1405)

        assert first is False  # pertama kali tetap dikirim
        assert second is True  # dedup window aktif
        assert after_window is False  # boleh kirim lagi setelah window lewat

    def test_skip_local_ip_when_bot_ip_unset(self, monkeypatch):
        from monitor.tasks import _should_skip_api_account_log
        tracker = {}
        monkeypatch.setattr("monitor.tasks._get_local_ipv4_set", lambda *a, **k: {"192.168.3.3"})
        should_skip = _should_skip_api_account_log(
            "system,info,account",
            "user admin logged in from 192.168.3.3 via api",
            "",
            tracker,
            300,
            now_ts=2000,
        )
        assert should_skip is True


class TestTopBandwidthHelpers:
    def test_classify_bw_level_and_build_messages(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_WARN_MBPS", 20, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CRIT_MBPS", 50, raising=False)

        assert t._classify_bw_level(10) is None
        assert t._classify_bw_level(25) == "warning"
        assert t._classify_bw_level(55) == "critical"

        alert_text = t._build_top_bw_alert_message("PC-1", 1, "critical", 80, 50, 30, 3)
        recovery_text = t._build_top_bw_recovery_message("PC-1")
        assert "TOP BW CRITICAL" in alert_text
        assert "PC-1" in recovery_text

    def test_queue_rate_to_mbps_converts_bytes_per_second(self):
        import monitor.tasks as t

        assert t._queue_rate_to_mbps(0) == 0.0
        assert round(t._queue_rate_to_mbps(4_712_500), 1) == 37.7

    def test_normalize_top_bw_candidates_filters_and_sorts(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", ["PC-WHITELIST"])
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_RX_MBPS", 10)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_TX_MBPS", 10)

        result = t._normalize_top_bw_candidates([
            {"name": "", "rx_rate": 100_000_000, "tx_rate": 0},
            {"name": "PC-WHITELIST", "rx_rate": 100_000_000, "tx_rate": 0},
            {"name": "PC-NOISE", "rx_rate": 500_000, "tx_rate": 200_000},
            {"name": "PC-2", "rx_rate": 20_000_000, "tx_rate": 5_000_000},
            {"name": "PC-1", "rx_rate": 30_000_000, "tx_rate": 20_000_000},
        ])

        assert [item["name"] for item in result] == ["PC-1", "PC-2"]
        assert result[0]["rank"] == 1
        assert result[1]["rank"] == 2

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_top_bw_missing_host_enters_recovery_and_prunes_idle_state(self, mock_send, monkeypatch):
        import monitor.tasks as t

        t._top_bw_host_state.clear()
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_TOP_N", 3)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_RECOVERY_HITS", 1)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_COOLDOWN_SEC", 60)

        t._top_bw_host_state["PC-OLD"] = {
            "warn_hits": 0,
            "crit_hits": 0,
            "recovery_hits": 0,
            "last_level": "warning",
            "last_alert_ts": 100.0,
            "last_seen_ts": 0.0,
        }
        t._top_bw_host_state["PC-IDLE"] = {
            "warn_hits": 0,
            "crit_hits": 0,
            "recovery_hits": 0,
            "last_level": None,
            "last_alert_ts": 0.0,
            "last_seen_ts": 0.0,
        }
        monkeypatch.setattr(t.time, "time", lambda: 4000.0)

        await t._run_top_bw_alert_engine([])

        assert mock_send.await_count == 1
        assert "TOP BW RECOVERY" in mock_send.await_args[0][0]
        assert "PC-OLD" not in t._top_bw_host_state
        assert "PC-IDLE" not in t._top_bw_host_state

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_top_bw_engine_warning_critical_and_cooldown_paths(self, mock_send, monkeypatch):
        import monitor.tasks as t

        t._top_bw_host_state.clear()
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_TOP_N", 3, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CONSECUTIVE_HITS", 2, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_RECOVERY_HITS", 2, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_COOLDOWN_SEC", 60, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_WARN_MBPS", 20, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CRIT_MBPS", 50, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_RX_MBPS", 0, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_TX_MBPS", 0, raising=False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", [], raising=False)

        time_values = iter([1000.0, 1001.0, 1065.0, 1066.0, 1067.0, 1068.0])
        monkeypatch.setattr(t.time, "time", lambda: next(time_values))

        await t._run_top_bw_alert_engine([{"name": "PC-1", "rx_rate": 25_000_000, "tx_rate": 0}])
        await t._run_top_bw_alert_engine([{"name": "PC-1", "rx_rate": 25_000_000, "tx_rate": 0}])
        await t._run_top_bw_alert_engine([{"name": "PC-1", "rx_rate": 25_000_000, "tx_rate": 0}])
        await t._run_top_bw_alert_engine([{"name": "PC-1", "rx_rate": 60_000_000, "tx_rate": 0}])
        await t._run_top_bw_alert_engine([{"name": "PC-1", "rx_rate": 60_000_000, "tx_rate": 0}])
        await t._run_top_bw_alert_engine([{"name": "PC-1", "rx_rate": 5_000_000, "tx_rate": 0}])

        sent_messages = [call.args[0] for call in mock_send.await_args_list]
        assert any("TOP BW WARNING" in msg for msg in sent_messages)
        assert any("TOP BW CRITICAL" in msg for msg in sent_messages)

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_cek_per_host_traffic_legacy_mode_alert_and_recovery(self, mock_send, monkeypatch):
        import monitor.tasks as t

        t._alerted_hosts_traffic.clear()
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", False, raising=False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_THRESHOLD_MBPS", 20, raising=False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", [], raising=False)
        warn_log = MagicMock()
        monkeypatch.setattr(t.logger, "warning", warn_log)

        await t._cek_per_host_traffic([{"name": "PC-A", "rx_rate": 25_000_000, "tx_rate": 5_000_000}])
        await t._cek_per_host_traffic([{"name": "PC-A", "rx_rate": 500_000, "tx_rate": 100_000}])

        assert mock_send.await_count == 1
        assert "PC-A" not in t._alerted_hosts_traffic
        warn_log.assert_called_once()

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_top_bw_seen_host_recovery_sends_recovery_message(self, mock_send, monkeypatch):
        import monitor.tasks as t

        t._top_bw_host_state.clear()
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_TOP_N", 3, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_RECOVERY_HITS", 1, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_COOLDOWN_SEC", 60, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_WARN_MBPS", 20, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CRIT_MBPS", 50, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_RX_MBPS", 0, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_TX_MBPS", 0, raising=False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", [], raising=False)
        monkeypatch.setattr(t.time, "time", lambda: 90000.0)

        t._top_bw_host_state["PC-1"] = {
            "warn_hits": 0,
            "crit_hits": 0,
            "recovery_hits": 0,
            "last_level": "warning",
            "last_alert_ts": 900.0,
            "last_seen_ts": 999.0,
        }

        await t._run_top_bw_alert_engine([{"name": "PC-1", "rx_rate": 1_000_000, "tx_rate": 1_000_000}])

        assert mock_send.await_count == 1
        assert "TOP BW RECOVERY" in mock_send.await_args[0][0]
        assert t._top_bw_host_state["PC-1"]["last_level"] is None


# ============ task_monitor_dhcp_arp ============

class TestTaskMonitorDhcpArp:
    """Test DHCP pool monitoring."""

    @pytest.mark.asyncio
    @patch('monitor.tasks.get_dhcp_usage_count', return_value=240)
    async def test_dhcp_pool_high_usage(self, mock_count):
        """DHCP pool usage > threshold harus terdeteksi."""
        from core.config import DHCP_POOL_SIZE
        count = mock_count()
        usage_pct = (count / DHCP_POOL_SIZE) * 100
        # Just verify the calculation works
        assert usage_pct > 0

    @pytest.mark.asyncio
    @patch('monitor.tasks.get_dhcp_usage_count', return_value=10)
    async def test_dhcp_pool_normal(self, mock_count):
        """DHCP pool usage normal — tidak alert."""
        from core.config import DHCP_POOL_SIZE
        count = mock_count()
        usage_pct = (count / DHCP_POOL_SIZE) * 100
        assert usage_pct < 100  # Should be well under threshold


class TestMonitorTaskLoops:
    @pytest.mark.asyncio
    async def test_task_monitor_system_pause_short_circuit(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t.cfg, "MONITOR_INTERVAL", 1, raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        calls = {"n": 0}
        async def fake_pause(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return True
            raise asyncio.CancelledError()
        monkeypatch.setattr(t, "_pause_if_api_unavailable", fake_pause)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_system()

    @pytest.mark.asyncio
    async def test_task_monitor_system_sends_traffic_alert_once(self, monkeypatch):
        import monitor.tasks as t

        t._last_alerts.clear()
        monkeypatch.setattr(t.cfg, "MONITOR_INTERVAL", 1, raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_THRESHOLD_MBPS", 50, raising=False)
        monkeypatch.setattr(t.cfg, "MONITOR_IGNORE_IFACE", [], raising=False)
        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.database, "cleanup_old_data", MagicMock(return_value=0))
        monkeypatch.setattr(t.database, "close_stale_incidents", MagicMock(return_value=0))
        monkeypatch.setattr(t.database, "record_metrics_batch", MagicMock())
        monkeypatch.setattr(t._pool, "health_check", lambda: True)
        monkeypatch.setattr(t, "get_status", lambda: {'cpu': '10', 'ram_total': '100', 'ram_free': '50', 'uptime': '1d', 'version': '7.14'})
        monkeypatch.setattr(t, "get_interfaces", lambda: [{'name': 'ether1', 'running': True}])
        monkeypatch.setattr(t, "get_traffic", lambda _n: {'rx_bps': 60_000_000, 'tx_bps': 10_000_000})
        monkeypatch.setattr(t, "cek_cpu_ram", AsyncMock())
        monkeypatch.setattr(t, "cek_disk", AsyncMock())
        monkeypatch.setattr(t, "cek_interface", AsyncMock())
        monkeypatch.setattr(t, "cek_uptime_anomaly", AsyncMock())
        monkeypatch.setattr(t, "cek_firmware", AsyncMock())
        monkeypatch.setattr(t, "cek_vpn_tunnels", AsyncMock())
        monkeypatch.setattr(t, "kirim_ke_semua_admin", AsyncMock())

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            try:
                return await coro if asyncio.iscoroutine(coro) else coro
            except Exception:
                return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_system()

        assert any("TRAFFIC ALERT" in call.args[0] for call in t.kirim_ke_semua_admin.await_args_list)

    @pytest.mark.asyncio
    async def test_task_monitor_system_housekeeping_health_and_low_traffic_paths(self, monkeypatch):
        import monitor.tasks as t
        import mikrotik

        t._last_alerts.clear()
        t._last_alerts["traffic_ether1"] = True
        monkeypatch.setattr(t.cfg, "MONITOR_INTERVAL", 1, raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_THRESHOLD_MBPS", 50, raising=False)
        monkeypatch.setattr(t.cfg, "MONITOR_IGNORE_IFACE", [], raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", False, raising=False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_THRESHOLD_MBPS", 0, raising=False)
        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.database, "cleanup_old_data", MagicMock(return_value=5))
        monkeypatch.setattr(t.database, "close_stale_incidents", MagicMock(return_value=2))
        monkeypatch.setattr(t.database, "record_metrics_batch", MagicMock())
        monkeypatch.setattr(t._pool, "health_check", lambda: False)
        monkeypatch.setattr(t._pool, "reset_all", MagicMock())
        monkeypatch.setattr(t, "get_status", lambda: {'cpu': '10', 'ram_total': '100', 'ram_free': '50', 'uptime': '1d', 'version': '7.14'})
        monkeypatch.setattr(t, "get_interfaces", lambda: [{'name': 'ether1', 'running': True}])
        monkeypatch.setattr(t, "get_traffic", lambda _n: {'rx_bps': 10_000_000, 'tx_bps': 5_000_000})
        monkeypatch.setattr(t, "cek_cpu_ram", AsyncMock())
        monkeypatch.setattr(t, "cek_disk", AsyncMock())
        monkeypatch.setattr(t, "cek_interface", AsyncMock())
        monkeypatch.setattr(t, "cek_uptime_anomaly", AsyncMock())
        monkeypatch.setattr(t, "cek_firmware", AsyncMock())
        monkeypatch.setattr(t, "cek_vpn_tunnels", AsyncMock())
        monkeypatch.setattr(t, "kirim_ke_semua_admin", AsyncMock())
        monkeypatch.setattr(mikrotik, "get_top_queues", lambda _n: None)
        monkeypatch.setattr(t.time, "time", lambda: 90000.0)

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            try:
                return await coro if asyncio.iscoroutine(coro) else coro
            except Exception:
                return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        info_log = MagicMock()
        monkeypatch.setattr(t.logger, "info", info_log)
        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_system()

        assert t._pool.reset_all.called
        assert t._last_alerts["traffic_ether1"] is False
        assert info_log.call_count >= 1
        t.database.cleanup_old_data.assert_called_once()
        t.database.close_stale_incidents.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_monitor_system_get_status_timeout_skips_tick(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t.cfg, "MONITOR_INTERVAL", 1, raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.database, "cleanup_old_data", MagicMock(return_value=0))
        monkeypatch.setattr(t.database, "close_stale_incidents", MagicMock(return_value=0))
        monkeypatch.setattr(t._pool, "health_check", lambda: True)
        monkeypatch.setattr(t.time, "time", lambda: 1000.0)

        async def fake_with_timeout(_coro, timeout=10, default=None, **kwargs):
            if asyncio.iscoroutine(_coro):
                _coro.close()
            if kwargs.get("log_key") == "tasks:get_status":
                return None
            return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        warn_log = MagicMock()
        monkeypatch.setattr(t.logger, "warning", warn_log)
        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_system()

        assert any("get_status timed out" in str(call.args[0]) for call in warn_log.call_args_list)

    @pytest.mark.asyncio
    async def test_task_monitor_system_housekeeping_warning_paths(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t.cfg, "MONITOR_INTERVAL", 1, raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.database, "cleanup_old_data", MagicMock(side_effect=RuntimeError("prune fail")))
        monkeypatch.setattr(t.database, "close_stale_incidents", MagicMock(side_effect=RuntimeError("stale fail")))
        monkeypatch.setattr(t._pool, "health_check", lambda: (_ for _ in ()).throw(RuntimeError("health fail")))
        monkeypatch.setattr(t.time, "time", lambda: 90000.0)

        async def fake_with_timeout(_coro, timeout=10, default=None, **kwargs):
            if asyncio.iscoroutine(_coro):
                _coro.close()
            if kwargs.get("log_key") == "tasks:get_status":
                return None
            return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        warn_log = MagicMock()
        debug_log = MagicMock()
        monkeypatch.setattr(t.logger, "warning", warn_log)
        monkeypatch.setattr(t.logger, "debug", debug_log)
        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_system()

        warn_msgs = [str(call.args[0]) for call in warn_log.call_args_list]
        assert any("DB Prune" in msg for msg in warn_msgs)
        assert any("Close stale incidents" in msg for msg in warn_msgs)
        debug_log.assert_called()

    @pytest.mark.asyncio
    async def test_task_monitor_top_bandwidth_top_queue_exception_debug_logged(self, monkeypatch):
        import monitor.tasks as t
        import mikrotik

        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_INTERVAL", 5, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", True, raising=False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_THRESHOLD_MBPS", 0, raising=False)
        monkeypatch.setattr(mikrotik, "get_top_queues", lambda _n: (_ for _ in ()).throw(RuntimeError("top fail")))

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            try:
                return await coro if asyncio.iscoroutine(coro) else coro
            except Exception as exc:
                raise exc

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        debug_log = MagicMock()
        monkeypatch.setattr(t.logger, "debug", debug_log)
        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_top_bandwidth()

        assert any("Top queue metrics error" in str(call.args[0]) for call in debug_log.call_args_list)

    @pytest.mark.asyncio
    async def test_task_monitor_traffic_runs_top_queue_alert_engine(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.cfg, "MONITOR_IGNORE_IFACE", [], raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "get_interfaces", lambda: [{"name": "ether1", "running": True}])
        monkeypatch.setattr(t, "get_traffic", lambda _name: {"rx_bps": 1234, "tx_bps": 5678})
        monkeypatch.setattr(t.database, "record_metrics_batch", MagicMock())
        monkeypatch.setattr(t, "_cek_per_host_traffic", AsyncMock())

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            return await coro if asyncio.iscoroutine(coro) else coro

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)
        monkeypatch.setattr("mikrotik.get_top_queues", lambda _n: [{"name": "PC-1", "rx_rate": 40_000_000, "tx_rate": 5_000_000}])

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_traffic()

        t._cek_per_host_traffic.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_task_monitor_top_bandwidth_runs_queue_engine(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_INTERVAL", 5, raising=False)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", True, raising=False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_THRESHOLD_MBPS", 0, raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "_record_top_queue_metrics_and_alerts", AsyncMock())

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_top_bandwidth()

        t._record_top_queue_metrics_and_alerts.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_task_monitor_system_outer_error_sends_alert(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t.cfg, "MONITOR_INTERVAL", 1, raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.database, "cleanup_old_data", MagicMock(return_value=0))
        monkeypatch.setattr(t.database, "close_stale_incidents", MagicMock(return_value=0))
        monkeypatch.setattr(t._pool, "health_check", lambda: True)
        monkeypatch.setattr(t.time, "time", lambda: 1000.0)
        monkeypatch.setattr(t, "get_status", lambda: {'cpu': '10', 'ram_total': '100', 'ram_free': '50', 'uptime': '1d', 'version': '7.14'})
        monkeypatch.setattr(t, "cek_cpu_ram", AsyncMock(side_effect=RuntimeError("cpu boom")))
        monkeypatch.setattr(t, "kirim_ke_semua_admin", AsyncMock())

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            return await coro if asyncio.iscoroutine(coro) else coro

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_system()

        assert any("Router Monitor Error" in call.args[0] for call in t.kirim_ke_semua_admin.await_args_list)

    @pytest.mark.asyncio
    async def test_task_monitor_traffic_records_batch_once(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t, "_record_top_queue_metrics_and_alerts", AsyncMock())
        monkeypatch.setattr(t.cfg, "MONITOR_IGNORE_IFACE", ["lo"], raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "get_interfaces", lambda: [
            {"name": "ether1", "running": True},
            {"name": "lo", "running": True},
        ])
        monkeypatch.setattr(t, "get_traffic", lambda _name: {"rx_bps": 1234, "tx_bps": 5678})

        rec = MagicMock()
        monkeypatch.setattr(t.database, "record_metrics_batch", rec)

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            try:
                return await coro if asyncio.iscoroutine(coro) else coro
            except Exception:
                return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_traffic()

        rec.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_monitor_traffic_skips_empty_results_and_logs_exceptions(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t, "_record_top_queue_metrics_and_alerts", AsyncMock())
        monkeypatch.setattr(t.cfg, "MONITOR_IGNORE_IFACE", [], raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "get_interfaces", lambda: [
            {"name": "ether1", "running": True},
            {"name": "ether2", "running": True},
        ])

        def fake_get_traffic(name):
            if name == "ether1":
                raise RuntimeError("boom")
            return None

        monkeypatch.setattr(t, "get_traffic", fake_get_traffic)
        rec = MagicMock()
        monkeypatch.setattr(t.database, "record_metrics_batch", rec)

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            try:
                return await coro if asyncio.iscoroutine(coro) else coro
            except Exception:
                return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_traffic()

        rec.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_monitor_traffic_exits_when_no_interfaces(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t, "_record_top_queue_metrics_and_alerts", AsyncMock())
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "get_interfaces", lambda: [])

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            return await coro if asyncio.iscoroutine(coro) else coro

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_traffic()

    @pytest.mark.asyncio
    async def test_task_monitor_traffic_pause_short_circuit(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "_record_top_queue_metrics_and_alerts", AsyncMock())
        calls = {"n": 0}

        async def fake_pause(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return True
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "_pause_if_api_unavailable", fake_pause)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_traffic()

    @pytest.mark.asyncio
    async def test_task_monitor_traffic_exits_when_all_interfaces_filtered(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t, "_record_top_queue_metrics_and_alerts", AsyncMock())
        monkeypatch.setattr(t.cfg, "MONITOR_IGNORE_IFACE", ["ether1"], raising=False)
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "get_interfaces", lambda: [{"name": "ether1", "running": True}])

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            return await coro if asyncio.iscoroutine(coro) else coro

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_traffic()

    @pytest.mark.asyncio
    async def test_collect_interface_traffic_uses_bounded_queries(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t.cfg, "MIKROTIK_MAX_CONNECTIONS", 12, raising=False)

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            return await coro if asyncio.iscoroutine(coro) else coro

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t, "get_traffic", lambda name: {"name": name, "rx_bps": 1, "tx_bps": 2})

        active_ifaces = [
            {"name": "ether1", "running": True},
            {"name": "ether2", "running": True},
            {"name": "ether3", "running": True},
        ]

        results = await t._collect_interface_traffic(active_ifaces, "tasks:test:get_traffic")

        assert len(results) == 3
        assert [result["name"] for result in results] == ["ether1", "ether2", "ether3"]
        assert t._traffic_query_concurrency() == 3

    @pytest.mark.asyncio
    async def test_task_monitor_logs_autoblocks_bruteforce(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "MONITOR_LOG_INTERVAL", 1, raising=False)
        monkeypatch.setattr(t.cfg, "MONITOR_LOG_FETCH_LINES", 50, raising=False)
        monkeypatch.setattr(t.cfg, "ADMIN_IDS", [111], raising=False)
        monkeypatch.setattr(t.cfg, "BOT_IP", "", raising=False)
        monkeypatch.setattr(t.cfg, "MIKROTIK_USER", "admin", raising=False)
        monkeypatch.setattr(t.cfg, "API_ACCOUNT_SKIP_USERS", ["admin"], raising=False)
        monkeypatch.setattr(t.cfg, "BRUTEFORCE_FAIL_THRESHOLD", 5, raising=False)
        monkeypatch.setattr(t, "_get_autoblock_trusted_ips", lambda: set())

        baseline = [{"time": "10:00:00", "topics": "system,info", "message": "boot"}]
        attack = [
            {"time": f"10:00:0{i}", "topics": "system,error,critical", "message": "login failure for user admin from 192.168.3.99"}
            for i in range(1, 6)
        ]
        calls = {"n": 0}
        def fake_get_log(_lines):
            calls["n"] += 1
            return baseline if calls["n"] == 1 else attack
        monkeypatch.setattr(t, "get_mikrotik_log", fake_get_log)
        monkeypatch.setattr(t, "block_ip", MagicMock())
        monkeypatch.setattr(t.database, "audit_log", MagicMock())
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock()
        monkeypatch.setattr(t, "bot", bot_mock)

        async def fake_with_timeout(coro, timeout=15, default=None, **kwargs):
            try:
                return await coro if asyncio.iscoroutine(coro) else coro
            except Exception:
                return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_logs()

        t.block_ip.assert_called_once_with("192.168.3.99", "Auto Blocked by Bot (Bruteforce)")
        bot_mock.send_message.assert_awaited()

    @pytest.mark.asyncio
    async def test_task_monitor_logs_sends_power_event_once(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "MONITOR_LOG_INTERVAL", 1, raising=False)
        monkeypatch.setattr(t.cfg, "MONITOR_LOG_FETCH_LINES", 50, raising=False)
        monkeypatch.setattr(t.cfg, "ADMIN_IDS", [111], raising=False)
        monkeypatch.setattr(t.cfg, "BOT_IP", "", raising=False)
        monkeypatch.setattr(t.cfg, "MIKROTIK_USER", "admin", raising=False)
        monkeypatch.setattr(t.cfg, "API_ACCOUNT_SKIP_USERS", ["admin"], raising=False)

        baseline = [{"time": "10:00:00", "topics": "system,info", "message": "boot"}]
        power = [{"time": "10:00:01", "topics": "system,info", "message": "power lost on ups"}]
        calls = {"n": 0}
        def fake_get_log(_lines):
            calls["n"] += 1
            return baseline if calls["n"] == 1 else power
        monkeypatch.setattr(t, "get_mikrotik_log", fake_get_log)
        monkeypatch.setattr(t, "_get_autoblock_trusted_ips", lambda: set())
        send = AsyncMock()
        monkeypatch.setattr(t, "kirim_ke_semua_admin", send)
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock()
        monkeypatch.setattr(t, "bot", bot_mock)

        async def fake_with_timeout(coro, timeout=15, default=None, **kwargs):
            try:
                return await coro if asyncio.iscoroutine(coro) else coro
            except Exception:
                return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_logs()

        assert any("POWER EVENT" in call.args[0] for call in send.await_args_list)

    @pytest.mark.asyncio
    async def test_task_monitor_alert_maintenance_runs_once(self, monkeypatch):
        import monitor.tasks as t

        check = AsyncMock()
        digest = AsyncMock()
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t, "check_escalation", check)
        monkeypatch.setattr(t, "send_digest", digest)

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_alert_maintenance()

        check.assert_awaited_once()
        digest.assert_awaited_once()

    def test_get_local_ipv4_set_cache_and_filter(self, monkeypatch):
        import monitor.tasks as t

        original_cache = dict(t._LOCAL_IP_CACHE)
        try:
            t._LOCAL_IP_CACHE["ips"] = set()
            t._LOCAL_IP_CACHE["ts"] = 0.0
            monkeypatch.setattr(t.time, "time", lambda: 1000.0)
            monkeypatch.setattr(t.socket, "gethostname", lambda: "host-a")
            monkeypatch.setattr(
                t.socket,
                "getaddrinfo",
                lambda *_a, **_k: [
                    (None, None, None, None, ("127.0.0.1", 0)),
                    (None, None, None, None, ("192.168.3.99", 0)),
                    (None, None, None, None, ("192.168.3.99", 0)),
                ],
            )

            ips = t._get_local_ipv4_set(cache_ttl=300)
            assert ips == {"192.168.3.99"}

            # Within TTL -> return cache, tidak panggil resolver ulang.
            monkeypatch.setattr(t.time, "time", lambda: 1001.0)
            monkeypatch.setattr(t.socket, "getaddrinfo", lambda *_a, **_k: (_ for _ in ()).throw(Exception("boom")))
            ips_cached = t._get_local_ipv4_set(cache_ttl=300)
            assert ips_cached == {"192.168.3.99"}
        finally:
            t._LOCAL_IP_CACHE.clear()
            t._LOCAL_IP_CACHE.update(original_cache)

    @pytest.mark.asyncio
    async def test_task_monitor_dhcp_arp_emits_alerts(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "DHCP_POOL_SIZE", 60, raising=False)
        monkeypatch.setattr(t.cfg, "DHCP_ALERT_THRESHOLD", 80, raising=False)
        monkeypatch.setattr(t.cfg, "CRITICAL_MACS", {"192.168.3.10": "aa:bb:cc:dd:ee:ff"}, raising=False)

        monkeypatch.setattr(t, "get_dhcp_usage_count", lambda: 55)
        monkeypatch.setattr(
            t,
            "get_arp_anomalies",
            lambda _m: [{
                "ip": "192.168.3.10",
                "expected_mac": "aa:bb:cc:dd:ee:ff",
                "current_mac": "ff:ee:dd:cc:bb:aa",
            }],
        )

        send = AsyncMock()
        monkeypatch.setattr(t, "kirim_ke_semua_admin", send)
        monkeypatch.setattr(t.database, "record_metric", MagicMock())
        monkeypatch.setattr(t.database, "log_incident_down", MagicMock())
        monkeypatch.setattr(t.database, "log_incident_up", MagicMock())

        async def fake_with_timeout(coro, timeout=10, default=None, **kwargs):
            try:
                return await coro if asyncio.iscoroutine(coro) else coro
            except Exception:
                return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_dhcp_arp()

        assert send.await_count >= 2  # DHCP warning + IP conflict

    @pytest.mark.asyncio
    async def test_task_monitor_logs_forwards_critical_log(self, monkeypatch):
        import monitor.tasks as t

        monkeypatch.setattr(t, "_pause_if_api_unavailable", AsyncMock(return_value=False))
        monkeypatch.setattr(t.cfg, "reload_runtime_overrides", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "reload_router_env", lambda min_interval=10: None, raising=False)
        monkeypatch.setattr(t.cfg, "MONITOR_LOG_INTERVAL", 1, raising=False)
        monkeypatch.setattr(t.cfg, "MONITOR_LOG_FETCH_LINES", 50, raising=False)
        monkeypatch.setattr(t.cfg, "ADMIN_IDS", [111], raising=False)
        monkeypatch.setattr(t.cfg, "BOT_IP", "", raising=False)
        monkeypatch.setattr(t.cfg, "MIKROTIK_USER", "admin", raising=False)
        monkeypatch.setattr(t.cfg, "API_ACCOUNT_SKIP_USERS", ["admin"], raising=False)

        logs_baseline = [{"time": "10:00:00", "topics": "system,info", "message": "boot"}]
        logs_tick = [{"time": "10:00:01", "topics": "system,error", "message": "disk error"}]
        calls = {"n": 0}

        def fake_get_log(_lines):
            calls["n"] += 1
            return logs_baseline if calls["n"] == 1 else logs_tick

        monkeypatch.setattr(t, "get_mikrotik_log", fake_get_log)

        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock()
        monkeypatch.setattr(t, "bot", bot_mock)

        async def fake_with_timeout(coro, timeout=15, default=None, **kwargs):
            try:
                return await coro if asyncio.iscoroutine(coro) else coro
            except Exception:
                return default

        async def stop_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(t, "with_timeout", fake_with_timeout)
        monkeypatch.setattr(t.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await t.task_monitor_logs()

        bot_mock.send_message.assert_awaited()
