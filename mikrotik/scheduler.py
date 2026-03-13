# ============================================
# MIKROTIK/SCHEDULER - Scheduler CRUD
# ============================================

import logging

from .connection import pool
from .decorators import with_retry, cached, to_bool

logger = logging.getLogger(__name__)


@cached(ttl=10)
@with_retry
def get_schedulers():
    """Ambil daftar scheduler entries."""
    api = pool.get_api()
    scheds = list(api.path('system', 'scheduler'))
    return [
        {
            'id': s.get('.id', ''),
            'name': s.get('name', ''),
            'start_date': s.get('start-date', ''),
            'start_time': s.get('start-time', ''),
            'interval': s.get('interval', ''),
            'on_event': s.get('on-event', ''),
            'run_count': s.get('run-count', '0'),
            'next_run': s.get('next-run', ''),
            'disabled': to_bool(s.get('disabled', False)),
            'comment': s.get('comment', ''),
        }
        for s in scheds
    ]


@with_retry
def set_scheduler_status(sched_id: str, disabled: bool):
    """Enable atau disable scheduler entry."""
    api = pool.get_api()
    api.path('system', 'scheduler').update(
        **{'.id': sched_id, 'disabled': str(disabled).lower()}
    )
    return True
