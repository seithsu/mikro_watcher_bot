# ============================================
# TEST_HANDLERS_JOBS - Tests for handlers/jobs.py
# Daily report & auto backup scheduled jobs
# ============================================

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestDailyReport:
    """Test daily_report job."""

    @pytest.mark.asyncio
    @patch('handlers.jobs.database')
    @patch('handlers.jobs.read_state_json')
    @patch('handlers.jobs.get_default_gateway', return_value='192.168.1.1')
    @patch('handlers.jobs.get_monitored_servers', return_value={})
    @patch('handlers.jobs.get_monitored_critical_devices', return_value={})
    @patch('handlers.jobs.get_monitored_aps', return_value={})
    @patch('handlers.jobs.get_interfaces', return_value=[])
    @patch('handlers.jobs.get_dhcp_usage_count', return_value=10)
    @patch('handlers.jobs.get_status')
    async def test_daily_report_runs(self, mock_status, mock_dhcp, mock_ifaces,
                                      mock_aps, mock_critical, mock_servers, mock_gw, mock_state, mock_db):
        from handlers.jobs import daily_report

        mock_status.return_value = {
            'board': 'hAP ac²', 'version': '7.14', 'uptime': '10d5h',
            'cpu': '15', 'ram_total': '268435456', 'ram_free': '134217728',
            'disk_total': '16777216', 'disk_free': '8388608',
        }
        mock_state.return_value = {'kategori': '🟢 NORMAL', 'hosts': {}}
        mock_db.get_stats_today.return_value = 0

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await daily_report(context)
        context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.jobs.logger')
    @patch('handlers.jobs.database')
    @patch('handlers.jobs.read_state_json', side_effect=Exception("state-fail"))
    @patch('handlers.jobs.get_default_gateway', side_effect=Exception("gw-fail"))
    @patch('handlers.jobs.get_active_critical_device_names', return_value=['KOMP-UNKNOWN'])
    @patch('handlers.jobs.get_monitored_critical_devices', return_value={})
    @patch('handlers.jobs.get_monitored_servers', side_effect=Exception("server-fail"))
    @patch('handlers.jobs.get_monitored_aps', return_value={})
    @patch('handlers.jobs.get_interfaces', return_value=[])
    @patch('handlers.jobs.get_dhcp_usage_count', side_effect=Exception("dhcp-fail"))
    @patch('handlers.jobs.get_status')
    async def test_daily_report_handles_fallbacks_and_send_failure(
        self,
        mock_status,
        mock_dhcp,
        mock_ifaces,
        mock_aps,
        mock_servers,
        mock_critical,
        mock_active_critical,
        mock_gw,
        mock_state,
        mock_db,
        mock_logger,
        monkeypatch,
    ):
        from handlers.jobs import daily_report

        mock_status.return_value = {
            'board': 'hEX',
            'version': '7.15',
            'uptime': '1d',
            'cpu': '5',
            'cpu_freq': 880,
            'cpu_count': 4,
            'cpu_temp': 38,
            'voltage': '243',
            'ram_total': '268435456',
            'ram_free': '134217728',
            'disk_total': '16777216',
            'disk_free': '8388608',
        }
        mock_db.get_stats_today.side_effect = Exception("db-fail")
        monkeypatch.setattr('handlers.jobs.cfg.ADMIN_IDS', [111], raising=False)
        monkeypatch.setattr('handlers.jobs.cfg.DHCP_POOL_SIZE', 60, raising=False)
        monkeypatch.setattr('handlers.jobs.cfg.GW_WAN', '192.168.1.1', raising=False)
        monkeypatch.setattr('handlers.jobs.cfg.GW_INET', '1.1.1.1', raising=False)
        monkeypatch.setattr('handlers.jobs.cfg.MIKROTIK_IP', '192.168.3.1', raising=False)
        monkeypatch.setattr('handlers.jobs.cfg.INSTITUTION_NAME', 'RSIA', raising=False)
        monkeypatch.setattr('handlers.jobs.cfg.MONITOR_IGNORE_IFACE', [], raising=False)

        context = MagicMock()
        context.bot.send_message = AsyncMock(side_effect=Exception("telegram-fail"))

        await daily_report(context)

        context.bot.send_message.assert_called_once()
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.jobs.logger')
    @patch('handlers.jobs.get_status', side_effect=Exception("router-fail"))
    async def test_daily_report_outer_error_logged(self, mock_status, mock_logger):
        from handlers.jobs import daily_report

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await daily_report(context)

        mock_logger.error.assert_called()


