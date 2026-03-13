# ============================================
# CONFTEST - Shared fixtures for all tests
# ============================================

import os
import sys
import shutil
from pathlib import Path
from uuid import uuid4
import pytest

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TEST_TMP_ROOT = Path(__file__).resolve().parent.parent / "data" / "_pytest_tmp"
_TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def tmp_path():
    """Custom tmp_path fixture to avoid Windows ACL issues from pytest tmpdir plugin."""
    path = _TEST_TMP_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_alert_ipc(monkeypatch):
    """Isolasi IPC file alert agar test tidak tercampur data runtime."""
    ack_file = _TEST_TMP_ROOT / "pending_acks_test.json"
    ack_events_file = _TEST_TMP_ROOT / "ack_events_test.json"
    lock_file = _TEST_TMP_ROOT / "pending_acks_test.lock"
    mute_file = _TEST_TMP_ROOT / "mute_test.lock"
    gate_file = _TEST_TMP_ROOT / "alert_gate_test.json"

    for p in (ack_file, ack_events_file, lock_file, mute_file, gate_file):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        import monitor.alerts as alerts
        monkeypatch.setattr(alerts, "_ACK_FILE", ack_file, raising=False)
        monkeypatch.setattr(alerts, "_ACK_EVENTS_FILE", ack_events_file, raising=False)
        monkeypatch.setattr(alerts, "_IPC_LOCK_FILE", lock_file, raising=False)
        monkeypatch.setattr(alerts, "_MUTE_FILE", mute_file, raising=False)
        monkeypatch.setattr(alerts, "_ALERT_GATE_FILE", gate_file, raising=False)
    except Exception:
        pass

    yield


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton instances between tests."""
    yield
    # Reset MikroTikConnection singleton
    try:
        from mikrotik.connection import MikroTikConnection
        MikroTikConnection._instance = None
        MikroTikConnection._api = None
        MikroTikConnection._active_connections = 0
        MikroTikConnection._reset_version = 0
        MikroTikConnection._connect_fail_count = 0
        MikroTikConnection._next_connect_allowed_ts = 0.0
        MikroTikConnection._last_connect_error = ""
        MikroTikConnection._last_limit_warning_ts = 0.0
    except Exception:
        pass
