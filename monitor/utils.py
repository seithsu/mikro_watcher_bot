# ============================================
# MONITOR/UTILS - Shared utilities for monitor tasks
# ============================================

import asyncio
import random


def compute_sleep_with_jitter(interval, jitter_ratio=0.15, max_jitter=2.0):
    """Tambah jitter positif kecil agar loop periodik tidak selalu sinkron.

    Mencegah thundering herd ketika beberapa task bangun bersamaan.
    """
    base = max(0.0, float(interval or 0))
    spread = min(float(max_jitter), base * float(jitter_ratio))
    if spread <= 0:
        return base
    return base + random.uniform(0.0, spread)


async def sleep_with_jitter(interval, jitter_ratio=0.15, max_jitter=2.0):
    """Async sleep dengan jitter — single source of truth untuk semua task loop."""
    await asyncio.sleep(compute_sleep_with_jitter(interval, jitter_ratio=jitter_ratio, max_jitter=max_jitter))
