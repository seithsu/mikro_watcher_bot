# ============================================
# TEST_CHECKS - Tests for monitor/checks.py
# CPU, RAM, disk, uptime anomaly, VPN, interface
# ============================================

import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock


class TestCekCpuRam:
    """Test fungsi cek_cpu_ram."""

    def setup_method(self):
        import monitor.checks
        monitor.checks._last_alerts['cpu'] = False
        monitor.checks._last_alerts['ram'] = False

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_cpu_normal_no_alert(self, mock_send):
        from monitor.checks import cek_cpu_ram
        info = {'cpu': '30', 'ram_total': '1073741824', 'ram_free': '536870912', 'uptime': '1d'}
        cpu, ram = await cek_cpu_ram(info)
        assert cpu == 30
        assert 40 < ram < 60  # ~50%
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_cpu_high_triggers_alert(self, mock_send):
        from monitor.checks import cek_cpu_ram
        import monitor.checks
        monitor.checks._last_alerts['cpu'] = False

        info = {'cpu': '95', 'ram_total': '1073741824', 'ram_free': '536870912', 'uptime': '1d'}
        await cek_cpu_ram(info)
        assert monitor.checks._last_alerts['cpu'] is True
        mock_send.assert_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_cpu_recovery(self, mock_send):
        from monitor.checks import cek_cpu_ram
        import monitor.checks
        monitor.checks._last_alerts['cpu'] = True  # Was high

        info = {'cpu': '20', 'ram_total': '1073741824', 'ram_free': '536870912', 'uptime': '1d'}
        await cek_cpu_ram(info)
        assert monitor.checks._last_alerts['cpu'] is False
        mock_send.assert_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_ram_high_triggers_alert(self, mock_send):
        from monitor.checks import cek_cpu_ram
        import monitor.checks
        monitor.checks._last_alerts['ram'] = False

        # RAM 95% used: total=1GB, free=50MB
        info = {'cpu': '10', 'ram_total': '1073741824', 'ram_free': '52428800', 'uptime': '1d'}
        await cek_cpu_ram(info)
        assert monitor.checks._last_alerts['ram'] is True

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_no_duplicate_cpu_alert(self, mock_send):
        """Tidak kirim alert jika sudah alert sebelumnya."""
        from monitor.checks import cek_cpu_ram
        import monitor.checks
        monitor.checks._last_alerts['cpu'] = True  # Already alerted

        info = {'cpu': '95', 'ram_total': '1073741824', 'ram_free': '536870912', 'uptime': '1d'}
        await cek_cpu_ram(info)
        mock_send.assert_not_called()


class TestCekDisk:
    """Test cek_disk function."""

    def setup_method(self):
        import monitor.checks
        monitor.checks._last_alerts['disk'] = False

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_disk_normal(self, mock_send):
        from monitor.checks import cek_disk
        info = {'disk_total': '134217728', 'disk_free': '67108864'}  # 50%
        await cek_disk(info)
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_disk_high(self, mock_send):
        from monitor.checks import cek_disk
        import monitor.checks
        info = {'disk_total': '134217728', 'disk_free': '6710886'}  # >95%
        await cek_disk(info)
        assert monitor.checks._last_alerts['disk'] is True

    @pytest.mark.asyncio
    @patch('monitor.checks._save_state')
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_disk_change_persists_state(self, mock_send, mock_save_state):
        from monitor.checks import cek_disk
        import monitor.checks
        monitor.checks._last_alerts['disk'] = False
        info = {'disk_total': '134217728', 'disk_free': '6710886'}
        await cek_disk(info)
        mock_save_state.assert_called_once()

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_disk_recovery_and_invalid_total(self, mock_send):
        from monitor.checks import cek_disk
        import monitor.checks

        monitor.checks._last_alerts['disk'] = True
        await cek_disk({'disk_total': '0', 'disk_free': '0'})
        mock_send.assert_not_called()

        await cek_disk({'disk_total': '134217728', 'disk_free': '67108864'})
        assert monitor.checks._last_alerts['disk'] is False
        assert mock_send.await_count == 1

    @pytest.mark.asyncio
    @patch('monitor.checks.database.record_metric', side_effect=RuntimeError("db-fail"))
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_disk_metric_failure_and_outer_error(self, mock_send, _mock_metric):
        from monitor.checks import cek_disk

        await cek_disk({'disk_total': 'bad', 'disk_free': '1'})
        mock_send.assert_not_called()