class TestAutoBackup:
    """Test auto_backup job."""

    @pytest.mark.asyncio
    @patch('handlers.jobs.os.remove')
    @patch('handlers.jobs.export_router_backup', return_value=None)
    @patch('handlers.jobs.export_router_backup_ftp', return_value="backup_export.rsc")
    async def test_auto_backup_ftp_success(self, mock_ftp, mock_export, mock_remove):
        from handlers.jobs import auto_backup

        context = MagicMock()
        context.bot.send_document = AsyncMock()

        # Mock open for file
        from unittest.mock import mock_open
        with patch('builtins.open', mock_open(read_data=b"config data")):
            await auto_backup(context)

    @pytest.mark.asyncio
    @patch('handlers.jobs.export_router_backup', side_effect=Exception("fail"))
    @patch('handlers.jobs.export_router_backup_ftp', side_effect=Exception("fail"))
    async def test_auto_backup_failure_no_crash(self, mock_ftp, mock_export):
        from handlers.jobs import auto_backup

        context = MagicMock()
        context.bot.send_document = AsyncMock()
        context.bot.send_message = AsyncMock()

        # Should not raise
        await auto_backup(context)

    @pytest.mark.asyncio
    @patch('handlers.jobs.os.remove')
    @patch('handlers.jobs.export_router_backup', return_value="backup_api.rsc")
    @patch('handlers.jobs.export_router_backup_ftp', side_effect=Exception("ftp-fail"))
    async def test_auto_backup_fallback_api_success(self, mock_ftp, mock_export, mock_remove, monkeypatch):
        from handlers.jobs import auto_backup

        monkeypatch.setattr('handlers.jobs.cfg.ADMIN_IDS', [111], raising=False)
        context = MagicMock()
        context.bot.send_document = AsyncMock()

        from unittest.mock import mock_open
        with patch('builtins.open', mock_open(read_data=b"config data")):
            await auto_backup(context)

        context.bot.send_document.assert_called_once()
        mock_ftp.assert_not_called()
        mock_remove.assert_called_once_with("backup_api.rsc")

    @pytest.mark.asyncio
    @patch('handlers.jobs.logger')
    @patch('handlers.jobs.os.remove', side_effect=OSError("locked"))
    @patch('handlers.jobs.export_router_backup', return_value=None)
    @patch('handlers.jobs.export_router_backup_ftp', return_value="backup_export.rsc")
    async def test_auto_backup_send_document_and_remove_failures_are_logged(self, mock_ftp, mock_export, mock_remove, mock_logger, monkeypatch):
        from handlers.jobs import auto_backup

        monkeypatch.setattr('handlers.jobs.cfg.ADMIN_IDS', [111], raising=False)
        context = MagicMock()
        context.bot.send_document = AsyncMock(side_effect=Exception("telegram-fail"))

        from unittest.mock import mock_open
        with patch('builtins.open', mock_open(read_data=b"config data")):
            await auto_backup(context)

        mock_logger.warning.assert_called()
        mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    @patch('handlers.jobs.export_router_backup', return_value=None)
    @patch('handlers.jobs.export_router_backup_ftp', return_value=None)
    async def test_auto_backup_no_filename_does_nothing(self, mock_ftp, mock_export):
        from handlers.jobs import auto_backup

        context = MagicMock()
        context.bot.send_document = AsyncMock()

        await auto_backup(context)

        context.bot.send_document.assert_not_called()
