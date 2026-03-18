# ============================================
# TEST_TOP_BW_ALERT - Tests for top bandwidth alert engine
# ============================================

import pytest
from unittest.mock import patch, AsyncMock


class TestTopBandwidthAlertEngine:
    def setup_method(self):
        import monitor.tasks as t
        t._top_bw_host_state.clear()
        t._alerted_hosts_traffic.clear()

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_warning_after_consecutive_hits(self, mock_send, monkeypatch):
        import monitor.tasks as t
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", True)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_TOP_N", 3)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_WARN_MBPS", 50)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CRIT_MBPS", 100)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CONSECUTIVE_HITS", 2)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_RECOVERY_HITS", 2)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_COOLDOWN_SEC", 900)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_TX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_RX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", [])

        data = [{"name": "PC-1", "rx_rate": 60_000_000, "tx_rate": 5_000_000}]
        await t._cek_per_host_traffic(data)
        await t._cek_per_host_traffic(data)

        assert mock_send.call_count == 1
        assert "TOP BW WARNING" in mock_send.call_args[0][0]
        assert "PC-1" in mock_send.call_args[0][0]

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_critical_escalation_bypasses_cooldown(self, mock_send, monkeypatch):
        import monitor.tasks as t
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", True)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_TOP_N", 3)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_WARN_MBPS", 50)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CRIT_MBPS", 100)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CONSECUTIVE_HITS", 1)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_RECOVERY_HITS", 2)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_COOLDOWN_SEC", 3600)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_TX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_RX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", [])

        warning_data = [{"name": "PC-2", "rx_rate": 55_000_000, "tx_rate": 0}]
        critical_data = [{"name": "PC-2", "rx_rate": 120_000_000, "tx_rate": 0}]

        await t._cek_per_host_traffic(warning_data)
        await t._cek_per_host_traffic(critical_data)

        assert mock_send.call_count == 2
        assert "TOP BW WARNING" in mock_send.call_args_list[0][0][0]
        assert "TOP BW CRITICAL" in mock_send.call_args_list[1][0][0]

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_warning_cooldown_prevents_spam(self, mock_send, monkeypatch):
        import monitor.tasks as t
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", True)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_TOP_N", 3)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_WARN_MBPS", 50)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CRIT_MBPS", 100)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CONSECUTIVE_HITS", 1)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_RECOVERY_HITS", 2)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_COOLDOWN_SEC", 3600)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_TX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_RX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", [])

        data = [{"name": "PC-3", "rx_rate": 70_000_000, "tx_rate": 0}]
        await t._cek_per_host_traffic(data)
        await t._cek_per_host_traffic(data)

        assert mock_send.call_count == 1
        assert "TOP BW WARNING" in mock_send.call_args[0][0]

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_recovery_after_recovery_hits(self, mock_send, monkeypatch):
        import monitor.tasks as t
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", True)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_TOP_N", 3)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_WARN_MBPS", 50)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CRIT_MBPS", 100)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CONSECUTIVE_HITS", 1)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_RECOVERY_HITS", 2)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_COOLDOWN_SEC", 900)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_TX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_RX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", [])

        high = [{"name": "PC-4", "rx_rate": 70_000_000, "tx_rate": 0}]
        await t._cek_per_host_traffic(high)
        await t._cek_per_host_traffic([])
        await t._cek_per_host_traffic([])

        assert mock_send.call_count == 2
        assert "TOP BW WARNING" in mock_send.call_args_list[0][0][0]
        assert "TOP BW RECOVERY" in mock_send.call_args_list[1][0][0]

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_only_top_n_processed(self, mock_send, monkeypatch):
        import monitor.tasks as t
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", True)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_TOP_N", 1)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_WARN_MBPS", 50)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CRIT_MBPS", 100)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_CONSECUTIVE_HITS", 1)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_RECOVERY_HITS", 2)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_COOLDOWN_SEC", 900)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_TX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_MIN_RX_MBPS", 0)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", [])

        data = [
            {"name": "PC-5A", "rx_rate": 120_000_000, "tx_rate": 0},
            {"name": "PC-5B", "rx_rate": 110_000_000, "tx_rate": 0},
        ]
        await t._cek_per_host_traffic(data)

        assert mock_send.call_count == 1
        msg = mock_send.call_args[0][0]
        assert "PC-5A" in msg
        assert "PC-5B" not in msg

    @pytest.mark.asyncio
    @patch("monitor.tasks.kirim_ke_semua_admin", new_callable=AsyncMock)
    async def test_legacy_mode_still_works_when_disabled(self, mock_send, monkeypatch):
        import monitor.tasks as t
        monkeypatch.setattr(t.cfg, "TOP_BW_ALERT_ENABLED", False)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_THRESHOLD_MBPS", 50)
        monkeypatch.setattr(t.cfg, "TRAFFIC_LEAK_WHITELIST", [])

        data = [{"name": "PC-LEGACY", "rx_rate": 60_000_000, "tx_rate": 0}]
        await t._cek_per_host_traffic(data)

        assert mock_send.call_count == 1
        assert "TRAFFIC LEAK" in mock_send.call_args[0][0]
