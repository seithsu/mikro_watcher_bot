# ============================================
# TEST_NETWATCH - Tests for monitor/netwatch.py
# Ping, TCP, DNS check, state machine
# ============================================

import pytest
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock


class TestHostPing:
    """Test _host_ping function."""

    @pytest.mark.asyncio
    @patch('monitor.netwatch.ping_host', return_value={'sent': 1, 'received': 1})
    async def test_ping_localhost(self, mock_ping):
        """Ping localhost should succeed (mocked)."""
        from monitor.netwatch import _host_ping
        result = await _host_ping("127.0.0.1", count=1)
        assert result is True
        mock_ping.assert_called_once()

    @pytest.mark.asyncio
    @patch('monitor.netwatch.ping_host', return_value={'sent': 1, 'received': 0})
    async def test_ping_invalid_host(self, mock_ping):
        """Ping with 0 received should fail."""
        from monitor.netwatch import _host_ping
        result = await _host_ping("192.0.2.254", count=1)
        assert result is False

    @pytest.mark.asyncio
    @patch('monitor.netwatch.ping_host', return_value={'sent': 4, 'received': 1})
    async def test_ping_requires_min_success_ratio(self, mock_ping, monkeypatch):
        from monitor.netwatch import _host_ping
        import monitor.netwatch as nw

        monkeypatch.setattr(nw.config, "NETWATCH_UP_MIN_SUCCESS_RATIO", 0.5, raising=False)
        result = await _host_ping("192.0.2.123", count=4)
        assert result is False

    @pytest.mark.asyncio
    @patch('monitor.netwatch.ping_host', side_effect=Exception("not logged in"))
    async def test_ping_not_logged_in_returns_none(self, mock_ping):
        from monitor.netwatch import _host_ping
        result = await _host_ping("192.168.3.1", count=1)
        assert result is None


class TestTcpCheck:
    """Test _tcp_check function."""

    @pytest.mark.asyncio
    async def test_tcp_check_closed_port(self):
        """TCP check ke port yang tidak ada harus gagal."""
        from monitor.netwatch import _tcp_check
        result = await _tcp_check("127.0.0.1", 59999, timeout=0.5)
        assert result is False

    @pytest.mark.asyncio
    async def test_tcp_check_timeout(self):
        """TCP check timeout harus return False."""
        from monitor.netwatch import _tcp_check
        result = await _tcp_check("192.0.2.254", 80, timeout=0.3)
        assert result is False


class TestDnsCheck:
    """Test _dns_check function."""

    @pytest.mark.asyncio
    async def test_dns_check_returns_bool(self):
        """DNS check should return a boolean."""
        from monitor.netwatch import _dns_check
        result = await _dns_check("localhost", timeout=2)
        assert isinstance(result, bool)


class TestAlertTimestamp:
    def test_alert_timestamp_has_no_timezone_suffix(self):
        from monitor.netwatch import _alert_timestamp

        ts = _alert_timestamp()
        assert "SE Asia Standard Time" not in ts
        assert len(ts) == 19

    def test_format_duration_seconds_compact(self):
        from monitor.netwatch import _format_duration_seconds

        assert _format_duration_seconds(0) == "0s"
        assert _format_duration_seconds(65) == "1m 5s"
        assert _format_duration_seconds(3661) == "1j 1m 1s"
        assert _format_duration_seconds(90061) == "1h 1j 1m 1s"


def test_host_fail_threshold_prefers_override(monkeypatch):
    import monitor.netwatch as nw

    monkeypatch.setattr(nw.config, "PING_FAIL_THRESHOLD", 3, raising=False)
    monkeypatch.setattr(nw.config, "NETWATCH_FAIL_THRESHOLD_OVERRIDES", {"192.168.3.145": 8}, raising=False)

    assert nw._host_fail_threshold("192.168.3.145") == 8
    assert nw._host_fail_threshold("192.168.3.10") == 3


def test_netwatch_compute_sleep_with_jitter_adds_positive_jitter(monkeypatch):
    import monitor.netwatch as nw

    monkeypatch.setattr(nw.random, "uniform", lambda a, b: 1.25)

    assert nw._compute_sleep_with_jitter(10, jitter_ratio=0.2, max_jitter=3.0) == 11.25