class TestFirmwareAndState:
    def test_state_load_save_helpers(self, tmp_path, monkeypatch):
        import monitor.checks as checks

        state_file = tmp_path / "monitor_state.json"
        monkeypatch.setattr(checks, "_STATE_FILE", state_file, raising=False)
        checks._last_alerts.update(
            {
                "cpu": True,
                "ram": False,
                "disk": True,
                "firmware_checked": True,
                "iface_down": {"ether2"},
                "vpn_down": {"vpn1"},
                "_initialized": True,
            }
        )

        checks._save_state()
        loaded = checks._load_state()
        assert loaded["cpu"] is True
        assert loaded["iface_down"] == {"ether2"}
        assert loaded["vpn_down"] == {"vpn1"}

        state_file.write_text("{bad json", encoding="utf-8")
        loaded = checks._load_state()
        assert loaded["cpu"] is False

    def test_save_state_if_changed(self):
        import monitor.checks as checks

        snapshot = checks._state_snapshot()
        with patch("monitor.checks._save_state") as mock_save:
            checks._save_state_if_changed(snapshot)
            mock_save.assert_not_called()
            checks._last_alerts["cpu"] = not checks._last_alerts["cpu"]
            checks._save_state_if_changed(snapshot)
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_system_routerboard', return_value={
        "needs_upgrade": True,
        "board": "hEX",
        "current_firmware": "6.40.9",
        "upgrade_firmware": "6.49.10",
    })
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_firmware_alert_and_throttle(self, mock_send, _mock_rb):
        import monitor.checks
        from monitor.checks import cek_firmware

        monitor.checks._firmware_last_check = 0
        monitor.checks._last_alerts["firmware_checked"] = False
        await cek_firmware()
        assert monitor.checks._last_alerts["firmware_checked"] is True
        mock_send.assert_awaited_once()

        await cek_firmware()
        assert mock_send.await_count == 1

    @pytest.mark.asyncio
    @patch('monitor.checks.get_system_routerboard', return_value={"needs_upgrade": False})
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_firmware_clear_and_error_path(self, mock_send, _mock_rb):
        import monitor.checks
        from monitor.checks import cek_firmware

        monitor.checks._firmware_last_check = 0
        monitor.checks._last_alerts["firmware_checked"] = True
        await cek_firmware()
        assert monitor.checks._last_alerts["firmware_checked"] is False
        mock_send.assert_not_called()

        monitor.checks._firmware_last_check = 0
        with patch("monitor.checks.get_system_routerboard", side_effect=RuntimeError("rb-fail")):
            await cek_firmware()


class TestCekUptimeAnomaly:
    """Test restart detection."""

    def setup_method(self):
        import monitor.checks
        monitor.checks._last_uptime_seconds = None

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_first_run_no_alert(self, mock_send):
        from monitor.checks import cek_uptime_anomaly
        info = {'uptime': '5d3h20m'}
        await cek_uptime_anomaly(info)
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_normal_increase_no_alert(self, mock_send):
        import monitor.checks
        monitor.checks._last_uptime_seconds = 1000

        from monitor.checks import cek_uptime_anomaly
        info = {'uptime': '30m'}  # 1800s > 1000s
        await cek_uptime_anomaly(info)
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_restart_detected(self, mock_send):
        import monitor.checks
        monitor.checks._last_uptime_seconds = 86400  # 1 day

        from monitor.checks import cek_uptime_anomaly
        info = {'uptime': '2m30s'}  # 150s < 600s threshold
        await cek_uptime_anomaly(info)
        mock_send.assert_called()
        assert 'Restart' in mock_send.call_args[0][0]

    @pytest.mark.asyncio
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_uptime_parse_error_path(self, mock_send):
        from monitor.checks import cek_uptime_anomaly

        with patch("re.match", side_effect=RuntimeError("bad")):
            await cek_uptime_anomaly({"uptime": "1d"})
        mock_send.assert_not_called()


