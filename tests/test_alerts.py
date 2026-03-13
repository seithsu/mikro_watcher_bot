# ============================================
# TEST_ALERTS - Tests for monitor/alerts.py
# Severity, mute, acknowledge, escalation
# ============================================

import time
import pytest
from unittest.mock import patch, AsyncMock


class TestAlertSeverity:
    def test_severity_values(self):
        from monitor.alerts import AlertSeverity
        assert AlertSeverity.CRITICAL.value == "CRITICAL"
        assert AlertSeverity.WARNING.value == "WARNING"
        assert AlertSeverity.INFO.value == "INFO"

    def test_parse_severity_accepts_enum_string_and_default(self):
        from monitor.alerts import _parse_severity, AlertSeverity
        assert _parse_severity(AlertSeverity.INFO) == AlertSeverity.INFO
        assert _parse_severity("AlertSeverity.CRITICAL") == AlertSeverity.CRITICAL
        assert _parse_severity("warning") == AlertSeverity.WARNING
        assert _parse_severity(object()) == AlertSeverity.WARNING


class TestBotLazyInit:
    def test_get_bot_raises_when_token_missing(self, monkeypatch):
        from monitor import alerts
        monkeypatch.setattr(alerts, "_bot_instance", None, raising=False)
        monkeypatch.setattr(alerts, "TOKEN", "", raising=False)
        with pytest.raises(RuntimeError):
            alerts._get_bot()

    def test_bot_proxy_delegates_attribute(self, monkeypatch):
        from monitor import alerts

        class DummyBot:
            marker = "ok"

        monkeypatch.setattr(alerts, "_get_bot", lambda: DummyBot())
        assert alerts.bot.marker == "ok"