@pytest.mark.asyncio
async def test_load_monitored_topology_reuses_last_good_cache(monkeypatch):
    import monitor.netwatch as nw

    orig_cache = dict(nw._topology_cache)
    try:
        nw._topology_cache.update({
            "ts": 0.0,
            "aps": {"AP1": "192.168.3.145"},
            "servers": {"SIMRS": "192.168.3.10"},
            "critical": {"IGD": "192.168.3.90"},
            "gw_wan": "192.168.1.1",
        })

        calls = {"n": 0}

        async def fake_with_timeout(_coro, timeout=10, default=None, log_key=None, **kwargs):
            calls["n"] += 1
            if hasattr(_coro, "close"):
                _coro.close()
            return None

        monkeypatch.setattr(nw, "with_timeout", fake_with_timeout)

        aps, servers, critical, gw = await nw._load_monitored_topology(refresh_ttl=0)

        assert aps == {"AP1": "192.168.3.145"}
        assert servers == {"SIMRS": "192.168.3.10"}
        assert critical == {"IGD": "192.168.3.90"}
        assert gw == "192.168.1.1"
        assert calls["n"] == 4
    finally:
        nw._topology_cache.clear()
        nw._topology_cache.update(orig_cache)


@pytest.mark.asyncio
async def test_load_monitored_topology_filters_ignored_hosts(monkeypatch):
    import monitor.netwatch as nw

    orig_cache = dict(nw._topology_cache)
    monkeypatch.setattr(nw.config, "NETWATCH_IGNORE_HOSTS", ["192.168.3.145", "192.168.3.147"], raising=False)

    async def fake_with_timeout(_coro, timeout=10, default=None, log_key=None, **kwargs):
        if hasattr(_coro, "close"):
            _coro.close()
        if log_key == "netwatch:get_monitored_aps":
            return {"AP1": "192.168.3.145", "AP2": "192.168.3.148"}
        if log_key == "netwatch:get_monitored_servers":
            return {"SIMRS": "192.168.3.10", "BOT": "192.168.3.147"}
        if log_key == "netwatch:get_monitored_critical_devices":
            return {"IGD": "192.168.3.90"}
        if log_key == "netwatch:get_default_gateway":
            return "192.168.1.1"
        return None

    try:
        nw._topology_cache.update({
            "ts": 0.0,
            "aps": {},
            "servers": {},
            "critical": {},
            "gw_wan": "",
        })
        monkeypatch.setattr(nw, "with_timeout", fake_with_timeout)

        aps, servers, critical, gw = await nw._load_monitored_topology(refresh_ttl=0)

        assert aps == {"AP2": "192.168.3.148"}
        assert servers == {"SIMRS": "192.168.3.10"}
        assert critical == {"IGD": "192.168.3.90"}
        assert gw == "192.168.1.1"
    finally:
        nw._topology_cache.clear()
        nw._topology_cache.update(orig_cache)


def test_static_monitored_hosts_respects_ignore_list(monkeypatch):
    import monitor.netwatch as nw

    monkeypatch.setattr(nw.config, "NETWATCH_IGNORE_HOSTS", ["192.168.3.145", "192.168.3.147"], raising=False)
    monkeypatch.setattr(nw.config, "MIKROTIK_IP", "192.168.3.1", raising=False)
    monkeypatch.setattr(nw.config, "GW_WAN", "192.168.1.1", raising=False)
    monkeypatch.setattr(nw.config, "GW_INET", "1.1.1.1", raising=False)
    monkeypatch.setattr(nw.config, "SERVERS_FALLBACK", {"SIMRS": "192.168.3.10"}, raising=False)
    monkeypatch.setattr(nw.config, "APS_FALLBACK", {"AP1": "192.168.3.145", "AP2": "192.168.3.148"}, raising=False)
    monkeypatch.setattr(nw.config, "CRITICAL_DEVICES_FALLBACK", {"BOT": "192.168.3.147"}, raising=False)
    monkeypatch.setattr(nw.config, "TCP_SERVICES", [], raising=False)

    hosts = nw._static_monitored_hosts()

    assert "192.168.3.145" not in hosts
    assert "192.168.3.147" not in hosts
    assert "192.168.3.148" in hosts
    assert "192.168.3.10" in hosts