class TestCekInterface:
    """Test interface monitoring."""

    def setup_method(self):
        import monitor.checks
        monitor.checks._last_alerts['iface_down'] = set()
        monitor.checks._last_alerts['_initialized'] = False

    @pytest.mark.asyncio
    @patch('monitor.checks.get_interfaces')
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_first_run_init_only(self, mock_send, mock_ifaces):
        from monitor.checks import cek_interface
        import monitor.checks
        mock_ifaces.return_value = [
            {'name': 'ether1', 'enabled': True, 'running': True},
            {'name': 'ether2', 'enabled': True, 'running': False},
        ]
        await cek_interface()
        assert monitor.checks._last_alerts['_initialized'] is True
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch('monitor.checks._save_state')
    @patch('monitor.checks.get_interfaces')
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_first_run_persists_state(self, mock_send, mock_ifaces, mock_save_state):
        from monitor.checks import cek_interface
        import monitor.checks
        monitor.checks._last_alerts['iface_down'] = set()
        monitor.checks._last_alerts['_initialized'] = False
        mock_ifaces.return_value = [
            {'name': 'ether1', 'enabled': True, 'running': True},
            {'name': 'ether2', 'enabled': True, 'running': False},
        ]
        await cek_interface()
        mock_save_state.assert_called_once()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_interfaces')
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_newly_down_interface(self, mock_send, mock_ifaces):
        import monitor.checks
        monitor.checks._last_alerts['_initialized'] = True
        monitor.checks._last_alerts['iface_down'] = set()

        from monitor.checks import cek_interface
        mock_ifaces.return_value = [
            {'name': 'ether1', 'enabled': True, 'running': True},
            {'name': 'ether2', 'enabled': True, 'running': False},
        ]
        await cek_interface()
        mock_send.assert_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_interfaces')
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_ignore_interface_not_alerted(self, mock_send, mock_ifaces):
        import monitor.checks
        from monitor.checks import cek_interface

        monitor.checks._last_alerts['_initialized'] = True
        monitor.checks._last_alerts['iface_down'] = set()
        original_ignore = set(monitor.checks.cfg.MONITOR_IGNORE_IFACE)
        monitor.checks.cfg.MONITOR_IGNORE_IFACE = {'ether3'}
        mock_ifaces.return_value = [
            {'name': 'ether3', 'enabled': True, 'running': False},
        ]
        try:
            await cek_interface()
        finally:
            monitor.checks.cfg.MONITOR_IGNORE_IFACE = original_ignore

        mock_send.assert_not_called()


