# ============================================
# SERVICES/CHART_SERVICE - Chart Generation (matplotlib)
# Generate grafik PNG untuk dikirim ke Telegram
# ============================================

import io
import logging
from datetime import datetime, timedelta

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logger = logging.getLogger(__name__)


def get_data_freshness(metric_name):
    """Kembalikan string keterangan kapan data terakhir diperbarui untuk caption chart.

    Returns: tuple (freshness_str, last_ts) dimana last_ts adalah datetime atau None.
    """
    from core import database
    try:
        metrics = database.get_metrics(metric_name, hours=1)
        if metrics:
            last_ts_str = metrics[-1].get('timestamp', '')
            last_ts = datetime.fromisoformat(last_ts_str)
            delta = datetime.now() - last_ts
            minutes = int(delta.total_seconds() / 60)
            if minutes < 1:
                return "Data live (baru saja)", last_ts
            elif minutes < 10:
                return f"Terakhir diperbarui {minutes} menit lalu", last_ts
            elif minutes < 60:
                return f"Terakhir diperbarui {minutes} menit lalu (monitor mungkin lambat)", last_ts
            else:
                return f"Data lama ({minutes // 60} jam lalu) - cek apakah monitor berjalan!", last_ts
    except Exception as e:
        logger.debug("Suppressed non-fatal exception: %s", e)
    return "Freshness tidak diketahui", None

# Dark theme colors
_COLORS = {
    'bg': '#1a1a2e',
    'fg': '#e0e0e0',
    'grid': '#333355',
    'accent1': '#00d4ff',  # Cyan
    'accent2': '#ff6b6b',  # Red
    'accent3': '#51cf66',  # Green
    'accent4': '#ffd43b',  # Yellow
    'accent5': '#845ef7',  # Purple
    'bar1': '#4dabf7',     # Light blue
    'bar2': '#ff8787',     # Light red
}


def _setup_style(fig, ax):
    """Apply dark theme styling ke figure."""
    fig.patch.set_facecolor(_COLORS['bg'])
    ax.set_facecolor(_COLORS['bg'])
    ax.tick_params(colors=_COLORS['fg'], labelsize=8)
    ax.xaxis.label.set_color(_COLORS['fg'])
    ax.yaxis.label.set_color(_COLORS['fg'])
    ax.title.set_color(_COLORS['fg'])
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(_COLORS['grid'])
    ax.spines['bottom'].set_color(_COLORS['grid'])
    ax.grid(True, alpha=0.3, color=_COLORS['grid'], linestyle='--')