class TestNetworkClassification:
    """Test network status classification."""

    def test_all_up_is_normal(self):
        from core.classification import classify_network_status
        state = {'192.168.1.1': True, '1.1.1.1': True, '8.8.8.8': True}
        result = classify_network_status(state, {}, {},
            router_ip='192.168.1.1', gw_wan='1.1.1.1', gw_inet='8.8.8.8')
        assert 'NORMAL' in result

    def test_internet_down(self):
        from core.classification import classify_network_status
        state = {'192.168.1.1': True, '1.1.1.1': True, '8.8.8.8': False}
        result = classify_network_status(state, {}, {},
            router_ip='192.168.1.1', gw_wan='1.1.1.1', gw_inet='8.8.8.8')
        assert 'INTERNET' in result

    def test_wan_down(self):
        from core.classification import classify_network_status
        state = {'192.168.1.1': True, '1.1.1.1': False, '8.8.8.8': False}
        result = classify_network_status(state, {}, {},
            router_ip='192.168.1.1', gw_wan='1.1.1.1', gw_inet='8.8.8.8')
        assert 'WAN' in result

    def test_core_down(self):
        from core.classification import classify_network_status
        state = {'192.168.1.1': False, '1.1.1.1': False, '8.8.8.8': False}
        result = classify_network_status(state, {}, {},
            router_ip='192.168.1.1', gw_wan='1.1.1.1', gw_inet='8.8.8.8')
        assert 'CORE DOWN' in result