class TestCekVpnTunnels:
    """Test VPN tunnel monitoring."""

    def setup_method(self):
        import monitor.checks
        monitor.checks._last_alerts['vpn_down'] = set()
        monitor.checks._last_alerts['_initialized'] = True
        monitor.checks.cfg.MONITOR_VPN_ENABLED = True
        monitor.checks.cfg.MONITOR_VPN_IGNORE_NAMES = set()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_vpn_tunnels')
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_vpn_down_alert(self, mock_send, mock_vpn):
        from monitor.checks import cek_vpn_tunnels
        mock_vpn.return_value = [
            {'name': 'vpn-hq', 'disabled': False, 'running': False, 'type': 'l2tp', 'remote': '10.0.0.1'},
        ]
        await cek_vpn_tunnels()
        mock_send.assert_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_vpn_tunnels')
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_disabled_vpn_ignored(self, mock_send, mock_vpn):
        from monitor.checks import cek_vpn_tunnels
        mock_vpn.return_value = [
            {'name': 'vpn-old', 'disabled': True, 'running': False, 'type': 'pptp', 'remote': '10.0.0.2'},
        ]
        await cek_vpn_tunnels()
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_vpn_tunnels')
    @patch('monitor.checks.database.close_open_incidents_by_tag', return_value=1)
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_vpn_monitor_disabled(self, mock_send, mock_close_tag, mock_vpn):
        import monitor.checks
        from monitor.checks import cek_vpn_tunnels

        monitor.checks.cfg.MONITOR_VPN_ENABLED = False
        monitor.checks._last_alerts['vpn_down'] = {'vpn-hq'}
        mock_vpn.return_value = [
            {'name': 'vpn-hq', 'disabled': False, 'running': False, 'type': 'l2tp', 'remote': '10.0.0.1'},
        ]

        await cek_vpn_tunnels()

        mock_vpn.assert_not_called()
        mock_send.assert_not_called()
        mock_close_tag.assert_called_once_with("vpn", "monitor-disabled")
        assert monitor.checks._last_alerts['vpn_down'] == set()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_vpn_tunnels', return_value=[
        {'name': 'vpn-hq', 'disabled': False, 'running': False, 'type': 'l2tp', 'remote': '10.0.0.1'},
    ])
    @patch('monitor.checks.database.log_incident_down', side_effect=RuntimeError("db-fail"))
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_vpn_down_db_failure_suppressed(self, mock_send, _mock_down, _mock_vpn):
        import monitor.checks
        from monitor.checks import cek_vpn_tunnels

        monitor.checks._last_alerts['_initialized'] = True
        monitor.checks._last_alerts['vpn_down'] = set()
        await cek_vpn_tunnels()
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_vpn_tunnels', return_value=[
        {'name': 'vpn-hq', 'disabled': False, 'running': True, 'type': 'l2tp', 'remote': '10.0.0.1'},
    ])
    @patch('monitor.checks.database.log_incident_up', side_effect=RuntimeError("db-fail"))
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_vpn_recovery_db_failure_suppressed(self, mock_send, _mock_up, _mock_vpn):
        import monitor.checks
        from monitor.checks import cek_vpn_tunnels

        monitor.checks._last_alerts['_initialized'] = True
        monitor.checks._last_alerts['vpn_down'] = {'vpn-hq'}
        await cek_vpn_tunnels()
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_vpn_tunnels', side_effect=RuntimeError("vpn-fail"))
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_vpn_error_suppressed(self, mock_send, _mock_vpn):
        from monitor.checks import cek_vpn_tunnels

        await cek_vpn_tunnels()
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_vpn_tunnels', return_value=[])
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_vpn_empty_tunnel_list(self, mock_send, _mock_vpn):
        from monitor.checks import cek_vpn_tunnels

        await cek_vpn_tunnels()
        mock_send.assert_not_called()


class TestInterfaceExtras:
    @pytest.mark.asyncio
    @patch('monitor.checks.get_interfaces', side_effect=RuntimeError("iface-fail"))
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_interface_fetch_error(self, mock_send, _mock_ifaces):
        from monitor.checks import cek_interface

        await cek_interface()
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch('monitor.checks.get_interfaces')
    @patch('monitor.checks.kirim_ke_semua_admin', new_callable=AsyncMock)
    async def test_interface_recovery_alert(self, mock_send, mock_ifaces):
        import monitor.checks
        from monitor.checks import cek_interface

        monitor.checks._last_alerts['_initialized'] = True
        monitor.checks._last_alerts['iface_down'] = {'ether2'}
        mock_ifaces.return_value = [
            {'name': 'ether2', 'enabled': True, 'running': True},
        ]

        await cek_interface()
        mock_send.assert_awaited_once()