class TestIpcHelpers:
    def test_read_json_unlocked_self_heals_invalid_file(self, tmp_path):
        from monitor import alerts
        target = tmp_path / "broken.json"
        target.write_text("{bad", encoding="utf-8")
        data = alerts._read_json_unlocked(target, {"ok": True})
        assert data == {"ok": True}
        assert alerts._read_json_unlocked(target, {}) == {"ok": True}

    def test_load_pending_acks_returns_none_on_lock_failure(self, monkeypatch):
        from monitor import alerts

        class BrokenLock:
            def __enter__(self):
                raise TimeoutError("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(alerts, "_ipc_lock", lambda: BrokenLock())
        assert alerts._load_pending_acks_from_file() is None

    def test_append_and_consume_ack_events(self, tmp_path, monkeypatch):
        from monitor import alerts
        monkeypatch.setattr(alerts, "_ACK_EVENTS_FILE", tmp_path / "ack_events.json", raising=False)
        alerts._append_ack_event("k1")
        alerts._append_ack_event("*")
        assert alerts._consume_ack_events() == ["k1", "*"]
        assert alerts._read_json_unlocked(alerts._ACK_EVENTS_FILE, []) == []

    def test_write_ack_file_and_save_pending_acks(self, tmp_path, monkeypatch):
        from monitor import alerts
        monkeypatch.setattr(alerts, "_ACK_FILE", tmp_path / "pending_acks.json", raising=False)
        alerts._pending_acks.clear()
        alerts._pending_acks["down_router"] = {
            "message": "router down",
            "severity": "critical",
            "time": 10,
            "escalated": 1,
        }
        alerts._save_pending_acks()
        saved = alerts._read_json_unlocked(alerts._ACK_FILE, {})
        assert saved["down_router"]["severity"] == "CRITICAL"
        assert saved["down_router"]["escalated"] == 1

    def test_get_pending_alerts_handles_invalid_timestamp(self, monkeypatch):
        from monitor import alerts
        alerts._pending_acks.clear()
        monkeypatch.setattr(alerts, "_load_pending_acks_from_file", lambda: {
            "x": {"message": "msg", "severity": "warning", "time": "bad", "escalated": 0}
        })
        rows = alerts.get_pending_alerts()
        assert rows[0]["time"] == "-"


class TestMuteCheck:
    def test_no_mute_file(self, tmp_path, monkeypatch):
        from monitor import alerts
        monkeypatch.setattr(alerts, "_MUTE_FILE", tmp_path / "mute.lock")
        assert alerts._check_mute() is False

    def test_mute_active(self, tmp_path, monkeypatch):
        from monitor import alerts
        mute_file = tmp_path / "mute.lock"
        monkeypatch.setattr(alerts, "_MUTE_FILE", mute_file)
        mute_file.write_text(str(time.time() + 3600))
        assert alerts._check_mute() is True

    def test_mute_expired(self, tmp_path, monkeypatch):
        from monitor import alerts
        mute_file = tmp_path / "mute.lock"
        monkeypatch.setattr(alerts, "_MUTE_FILE", mute_file)
        mute_file.write_text(str(time.time() - 100))
        assert alerts._check_mute() is False


class TestAlertGate:
    def test_gate_default_enabled_when_not_required(self, monkeypatch):
        from monitor import alerts
        monkeypatch.setattr(alerts, "ALERT_REQUIRE_START", False, raising=False)
        assert alerts.is_alert_delivery_enabled() is True

    def test_gate_default_disabled_when_required(self, monkeypatch):
        from monitor import alerts
        monkeypatch.setattr(alerts, "ALERT_REQUIRE_START", True, raising=False)
        assert alerts.is_alert_delivery_enabled() is False

    def test_set_gate_enabled(self, monkeypatch, tmp_path):
        from monitor import alerts
        monkeypatch.setattr(alerts, "_ALERT_GATE_FILE", tmp_path / "alert_gate.json", raising=False)
        monkeypatch.setattr(alerts, "ALERT_REQUIRE_START", True, raising=False)
        assert alerts.set_alert_delivery_enabled(True, actor="test", reason="unit") is True
        assert alerts.is_alert_delivery_enabled() is True

    def test_set_gate_disabled_clears_pending_and_recent(self, monkeypatch, tmp_path):
        from monitor import alerts
        monkeypatch.setattr(alerts, "_ALERT_GATE_FILE", tmp_path / "alert_gate.json", raising=False)
        monkeypatch.setattr(alerts, "_ACK_FILE", tmp_path / "pending_acks.json", raising=False)
        monkeypatch.setattr(alerts, "ALERT_REQUIRE_START", True, raising=False)
        alerts._recent_alerts.clear()
        alerts._recent_alerts.append((time.time(), "warn", alerts.AlertSeverity.WARNING))
        alerts._pending_acks.clear()
        alerts._pending_acks["a"] = {
            "message": "x", "severity": alerts.AlertSeverity.CRITICAL, "time": time.time(), "escalated": 0
        }
        assert alerts.set_alert_delivery_enabled(False, actor="test", reason="cleanup") is True
        assert list(alerts._recent_alerts) == []
        assert alerts._pending_acks == {}

    def test_gate_returns_false_on_lock_error(self, monkeypatch):
        from monitor import alerts
        monkeypatch.setattr(alerts, "ALERT_REQUIRE_START", True, raising=False)

        class BrokenLock:
            def __enter__(self):
                raise TimeoutError("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(alerts, "_ipc_lock", lambda: BrokenLock())
        assert alerts.is_alert_delivery_enabled() is False

    def test_set_gate_returns_false_when_write_fails(self, monkeypatch):
        from monitor import alerts

        class BrokenLock:
            def __enter__(self):
                raise TimeoutError("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(alerts, "_ipc_lock", lambda: BrokenLock())
        assert alerts.set_alert_delivery_enabled(True) is False

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_send_suppressed_when_gate_disabled(self, mock_bot, monkeypatch, tmp_path):
        from monitor import alerts
        monkeypatch.setattr(alerts, "ALERT_REQUIRE_START", True, raising=False)
        monkeypatch.setattr(alerts, "_ALERT_GATE_FILE", tmp_path / "alert_gate.json", raising=False)
        alerts.set_alert_delivery_enabled(False, actor="test", reason="unit")
        mock_bot.send_message = AsyncMock()
        await alerts.kirim_ke_semua_admin("test msg")
        mock_bot.send_message.assert_not_called()


class TestAcknowledge:
    def setup_method(self):
        from monitor import alerts
        alerts._pending_acks.clear()
        alerts._acknowledged.clear()

    def test_ack_empty(self):
        from monitor.alerts import acknowledge_alert
        assert acknowledge_alert() == 0

    def test_ack_with_pending(self):
        from monitor.alerts import acknowledge_alert, _pending_acks, AlertSeverity
        _pending_acks["key1"] = {"message": "test", "severity": AlertSeverity.CRITICAL, "time": time.time(), "escalated": 0}
        _pending_acks["key2"] = {"message": "test2", "severity": AlertSeverity.CRITICAL, "time": time.time(), "escalated": 0}
        assert acknowledge_alert() == 2
        assert len(_pending_acks) == 0

    def test_ack_specific_key(self):
        from monitor.alerts import acknowledge_alert, _pending_acks, _acknowledged, AlertSeverity
        _pending_acks["k1"] = {"message": "a", "severity": AlertSeverity.CRITICAL, "time": time.time(), "escalated": 0}
        assert acknowledge_alert("k1") == 1
        assert "k1" not in _pending_acks
        assert "k1" in _acknowledged

    def test_ack_specific_key_reads_file_snapshot(self, monkeypatch):
        from monitor import alerts
        written = {}
        monkeypatch.setattr(alerts, "_load_pending_acks_from_file", lambda: {"k1": {"message": "from-file"}})
        monkeypatch.setattr(alerts, "_write_ack_file", lambda data: written.update(data=data))
        appended = []
        monkeypatch.setattr(alerts, "_append_ack_event", lambda key: appended.append(key))
        assert alerts.acknowledge_alert("k1") == 1
        assert written["data"] == {}
        assert appended == ["k1"]

    def test_ack_nonexistent(self):
        from monitor.alerts import acknowledge_alert
        assert acknowledge_alert("nope") == 0

    def test_get_pending_alerts(self):
        from monitor.alerts import get_pending_alerts, _pending_acks, AlertSeverity
        _pending_acks["t"] = {
            "message": "Long alert message for testing",
            "severity": AlertSeverity.CRITICAL,
            "time": time.time(),
            "escalated": 1,
        }
        alerts = get_pending_alerts()
        assert len(alerts) == 1
        assert alerts[0]["key"] == "t"
        assert alerts[0]["severity"] == "CRITICAL"


class TestWithTimeout:
    @pytest.mark.asyncio
    async def test_success(self):
        from monitor.alerts import with_timeout

        async def fast():
            return "ok"

        assert await with_timeout(fast(), timeout=5) == "ok"

    @pytest.mark.asyncio
    async def test_timeout_returns_default(self):
        import asyncio
        from monitor.alerts import with_timeout

        async def slow():
            await asyncio.sleep(10)
            return "never"

        result = await with_timeout(slow(), timeout=0.1, default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_exception_returns_default(self):
        from monitor.alerts import with_timeout

        async def boom():
            raise ValueError("err")

        assert await with_timeout(boom(), timeout=5, default="safe") == "safe"

    @pytest.mark.asyncio
    async def test_exception_logs_keyed_error(self):
        from monitor import alerts

        async def boom():
            raise ValueError("err")

        with patch.object(alerts, "logger") as mock_logger:
            assert await alerts.with_timeout(boom(), timeout=5, default="safe", log_key="unit:boom") == "safe"
        mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_exception_logs_generic_error_without_key(self):
        from monitor import alerts

        async def boom():
            raise ValueError("err")

        with patch.object(alerts, "logger") as mock_logger:
            assert await alerts.with_timeout(boom(), timeout=5, default="safe") == "safe"
        mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_timeout_warning_is_throttled(self):
        import asyncio
        from monitor import alerts
        alerts._TIMEOUT_LOG_STATE.clear()

        async def slow():
            await asyncio.sleep(10)

        with patch.object(alerts, "logger") as mock_logger:
            assert await alerts.with_timeout(slow(), timeout=0.01, default="fallback", log_key="unit:slow", warn_every_sec=300) == "fallback"
            assert await alerts.with_timeout(slow(), timeout=0.01, default="fallback", log_key="unit:slow", warn_every_sec=300) == "fallback"
        mock_logger.warning.assert_called_once()


class TestCheckEscalation:
    def setup_method(self):
        from monitor import alerts
        alerts._pending_acks.clear()
        alerts.ALERT_REQUIRE_START = False

    @pytest.mark.asyncio
    async def test_no_escalation_when_empty(self):
        from monitor.alerts import check_escalation
        await check_escalation()

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_escalation_triggered(self, mock_bot):
        from monitor.alerts import check_escalation, _pending_acks, AlertSeverity
        mock_bot.send_message = AsyncMock()
        _pending_acks["old"] = {"message": "Down", "severity": AlertSeverity.CRITICAL, "time": time.time() - 3600, "escalated": 0}
        await check_escalation()
        assert _pending_acks["old"]["escalated"] == 1

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_no_escalation_if_maxed(self, mock_bot):
        from monitor.alerts import check_escalation, _pending_acks, AlertSeverity
        mock_bot.send_message = AsyncMock()
        _pending_acks["maxed"] = {"message": "Max", "severity": AlertSeverity.CRITICAL, "time": time.time() - 3600, "escalated": 3}
        await check_escalation()
        assert _pending_acks["maxed"]["escalated"] == 3

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_escalation_hydrates_file_and_targets_single_admin(self, mock_bot, monkeypatch):
        from monitor import alerts
        mock_bot.send_message = AsyncMock()
        monkeypatch.setattr(alerts, "ADMIN_IDS", [1, 2, 3], raising=False)
        monkeypatch.setattr(alerts, "_load_pending_acks_from_file", lambda: {
            "old": {"message": "Down", "severity": "CRITICAL", "time": time.time() - 3600, "escalated": 0}
        })
        monkeypatch.setattr(alerts, "_consume_ack_events", lambda: [])
        alerts._pending_acks.clear()
        await alerts.check_escalation()
        assert alerts._pending_acks["old"]["escalated"] == 1
        assert mock_bot.send_message.await_args.kwargs["chat_id"] == 1

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_escalation_ack_all_event_clears_pending(self, mock_bot, monkeypatch):
        from monitor import alerts
        mock_bot.send_message = AsyncMock()
        alerts._pending_acks.clear()
        alerts._pending_acks["a"] = {"message": "Down", "severity": alerts.AlertSeverity.CRITICAL, "time": time.time() - 3600, "escalated": 0}
        monkeypatch.setattr(alerts, "_load_pending_acks_from_file", lambda: {})
        monkeypatch.setattr(alerts, "_consume_ack_events", lambda: ["*"])
        await alerts.check_escalation()
        assert alerts._pending_acks == {}
        mock_bot.send_message.assert_not_called()


class TestDeliveryAndDigest:
    def setup_method(self):
        from monitor import alerts
        alerts._recent_alerts.clear()
        alerts._pending_acks.clear()
        alerts._acknowledged.clear()

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_send_warning_suppressed_in_digest_mode(self, mock_bot, monkeypatch):
        from monitor import alerts
        mock_bot.send_message = AsyncMock()
        monkeypatch.setattr(alerts, "ALERT_DIGEST_THRESHOLD", 1, raising=False)
        monkeypatch.setattr(alerts, "ALERT_DIGEST_WINDOW", 300, raising=False)
        monkeypatch.setattr(alerts, "is_alert_delivery_enabled", lambda: True)
        monkeypatch.setattr(alerts, "_check_mute", lambda: False)
        async def fake_to_thread(func, *a, **k):
            return func(*a, **k)
        monkeypatch.setattr(alerts.asyncio, "to_thread", fake_to_thread)
        await alerts.kirim_ke_semua_admin("warn-1", severity=alerts.AlertSeverity.WARNING)
        await alerts.kirim_ke_semua_admin("warn-2", severity=alerts.AlertSeverity.WARNING)
        assert mock_bot.send_message.await_count == len(alerts.ADMIN_IDS)

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_send_critical_persists_pending_ack_and_markup(self, mock_bot, monkeypatch):
        from monitor import alerts
        mock_bot.send_message = AsyncMock()
        monkeypatch.setattr(alerts, "is_alert_delivery_enabled", lambda: True)
        monkeypatch.setattr(alerts, "_check_mute", lambda: False)
        async def fake_to_thread(func, *a, **k):
            return func(*a, **k)
        monkeypatch.setattr(alerts.asyncio, "to_thread", fake_to_thread)
        await alerts.kirim_ke_semua_admin("router down", severity=alerts.AlertSeverity.CRITICAL, alert_key="down_router")
        assert "down_router" in alerts._pending_acks
        kwargs = mock_bot.send_message.await_args.kwargs
        assert kwargs["reply_markup"] is not None
        assert kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_send_skips_when_muted(self, mock_bot, monkeypatch):
        from monitor import alerts
        mock_bot.send_message = AsyncMock()
        monkeypatch.setattr(alerts, "is_alert_delivery_enabled", lambda: True)
        monkeypatch.setattr(alerts, "_check_mute", lambda: True)
        async def fake_to_thread(func, *a, **k):
            return func(*a, **k)
        monkeypatch.setattr(alerts.asyncio, "to_thread", fake_to_thread)
        await alerts.kirim_ke_semua_admin("warn", severity=alerts.AlertSeverity.WARNING)
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_send_logs_delivery_error_and_continues(self, mock_bot, monkeypatch):
        from monitor import alerts
        calls = []

        async def fake_send_message(**kwargs):
            calls.append(kwargs["chat_id"])
            if len(calls) == 1:
                raise RuntimeError("boom")

        mock_bot.send_message = AsyncMock(side_effect=fake_send_message)
        monkeypatch.setattr(alerts, "ADMIN_IDS", [1, 2], raising=False)
        monkeypatch.setattr(alerts, "is_alert_delivery_enabled", lambda: True)
        monkeypatch.setattr(alerts, "_check_mute", lambda: False)
        async def fake_to_thread(func, *a, **k):
            return func(*a, **k)
        monkeypatch.setattr(alerts.asyncio, "to_thread", fake_to_thread)
        await alerts.kirim_ke_semua_admin("warn", severity=alerts.AlertSeverity.INFO)
        assert calls == [1, 2]

    @pytest.mark.asyncio
    @patch("monitor.alerts.bot")
    async def test_send_digest_batches_recent_warnings(self, mock_bot, monkeypatch):
        from monitor import alerts
        mock_bot.send_message = AsyncMock()
        monkeypatch.setattr(alerts, "is_alert_delivery_enabled", lambda: True)
        async def fake_to_thread(func, *a, **k):
            return func(*a, **k)
        monkeypatch.setattr(alerts.asyncio, "to_thread", fake_to_thread)
        monkeypatch.setattr(alerts, "ALERT_DIGEST_THRESHOLD", 1, raising=False)
        monkeypatch.setattr(alerts, "ALERT_DIGEST_WINDOW", 300, raising=False)
        alerts._recent_alerts.clear()
        alerts._recent_alerts.extend([
            (time.time(), "warn-a", alerts.AlertSeverity.WARNING),
            (time.time(), "warn-b", alerts.AlertSeverity.INFO),
        ])
        await alerts.send_digest()
        mock_bot.send_message.assert_awaited()
        sent_text = mock_bot.send_message.await_args.kwargs["text"]
        assert "ALERT DIGEST" in sent_text
        assert len(alerts._recent_alerts) == 0