def _fig_to_buffer(fig):
    """Convert matplotlib figure ke BytesIO PNG buffer."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor(), edgecolor='none')
    buf.seek(0)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return buf


def generate_cpu_chart(hours=24):
    """Generate line chart CPU usage.
    
    Returns: (BytesIO buffer PNG, dict summary) or (None, None) jika data kosong.
    """
    from core import database

    metrics = database.get_metrics('cpu_usage', hours=hours)
    if not metrics:
        return None, None

    timestamps = []
    values = []
    for m in metrics:
        try:
            ts = datetime.fromisoformat(m['timestamp'])
            timestamps.append(ts)
            values.append(m['value'])
        except (ValueError, KeyError):
            continue

    if not timestamps:
        return None, None

    fig, ax = plt.subplots(figsize=(10, 4))
    _setup_style(fig, ax)

    ax.plot(timestamps, values, color=_COLORS['accent1'], linewidth=1.5, alpha=0.9)
    ax.fill_between(timestamps, values, alpha=0.15, color=_COLORS['accent1'])

    # Threshold line
    from core.config import CPU_THRESHOLD
    ax.axhline(y=CPU_THRESHOLD, color=_COLORS['accent2'], linestyle='--', alpha=0.7, label=f'Threshold ({CPU_THRESHOLD}%)')

    ax.set_title(f'CPU Usage - Last {hours}h', fontsize=12, fontweight='bold', pad=10)
    ax.set_ylabel('CPU (%)')
    ax.set_ylim(0, 105)
    ax.legend(loc='upper right', fontsize=8, facecolor=_COLORS['bg'], edgecolor=_COLORS['grid'], labelcolor=_COLORS['fg'])

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.autofmt_xdate(rotation=30)

    summary = database.get_metrics_summary('cpu_usage', days=hours // 24 or 1)

    return _fig_to_buffer(fig), summary


def generate_ram_chart(hours=24):
    """Generate line chart RAM usage."""
    from core import database

    metrics = database.get_metrics('ram_usage', hours=hours)
    if not metrics:
        return None, None

    timestamps = []
    values = []
    for m in metrics:
        try:
            ts = datetime.fromisoformat(m['timestamp'])
            timestamps.append(ts)
            values.append(m['value'])
        except (ValueError, KeyError):
            continue

    if not timestamps:
        return None, None

    fig, ax = plt.subplots(figsize=(10, 4))
    _setup_style(fig, ax)

    ax.plot(timestamps, values, color=_COLORS['accent5'], linewidth=1.5, alpha=0.9)
    ax.fill_between(timestamps, values, alpha=0.15, color=_COLORS['accent5'])

    from core.config import RAM_THRESHOLD
    ax.axhline(y=RAM_THRESHOLD, color=_COLORS['accent2'], linestyle='--', alpha=0.7, label=f'Threshold ({RAM_THRESHOLD}%)')

    ax.set_title(f'RAM Usage - Last {hours}h', fontsize=12, fontweight='bold', pad=10)
    ax.set_ylabel('RAM (%)')
    ax.set_ylim(0, 105)
    ax.legend(loc='upper right', fontsize=8, facecolor=_COLORS['bg'], edgecolor=_COLORS['grid'], labelcolor=_COLORS['fg'])

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.autofmt_xdate(rotation=30)

    summary = database.get_metrics_summary('ram_usage', days=hours // 24 or 1)

    return _fig_to_buffer(fig), summary


def generate_uptime_chart(days=7):
    """Generate bar chart uptime per host berdasarkan incidents."""
    from core import database

    stats = database.get_uptime_stats(days=days)
    if not stats:
        return None, None

    hosts = list(stats.keys())
    uptimes = [float(stats[h].get('uptime_pct', 0)) for h in hosts]
    incidents = [int(stats[h].get('incident_count', 0)) for h in hosts]

    fig, ax = plt.subplots(figsize=(10, 4))
    _setup_style(fig, ax)

    bars = ax.bar(hosts, uptimes, color=_COLORS['accent3'], alpha=0.85)
    ax.set_title(f'Uptime by Host - Last {days}d', fontsize=12, fontweight='bold', pad=10)
    ax.set_ylabel('Uptime (%)')
    ax.set_ylim(0, 100.5)
    plt.setp(ax.get_xticklabels(), rotation=20, ha='right')

    # Label ringkas per bar agar cepat dibaca di Telegram.
    for bar, val in zip(bars, uptimes):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            min(100, val) + 0.5,
            f"{val:.2f}%",
            ha='center',
            va='bottom',
            fontsize=7,
            color=_COLORS['fg'],
        )

    worst_host = hosts[min(range(len(hosts)), key=lambda i: uptimes[i])] if hosts else None
    summary = {
        'total_hosts': len(hosts),
        'total_incidents': sum(incidents),
        'avg_uptime_pct': round(sum(uptimes) / len(uptimes), 4) if uptimes else 0,
        'worst_host': worst_host,
    }
    return _fig_to_buffer(fig), summary


def generate_traffic_chart(hours=24):
    """Generate dual-line chart RX/TX traffic dari metrics — semua interface.

    B10-RC2: Menampilkan AGGREGATE traffic semua interface (WAN + LOCAL + lainnya),
    bukan hanya WAN. Mencerminkan traffic aktual yang terlihat di WinBox.
    """
    from core import database
    from core.config import MONITOR_IGNORE_IFACE

    metrics_rx = database.get_metrics('traffic_rx_bps', hours=hours)
    metrics_tx = database.get_metrics('traffic_tx_bps', hours=hours)

    if not metrics_rx and not metrics_tx:
        return None, None

    # Aggregate semua interface, bulatkan ke menit agar bisa di-aggregate per waktu
    data_dict = {}
    iface_names = set()

    for m in metrics_rx:
        iface = m.get('metadata', '')
        # Skip interface yang di-ignore atau interface yang tidak relevan (loopback, dlsb2)
        if iface and iface in MONITOR_IGNORE_IFACE:
            continue
        if iface:
            iface_names.add(iface)
        try:
            ts = datetime.fromisoformat(m['timestamp']).replace(second=0, microsecond=0)
            if ts not in data_dict:
                data_dict[ts] = {'rx': 0, 'tx': 0}
            data_dict[ts]['rx'] += m['value']
        except (ValueError, KeyError):
            pass

    for m in metrics_tx:
        iface = m.get('metadata', '')
        if iface and iface in MONITOR_IGNORE_IFACE:
            continue
        try:
            ts = datetime.fromisoformat(m['timestamp']).replace(second=0, microsecond=0)
            if ts not in data_dict:
                data_dict[ts] = {'rx': 0, 'tx': 0}
            data_dict[ts]['tx'] += m['value']
        except (ValueError, KeyError):
            pass

    sorted_dates = sorted(data_dict.keys())
    if not sorted_dates:
        return None, None

    rx_values = [data_dict[d]['rx'] / 1_000_000 for d in sorted_dates]  # bps → Mbps
    tx_values = [data_dict[d]['tx'] / 1_000_000 for d in sorted_dates]

    fig, ax = plt.subplots(figsize=(10, 4))
    _setup_style(fig, ax)

    ax.plot(sorted_dates, rx_values, color=_COLORS['accent1'], linewidth=1.5, alpha=0.9, label='RX (Download)')
    ax.fill_between(sorted_dates, rx_values, alpha=0.15, color=_COLORS['accent1'])

    ax.plot(sorted_dates, tx_values, color=_COLORS['accent4'], linewidth=1.5, alpha=0.9, label='TX (Upload)')
    ax.fill_between(sorted_dates, tx_values, alpha=0.15, color=_COLORS['accent4'])

    iface_label = ', '.join(sorted(iface_names)) if iface_names else 'semua interface'
    ax.set_title(f'Total Traffic ({iface_label}) - Last {hours}h', fontsize=11, fontweight='bold', pad=10)
    ax.set_ylabel('Traffic (Mbps)')
    ax.legend(loc='upper right', fontsize=8, facecolor=_COLORS['bg'], edgecolor=_COLORS['grid'], labelcolor=_COLORS['fg'])

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.autofmt_xdate(rotation=30)

    summary_info = {
        'avg_rx': round(sum(rx_values) / len(rx_values), 1) if rx_values else 0,
        'max_rx': round(max(rx_values), 1) if rx_values else 0,
        'avg_tx': round(sum(tx_values) / len(tx_values), 1) if tx_values else 0,
        'max_tx': round(max(tx_values), 1) if tx_values else 0,
        'count': len(sorted_dates),
        'ifaces': iface_label,
    }

    return _fig_to_buffer(fig), summary_info


# B8 FIX: Rename generate_bandwidth_chart → generate_dhcp_chart (nama lebih akurat)
# Alias backward-compatible disediakan agar handlers/charts.py tidak perlu diubah sekarang
def generate_dhcp_chart(hours=24):
    """Generate line chart DHCP pool usage trend."""
    from core import database

    metrics = database.get_metrics('dhcp_usage_pct', hours=hours)
    if not metrics:
        return None, None

    timestamps = []
    values = []
    for m in metrics:
        try:
            ts = datetime.fromisoformat(m['timestamp'])
            timestamps.append(ts)
            values.append(m['value'])
        except (ValueError, KeyError):
            continue

    if not timestamps:
        return None, None

    fig, ax = plt.subplots(figsize=(10, 4))
    _setup_style(fig, ax)

    ax.plot(timestamps, values, color=_COLORS['accent4'], linewidth=1.5, alpha=0.9)
    ax.fill_between(timestamps, values, alpha=0.15, color=_COLORS['accent4'])

    from core.config import DHCP_ALERT_THRESHOLD
    ax.axhline(y=DHCP_ALERT_THRESHOLD, color=_COLORS['accent2'], linestyle='--', alpha=0.7, label=f'Alert ({DHCP_ALERT_THRESHOLD}%)')

    ax.set_title(f'DHCP Pool Usage - Last {hours}h', fontsize=12, fontweight='bold', pad=10)
    ax.set_ylabel('Usage (%)')
    ax.set_ylim(0, 105)
    ax.legend(loc='upper right', fontsize=8, facecolor=_COLORS['bg'], edgecolor=_COLORS['grid'], labelcolor=_COLORS['fg'])

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.autofmt_xdate(rotation=30)

    summary = database.get_metrics_summary('dhcp_usage_pct', days=hours // 24 or 1)

    return _fig_to_buffer(fig), summary


# B8 FIX: Alias backward-compatible agar kode yang masih gunakan nama lama tetap berjalan
generate_bandwidth_chart = generate_dhcp_chart