class TestNetwatchState:
    """Test netwatch state dictionaries."""

    def test_state_dict_type(self):
        from monitor.netwatch import _netwatch_state
        assert isinstance(_netwatch_state, dict)

    def test_fail_dict_type(self):
        from monitor.netwatch import _netwatch_fail
        assert isinstance(_netwatch_fail, dict)

    def test_recovery_up_since_dict_type(self):
        from monitor.netwatch import _netwatch_up_since
        assert isinstance(_netwatch_up_since, dict)

    def test_fail_counter_mechanics(self):
        from monitor.netwatch import _netwatch_fail
        host = '_test_host_counter'
        _netwatch_fail[host] = 0
        _netwatch_fail[host] += 1
        assert _netwatch_fail[host] == 1
        _netwatch_fail[host] = 0  # Reset on UP
        assert _netwatch_fail[host] == 0
        # Cleanup
        del _netwatch_fail[host]

    @pytest.mark.asyncio
    async def test_cleanup_stale_hosts_closes_incident_and_clears_ack(self):
        from monitor import netwatch as nw

        # Snapshot state awal agar tidak bocor ke test lain
        orig_state = dict(nw._netwatch_state)
        orig_fail = dict(nw._netwatch_fail)
        orig_down = dict(nw._netwatch_time_down)
        orig_dbid = dict(nw._netwatch_db_id)
        orig_recovery = dict(nw._netwatch_recovery)
        orig_up_since = dict(nw._netwatch_up_since)

        stale = "192.168.3.250:3306"
        keep = "192.168.3.1"
        try:
            nw._netwatch_state.clear()
            nw._netwatch_fail.clear()
            nw._netwatch_time_down.clear()
            nw._netwatch_db_id.clear()
            nw._netwatch_recovery.clear()
            nw._netwatch_up_since.clear()

            nw._netwatch_state[stale] = False
            nw._netwatch_fail[stale] = 7
            nw._netwatch_time_down[stale] = "dummy"
            nw._netwatch_db_id[stale] = 123
            nw._netwatch_recovery[stale] = 0
            nw._netwatch_up_since[stale] = "dummy"

            nw._netwatch_state[keep] = True
            nw._netwatch_fail[keep] = 0
            nw._netwatch_time_down[keep] = None
            nw._netwatch_recovery[keep] = 0
            nw._netwatch_up_since[keep] = None

            with patch('monitor.netwatch.database.log_incident_up') as mock_up, \
                 patch('monitor.netwatch.acknowledge_alert') as mock_ack:
                await nw._cleanup_stale_hosts([keep])
                mock_up.assert_called_once_with(stale)
                mock_ack.assert_called_once_with(f"down_{stale}")

            assert stale not in nw._netwatch_state
            assert stale not in nw._netwatch_fail
            assert stale not in nw._netwatch_time_down
            assert stale not in nw._netwatch_db_id
            assert stale not in nw._netwatch_recovery
            assert stale not in nw._netwatch_up_since
            assert keep in nw._netwatch_state
        finally:
            nw._netwatch_state.clear()
            nw._netwatch_state.update(orig_state)
            nw._netwatch_fail.clear()
            nw._netwatch_fail.update(orig_fail)
            nw._netwatch_time_down.clear()
            nw._netwatch_time_down.update(orig_down)
            nw._netwatch_db_id.clear()
            nw._netwatch_db_id.update(orig_dbid)
            nw._netwatch_recovery.clear()
            nw._netwatch_recovery.update(orig_recovery)
            nw._netwatch_up_since.clear()
            nw._netwatch_up_since.update(orig_up_since)

    @pytest.mark.asyncio
    async def test_api_unavailable_writes_unknown_state_without_red_alerts(self, tmp_path, monkeypatch):
        from monitor import netwatch as nw

        orig_flag = nw._api_unavailable_active
        orig_since = nw._api_unavailable_since
        orig_hash = nw._last_state_hash
        try:
            nw._api_unavailable_active = False
            nw._api_unavailable_since = None
            nw._last_state_hash = None
            monkeypatch.setattr(nw.config, "DATA_DIR", tmp_path)
            monkeypatch.setattr(nw.config, "MIKROTIK_IP", "192.168.3.1")
            monkeypatch.setattr(nw.config, "GW_WAN", "192.168.1.1")
            monkeypatch.setattr(nw.config, "GW_INET", "1.1.1.1")
            monkeypatch.setattr(nw.config, "SERVERS_FALLBACK", {})
            monkeypatch.setattr(nw.config, "APS_FALLBACK", {})
            monkeypatch.setattr(nw.config, "TCP_SERVICES", [])
            monkeypatch.setattr(nw.config, "NETWATCH_INTERVAL", 1)
            monkeypatch.setattr(nw.config, "reload_runtime_overrides", lambda min_interval=10: None)
            monkeypatch.setattr(nw.config, "reload_router_env", lambda min_interval=10: None)

            with patch('monitor.netwatch.pool.connection_diagnostics', return_value={
                'healthy': False,
                'last_error': 'login failed',
                'fail_count': 2,
                'backoff_seconds': 5.0,
            }), patch('monitor.netwatch.kirim_ke_semua_admin', new_callable=AsyncMock) as mock_send, \
                 patch('monitor.netwatch.asyncio.sleep', new_callable=AsyncMock, side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await nw.task_monitor_netwatch()

            state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
            assert state["api_connected"] is False
            assert "API UNAVAILABLE" in state["kategori"]
            assert all(v is None for v in state["hosts"].values())
            assert state["api_unavailable_since"]
            mock_send.assert_awaited_once()
        finally:
            nw._api_unavailable_active = orig_flag
            nw._api_unavailable_since = orig_since
            nw._last_state_hash = orig_hash


class TestUptimeParsing:
    """Test uptime string parsing (inline in checks.py cek_uptime_anomaly)."""

    def _parse_uptime(self, uptime_str):
        """Mirror the uptime parsing logic from cek_uptime_anomaly."""
        total_seconds = 0
        current = ''
        for ch in uptime_str:
            if ch.isdigit():
                current += ch
            elif ch == 'w':
                total_seconds += int(current) * 604800
                current = ''
            elif ch == 'd':
                total_seconds += int(current) * 86400
                current = ''
            elif ch == 'h':
                total_seconds += int(current) * 3600
                current = ''
            elif ch == 'm':
                total_seconds += int(current) * 60
                current = ''
            elif ch == 's':
                total_seconds += int(current)
                current = ''
        return total_seconds

    def test_minutes_seconds(self):
        assert self._parse_uptime("5m30s") == 330

    def test_hours(self):
        assert self._parse_uptime("1h") == 3600

    def test_days_hours_minutes(self):
        assert self._parse_uptime("1d2h3m") == 93780

    def test_weeks(self):
        assert self._parse_uptime("1w") == 604800
        assert self._parse_uptime("2w3d") == 1468800

    def test_full_format(self):
        assert self._parse_uptime("2w3d5h10m30s") == 1487430

    def test_empty_string(self):
        assert self._parse_uptime("") == 0


class TestNetwatchHelpers:
    def test_api_error_hint_variants(self):
        from monitor import netwatch as nw

        assert "user/password" in nw._api_error_hint("invalid user name or password (6)")
        assert "Sesi API invalid" in nw._api_error_hint("not logged in")
        assert "konektivitas" in nw._api_error_hint("connection timed out")
        assert "menutup koneksi" in nw._api_error_hint("connection unexpectedly closed")
        assert "allow-list IP service API" in nw._api_error_hint("other")

    def test_dns_label_prefers_domain_list(self, monkeypatch):
        from monitor import netwatch as nw
        monkeypatch.setattr(nw.config, "DNS_CHECK_DOMAINS", ["a.com", "b.com", "c.com", "d.com"])
        assert nw._dns_label() == "a.com, b.com, c.com"

    @pytest.mark.asyncio
    async def test_dns_check_uses_router_ping_before_local_resolver(self, monkeypatch):
        from monitor import netwatch as nw

        monkeypatch.setattr(nw.asyncio, "to_thread", AsyncMock(return_value={"received": 1}))
        result = await nw._dns_check(["example.com"], timeout=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_dns_check_falls_back_to_local_resolver(self, monkeypatch):
        from monitor import netwatch as nw

        async def fake_to_thread(_func, *_args, **_kwargs):
            return {"received": 0}

        class FakeLoop:
            async def getaddrinfo(self, *_args, **_kwargs):
                return [(None, None, None, None, ("1.1.1.1", 0))]

        monkeypatch.setattr(nw.asyncio, "to_thread", fake_to_thread)
        monkeypatch.setattr(nw.asyncio, "get_event_loop", lambda: FakeLoop())
        result = await nw._dns_check(["example.com"], timeout=1)
        assert result is True

    def test_static_monitored_hosts_deduplicated(self, monkeypatch):
        from monitor import netwatch as nw
        monkeypatch.setattr(nw.config, "MIKROTIK_IP", "192.168.3.1")
        monkeypatch.setattr(nw.config, "GW_WAN", "192.168.1.1")
        monkeypatch.setattr(nw.config, "GW_INET", "1.1.1.1")
        monkeypatch.setattr(nw.config, "SERVERS_FALLBACK", {"SIMRS": "192.168.3.10"})
        monkeypatch.setattr(nw.config, "APS_FALLBACK", {"AP1": "192.168.3.20"})
        monkeypatch.setattr(nw.config, "CRITICAL_DEVICES_FALLBACK", {"SIMRS": "192.168.3.10"})
        monkeypatch.setattr(nw.config, "TCP_SERVICES", [{"ip": "192.168.3.10", "port": 443}])
        hosts = nw._static_monitored_hosts()
        assert "DNS_Resolv" in hosts
        assert hosts.count("192.168.3.10") == 1

    def test_build_state_dump_shape(self):
        from monitor import netwatch as nw
        state = nw._build_state_dump("ok", {"1.1.1.1": True}, {"1.1.1.1": 0}, api_connected=False, api_error="x")
        assert "last_update" in state
        assert state["hosts"]["1.1.1.1"] is True
        assert state["api_connected"] is False
        assert state["monitor_degraded"] is False

    def test_build_state_dump_can_mark_monitor_degraded(self):
        from monitor import netwatch as nw
        state = nw._build_state_dump(
            "degraded",
            {"1.1.1.1": True},
            {"1.1.1.1": 0},
            monitor_degraded=True,
            degraded_reason="timeout",
        )
        assert state["monitor_degraded"] is True
        assert state["degraded_reason"] == "timeout"

    @pytest.mark.asyncio
    async def test_persist_state_dump_writes_and_hashes(self, tmp_path, monkeypatch):
        from monitor import netwatch as nw
        orig_hash = nw._last_state_hash
        try:
            nw._last_state_hash = None
            monkeypatch.setattr(nw.config, "DATA_DIR", tmp_path)
            state = nw._build_state_dump("ok", {"1.1.1.1": True}, {"1.1.1.1": 0})
            await nw._persist_state_dump(state)
            p = tmp_path / "state.json"
            assert p.exists()
            first = p.read_text(encoding="utf-8")
            await nw._persist_state_dump(state)
            second = p.read_text(encoding="utf-8")
            assert first == second
        finally:
            nw._last_state_hash = orig_hash

    def test_clear_false_down_alerts_ignores_ack_errors(self, monkeypatch):
        from monitor import netwatch as nw

        orig_state = dict(nw._netwatch_state)
        try:
            nw._netwatch_state.clear()
            nw._netwatch_state.update({"192.168.3.10": False})
            monkeypatch.setattr(nw, "_static_monitored_hosts", lambda: ["192.168.3.1"])

            calls = []

            def fake_ack(key):
                calls.append(key)
                if key == "down_192.168.3.1":
                    raise RuntimeError("boom")

            monkeypatch.setattr(nw, "acknowledge_alert", fake_ack)
            nw._clear_false_down_alerts()

            assert "down_192.168.3.10" in calls
            assert "down_192.168.3.1" in calls
        finally:
            nw._netwatch_state.clear()
            nw._netwatch_state.update(orig_state)

    def test_generate_snapshot_success_and_failure(self, monkeypatch):
        from monitor import netwatch as nw
        nw._snapshot_cache["ts"] = 0.0
        nw._snapshot_cache["value"] = ""
        monkeypatch.setattr(nw, "get_status", lambda: {"cpu": 10, "ram_total": 1024 * 1024 * 256, "ram_free": 1024 * 1024 * 200})
        monkeypatch.setattr(nw, "get_interfaces", lambda: [
            {"name": "ether1", "rx_error": 1, "tx_error": 2},
            {"name": "bridge", "rx_error": 0, "tx_error": 0},
        ])
        monkeypatch.setattr(nw, "get_dhcp_usage_count", lambda: 30)
        monkeypatch.setattr(nw.config, "DHCP_POOL_SIZE", 60)
        monkeypatch.setattr(nw.config, "WAN_IFACE_KEYWORDS", ["ether1"])
        monkeypatch.setattr(nw.config, "LAN_IFACE_KEYWORDS", ["bridge"])

        ok = nw._generate_snapshot()
        assert "CPU:" in ok
        assert "DHCP:" in ok

        nw._snapshot_cache["ts"] = 0.0
        nw._snapshot_cache["value"] = ""
        monkeypatch.setattr(nw, "get_status", lambda: (_ for _ in ()).throw(Exception("boom")))
        fail = nw._generate_snapshot()
        assert "Snapshot gagal" in fail

    def test_generate_snapshot_reuses_recent_cache(self, monkeypatch):
        from monitor import netwatch as nw

        nw._snapshot_cache["ts"] = 100.0
        nw._snapshot_cache["value"] = "cached snapshot"
        monkeypatch.setattr(nw.datetime, "datetime", type("FakeDt", (), {
            "now": staticmethod(lambda: type("FakeNow", (), {"timestamp": lambda self: 110.0})())
        }))
        monkeypatch.setattr(nw, "_build_snapshot_now", lambda: (_ for _ in ()).throw(AssertionError("should use cache")))

        assert nw._generate_snapshot(cache_ttl=30) == "cached snapshot"

    @pytest.mark.asyncio
    async def test_full_timeout_enters_degraded_without_marking_hosts_down(self, tmp_path, monkeypatch):
        from monitor import netwatch as nw

        orig_state = dict(nw._netwatch_state)
        orig_fail = dict(nw._netwatch_fail)
        orig_timeout_hits = nw._netwatch_timeout_hits
        orig_api_flag = nw._api_unavailable_active
        orig_hash = nw._last_state_hash
        try:
            nw._netwatch_state.clear()
            nw._netwatch_fail.clear()
            nw._netwatch_state.update({"192.168.3.1": True, "1.1.1.1": True})
            nw._netwatch_fail.update({"192.168.3.1": 0, "1.1.1.1": 0})
            nw._netwatch_timeout_hits = 0
            nw._api_unavailable_active = False
            nw._last_state_hash = None

            monkeypatch.setattr(nw.config, "DATA_DIR", tmp_path)
            monkeypatch.setattr(nw.config, "MIKROTIK_IP", "192.168.3.1")
            monkeypatch.setattr(nw.config, "GW_WAN", "192.168.1.1")
            monkeypatch.setattr(nw.config, "GW_INET", "1.1.1.1")
            monkeypatch.setattr(nw.config, "TCP_SERVICES", [])
            monkeypatch.setattr(nw.config, "NETWATCH_INTERVAL", 1)
            monkeypatch.setattr(nw.config, "NETWATCH_CYCLE_TIMEOUT_THRESHOLD", 1)
            monkeypatch.setattr(nw.config, "NETWATCH_DEGRADED_ALERT_COOLDOWN_SEC", 30)
            monkeypatch.setattr(nw.config, "reload_runtime_overrides", lambda min_interval=10: None)
            monkeypatch.setattr(nw.config, "reload_router_env", lambda min_interval=10: None)

            async def fake_with_timeout(_coro, timeout=30, default=None, **kwargs):
                if default is not None:
                    if hasattr(_coro, "cancel"):
                        _coro.cancel()
                    elif hasattr(_coro, "close"):
                        _coro.close()
                    return default
                if hasattr(_coro, "cancel"):
                    _coro.cancel()
                elif hasattr(_coro, "close"):
                    _coro.close()
                return None

            with patch('monitor.netwatch.pool.connection_diagnostics', return_value={
                'healthy': True,
                'last_error': '',
            }), patch('monitor.netwatch.get_monitored_aps', return_value={}), \
                 patch('monitor.netwatch.get_monitored_servers', return_value={}), \
                 patch('monitor.netwatch.get_monitored_critical_devices', return_value={}), \
                 patch('monitor.netwatch.get_default_gateway', return_value='192.168.1.1'), \
                 patch('monitor.netwatch.with_timeout', side_effect=fake_with_timeout), \
                 patch('monitor.netwatch.kirim_ke_semua_admin', new_callable=AsyncMock) as mock_send, \
                 patch('monitor.netwatch.asyncio.sleep', new_callable=AsyncMock, side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await nw.task_monitor_netwatch()

            state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
            assert state["monitor_degraded"] is True
            assert state["hosts"]["192.168.3.1"] is True
            assert state["hosts"]["1.1.1.1"] is True
            assert "NETWATCH DEGRADED" in state["kategori"]
            mock_send.assert_awaited_once()
        finally:
            nw._netwatch_state.clear()
            nw._netwatch_state.update(orig_state)
            nw._netwatch_fail.clear()
            nw._netwatch_fail.update(orig_fail)
            nw._netwatch_timeout_hits = orig_timeout_hits
            nw._api_unavailable_active = orig_api_flag
            nw._last_state_hash = orig_hash

    @pytest.mark.asyncio
    async def test_task_netwatch_sends_api_recovery_and_host_recovery(self, tmp_path, monkeypatch):
        from monitor import netwatch as nw

        orig_state = dict(nw._netwatch_state)
        orig_fail = dict(nw._netwatch_fail)
        orig_down = dict(nw._netwatch_time_down)
        orig_recovery = dict(nw._netwatch_recovery)
        orig_up_since = dict(nw._netwatch_up_since)
        orig_reconciled = set(nw._netwatch_reconciled_hosts)
        orig_api_flag = nw._api_unavailable_active
        orig_api_since = nw._api_unavailable_since
        orig_hash = nw._last_state_hash
        try:
            host = "192.168.3.10"
            nw._netwatch_state.clear()
            nw._netwatch_fail.clear()
            nw._netwatch_time_down.clear()
            nw._netwatch_recovery.clear()
            nw._netwatch_up_since.clear()
            nw._netwatch_reconciled_hosts.clear()

            nw._netwatch_state.update({
                "192.168.3.1": True,
                "192.168.1.1": True,
                "1.1.1.1": True,
                host: False,
                "DNS_Resolv": True,
            })
            nw._netwatch_fail.update({
                "192.168.3.1": 0,
                "192.168.1.1": 0,
                "1.1.1.1": 0,
                host: 3,
                "DNS_Resolv": 0,
            })
            nw._netwatch_time_down[host] = nw.datetime.datetime.now() - nw.datetime.timedelta(minutes=2)
            nw._netwatch_recovery.update({
                "192.168.3.1": 0,
                "192.168.1.1": 0,
                "1.1.1.1": 0,
                host: 0,
                "DNS_Resolv": 0,
            })
            nw._netwatch_up_since.update({
                "192.168.3.1": None,
                "192.168.1.1": None,
                "1.1.1.1": None,
                host: None,
                "DNS_Resolv": None,
            })
            nw._api_unavailable_active = True
            nw._api_unavailable_since = nw.datetime.datetime.now() - nw.datetime.timedelta(minutes=5, seconds=7)
            nw._last_state_hash = None

            monkeypatch.setattr(nw.config, "DATA_DIR", tmp_path)
            monkeypatch.setattr(nw.config, "MIKROTIK_IP", "192.168.3.1")
            monkeypatch.setattr(nw.config, "GW_WAN", "192.168.1.1")
            monkeypatch.setattr(nw.config, "GW_INET", "1.1.1.1")
            monkeypatch.setattr(nw.config, "SERVERS_FALLBACK", {})
            monkeypatch.setattr(nw.config, "APS_FALLBACK", {})
            monkeypatch.setattr(nw.config, "CRITICAL_DEVICES_FALLBACK", {})
            monkeypatch.setattr(nw.config, "TCP_SERVICES", [])
            monkeypatch.setattr(nw.config, "NETWATCH_INTERVAL", 1)
            monkeypatch.setattr(nw.config, "PING_FAIL_THRESHOLD", 3)
            monkeypatch.setattr(nw.config, "RECOVERY_CONFIRM_COUNT", 1)
            monkeypatch.setattr(nw.config, "RECOVERY_MIN_UP_SECONDS", 0)
            monkeypatch.setattr(nw.config, "CRITICAL_RECOVERY_CONFIRM_COUNT", 3)
            monkeypatch.setattr(nw.config, "CRITICAL_RECOVERY_MIN_UP_SECONDS", 180)
            monkeypatch.setattr(nw.config, "reload_runtime_overrides", lambda min_interval=10: None)
            monkeypatch.setattr(nw.config, "reload_router_env", lambda min_interval=10: None)
            monkeypatch.setattr(nw, "classify_network_status", lambda *a, **k: "NORMAL")
            monkeypatch.setattr(nw, "classify_host_short", lambda *a, **k: "SERVER ISSUE")
            monkeypatch.setattr(nw, "_generate_snapshot", lambda: "snapshot")

            async def fake_with_timeout(_coro, timeout=30, default=None, log_key=None, **kwargs):
                if hasattr(_coro, "close"):
                    _coro.close()
                if log_key == "netwatch:get_monitored_aps":
                    return {}
                if log_key == "netwatch:get_monitored_servers":
                    return {"SERVER IMS": host}
                if log_key == "netwatch:get_monitored_critical_devices":
                    return {}
                if log_key == "netwatch:get_default_gateway":
                    return None
                if log_key == "netwatch:all_checks":
                    return (
                        [
                            (("Router", "192.168.3.1", "CORE"), True),
                            (("WAN_GW", "192.168.1.1", "WAN"), True),
                            (("Internet", "1.1.1.1", "INET"), True),
                            (("SERVER IMS", host, "SERVER"), True),
                        ],
                        [],
                        ("DNS_Resolv", True),
                    )
                return default

            send_mock = AsyncMock()
            ack_mock = MagicMock()
            log_up = MagicMock(return_value=True)
            monkeypatch.setattr(nw, "with_timeout", fake_with_timeout)
            monkeypatch.setattr(nw, "kirim_ke_semua_admin", send_mock)
            monkeypatch.setattr(nw, "acknowledge_alert", ack_mock)
            monkeypatch.setattr(nw.pool, "connection_diagnostics", lambda: {"healthy": True, "last_error": ""})
            monkeypatch.setattr(nw.database, "log_incident_up", log_up)

            async def stop_sleep(_seconds):
                raise asyncio.CancelledError()

            monkeypatch.setattr(nw.asyncio, "sleep", stop_sleep)

            with pytest.raises(asyncio.CancelledError):
                await nw.task_monitor_netwatch()

            messages = [call.args[0] for call in send_mock.await_args_list]
            assert any("MIKROTIK API RECOVERY" in msg for msg in messages)
            assert any("Durasi gangguan API:" in msg for msg in messages)
            assert any("RECOVERY" in msg and host in msg for msg in messages)
            ack_mock.assert_any_call("api_unavailable")
            ack_mock.assert_any_call(f"down_{host}")
            assert nw._netwatch_state[host] is True
            assert (tmp_path / "state.json").exists()
            assert log_up.call_count >= 2
        finally:
            nw._netwatch_state.clear()
            nw._netwatch_state.update(orig_state)
            nw._netwatch_fail.clear()
            nw._netwatch_fail.update(orig_fail)
            nw._netwatch_time_down.clear()
            nw._netwatch_time_down.update(orig_down)
            nw._netwatch_recovery.clear()
            nw._netwatch_recovery.update(orig_recovery)
            nw._netwatch_up_since.clear()
            nw._netwatch_up_since.update(orig_up_since)
            nw._netwatch_reconciled_hosts.clear()
            nw._netwatch_reconciled_hosts.update(orig_reconciled)
            nw._api_unavailable_active = orig_api_flag
            nw._api_unavailable_since = orig_api_since
            nw._last_state_hash = orig_hash
