# ============================================
# TEST_CHART_SERVICE - Tests for services/chart_service.py
# ============================================

import io
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


class TestChartService:
    """Test chart generation functions."""

    def _mock_metrics(self, count=10, value_range=(10, 90)):
        """Helper: generate mock metric data."""
        now = datetime.now()
        return [
            {
                'timestamp': (now - timedelta(hours=count - i)).isoformat(),
                'value': value_range[0] + (value_range[1] - value_range[0]) * i / max(1, count - 1),
                'metadata': None
            }
            for i in range(count)
        ]

    @patch('core.database.get_metrics_summary')
    @patch('core.database.get_metrics')
    def test_cpu_chart_generates_png(self, mock_get_metrics, mock_summary):
        """CPU chart harus menghasilkan valid PNG buffer."""
        mock_get_metrics.return_value = self._mock_metrics(10, (20, 60))
        mock_summary.return_value = {'avg': 40, 'min': 20, 'max': 60, 'count': 10}
        
        from services.chart_service import generate_cpu_chart
        buf, summary = generate_cpu_chart(24)
        
        assert buf is not None
        assert isinstance(buf, io.BytesIO)
        # Check PNG magic bytes
        buf.seek(0)
        assert buf.read(4) == b'\x89PNG'
        assert summary is not None

    @patch('core.database.get_metrics_summary')
    @patch('core.database.get_metrics')
    def test_ram_chart_generates_png(self, mock_get_metrics, mock_summary):
        """RAM chart harus menghasilkan valid PNG buffer."""
        mock_get_metrics.return_value = self._mock_metrics(5, (30, 70))
        mock_summary.return_value = {'avg': 50, 'min': 30, 'max': 70, 'count': 5}
        
        from services.chart_service import generate_ram_chart
        buf, summary = generate_ram_chart(24)
        
        assert buf is not None
        buf.seek(0)
        assert buf.read(4) == b'\x89PNG'

    @patch('core.database.get_metrics')
    def test_chart_empty_data(self, mock_get_metrics):
        """Chart dengan data kosong harus return None."""
        mock_get_metrics.return_value = []
        
        from services.chart_service import generate_cpu_chart
        buf, summary = generate_cpu_chart(24)
        
        assert buf is None
        assert summary is None

    @patch('core.database.get_uptime_stats')
    def test_uptime_chart(self, mock_uptime):
        """Uptime chart harus handle data uptime stats."""
        mock_uptime.return_value = {
            '192.168.1.1': {
                'uptime_pct': 99.95,
                'incident_count': 2,
                'total_downtime_sec': 300,
                'total_downtime_str': '5m 0s',
            },
            '192.168.1.10': {
                'uptime_pct': 98.5,
                'incident_count': 5,
                'total_downtime_sec': 9000,
                'total_downtime_str': '2h 30m 0s',
            }
        }
        
        from services.chart_service import generate_uptime_chart
        buf, summary = generate_uptime_chart(7)
        
        assert buf is not None
        buf.seek(0)
        assert buf.read(4) == b'\x89PNG'
        assert summary['total_hosts'] == 2
        assert summary['total_incidents'] == 7

    @patch('core.database.get_uptime_stats')
    def test_uptime_chart_empty(self, mock_uptime):
        """Uptime chart dengan data kosong harus return None."""
        mock_uptime.return_value = {}
        
        from services.chart_service import generate_uptime_chart
        buf, summary = generate_uptime_chart(7)
        
        assert buf is None
        assert summary is None

    @patch('core.database.get_metrics', return_value=[])
    def test_get_data_freshness_unknown_when_no_metrics(self, mock_metrics):
        from services.chart_service import get_data_freshness
        label, last_ts = get_data_freshness('cpu_usage')
        assert "Freshness tidak diketahui" in label
        assert last_ts is None

    @patch('core.database.get_metrics')
    def test_get_data_freshness_live_and_old_buckets(self, mock_metrics):
        from services.chart_service import get_data_freshness

        recent = datetime.now().isoformat()
        old = (datetime.now() - timedelta(hours=2)).isoformat()

        mock_metrics.return_value = [{'timestamp': recent}]
        label, last_ts = get_data_freshness('cpu_usage')
        assert "baru saja" in label
        assert last_ts is not None

        mock_metrics.return_value = [{'timestamp': old}]
        label, _ = get_data_freshness('cpu_usage')
        assert "Data lama" in label

    @patch('core.database.get_metrics')
    def test_get_data_freshness_handles_exception(self, mock_metrics):
        from services.chart_service import get_data_freshness
        mock_metrics.side_effect = Exception("boom")
        label, last_ts = get_data_freshness('cpu_usage')
        assert "Freshness tidak diketahui" in label
        assert last_ts is None

    def test_fig_to_buffer_returns_png(self):
        from services.chart_service import _fig_to_buffer
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.plot([1, 2], [3, 4])
        buf = _fig_to_buffer(fig)
        assert isinstance(buf, io.BytesIO)
        buf.seek(0)
        assert buf.read(4) == b'\x89PNG'

    @patch('core.database.get_metrics')
    def test_traffic_chart_empty_when_only_ignored_or_invalid(self, mock_metrics, monkeypatch):
        from services.chart_service import generate_traffic_chart
        import services.chart_service as cs

        monkeypatch.setattr('core.config.MONITOR_IGNORE_IFACE', ['ether1'])
        mock_metrics.side_effect = [
            [{'timestamp': datetime.now().isoformat(), 'value': 1000, 'metadata': 'ether1'}],
            [{'timestamp': 'bad-ts', 'value': 1000, 'metadata': 'ether1'}],
        ]

        buf, summary = generate_traffic_chart(24)
        assert buf is None
        assert summary is None

    @patch('core.database.get_metrics')
    def test_traffic_chart_generates_summary(self, mock_metrics, monkeypatch):
        from services.chart_service import generate_traffic_chart

        monkeypatch.setattr('core.config.MONITOR_IGNORE_IFACE', [])
        ts1 = datetime.now().replace(second=0, microsecond=0).isoformat()
        ts2 = (datetime.now() - timedelta(minutes=1)).replace(second=0, microsecond=0).isoformat()
        mock_metrics.side_effect = [
            [
                {'timestamp': ts1, 'value': 2_000_000, 'metadata': 'ether1'},
                {'timestamp': ts2, 'value': 4_000_000, 'metadata': 'ether2'},
            ],
            [
                {'timestamp': ts1, 'value': 1_000_000, 'metadata': 'ether1'},
                {'timestamp': ts2, 'value': 3_000_000, 'metadata': 'ether2'},
            ],
        ]

        buf, summary = generate_traffic_chart(24)
        assert buf is not None
        assert summary['count'] == 2
        assert summary['max_rx'] >= 2.0
        assert 'ether1' in summary['ifaces']

    @patch('core.database.get_metrics_summary')
    @patch('core.database.get_metrics')
    def test_dhcp_chart_generates_png_and_alias(self, mock_metrics, mock_summary):
        from services.chart_service import generate_dhcp_chart, generate_bandwidth_chart

        mock_metrics.return_value = self._mock_metrics(6, (10, 60))
        mock_summary.return_value = {'avg': 35, 'min': 10, 'max': 60, 'count': 6}

        buf, summary = generate_dhcp_chart(24)
        assert buf is not None
        assert summary['avg'] == 35
        assert generate_bandwidth_chart is generate_dhcp_chart

    @patch('core.database.get_metrics', return_value=[{'timestamp': 'bad-ts', 'value': 10}])
    def test_dhcp_chart_returns_none_when_all_points_invalid(self, mock_metrics):
        from services.chart_service import generate_dhcp_chart
        buf, summary = generate_dhcp_chart(24)
        assert buf is None
        assert summary is None
