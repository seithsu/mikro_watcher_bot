from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import json
import time

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import handlers.utils as u


def test_format_bytes_auto_bytes():
    assert u.format_bytes_auto(500) == "500 B"


def test_format_bytes_auto_kb():
    assert u.format_bytes_auto(1536) == "1.5 KB"


def test_format_bytes_auto_mb():
    assert u.format_bytes_auto(1572864) == "1.5 MB"


def test_format_bytes_auto_gb():
    assert u.format_bytes_auto(2684354560) == "2.50 GB"


def test_format_bytes_alias():
    assert u._format_bytes(1536) == "1.5 KB"


def test_read_state_json_default_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(u.cfg, "DATA_DIR", tmp_path, raising=False)
    state = u.read_state_json()
    assert state["kategori"]
    assert state["hosts"] == {}


def test_read_state_json_valid_file(monkeypatch, tmp_path):
    monkeypatch.setattr(u.cfg, "DATA_DIR", tmp_path, raising=False)
    payload = {"hosts": {"a": "b"}, "kategori": "ok", "api_connected": False, "api_error": "x"}
    with open(tmp_path / "state.json", "w", encoding="utf-8") as f:
        json.dump(payload, f)

    state = u.read_state_json()
    assert state["hosts"] == {"a": "b"}
    assert state["api_connected"] is False


def test_back_button_helpers():
    m1 = u.get_back_button()
    assert m1.inline_keyboard[0][0].callback_data == "cmd_start"

    m2 = u.get_back_button("menu_network")
    assert len(m2.inline_keyboard[0]) == 2

    base = InlineKeyboardMarkup([[InlineKeyboardButton("X", callback_data="x")]])
    merged = u.append_back_button(base, "menu_tools")
    assert len(merged.inline_keyboard) == 2
    assert any(btn.callback_data == "cmd_start" for btn in merged.inline_keyboard[-1])


def test_escape_and_generic_error():
    assert u.escape_html("<b>test</b>") == "&lt;b&gt;test&lt;/b&gt;"
    assert "Terjadi gangguan internal" in u.generic_error_html()
    assert "prefix" in u.generic_error_html("prefix")


def test_cache_helpers_expire(monkeypatch):
    bot_data = {}
    u.set_cache_with_ts(bot_data, "key1", {"v": 1})
    assert u.get_cache_if_fresh(bot_data, "key1", ttl_seconds=60) == {"v": 1}

    real_time = time.time
    monkeypatch.setattr(u.time, "time", lambda: real_time() + 1000)
    assert u.get_cache_if_fresh(bot_data, "key1", ttl_seconds=1) is None


def test_callback_payload_roundtrip():
    bot_data = {}
    token = u.put_callback_payload(bot_data, "scan", "ether2")
    assert isinstance(token, str) and len(token) == 10
    assert u.get_callback_payload(bot_data, "scan", token, ttl_seconds=60) == "ether2"


def test_format_interface_list_statuses():
    text = u.format_interface_list([
        {"running": True, "enabled": True, "name": "ether1", "type": "ether", "comment": ""},
        {"running": False, "enabled": True, "name": "ether2", "type": "ether", "comment": "down"},
        {"running": False, "enabled": False, "name": "ether3", "type": "ether", "comment": ""},
    ])
    assert "[ON] UP ether1" in text
    assert "[DOWN] DOWN ether2" in text
    assert "[OFF] DISABLED ether3" in text


def test_rate_limiter_limit_and_cleanup(monkeypatch):
    rl = u.RateLimiter(max_per_minute=2)
    monkeypatch.setattr(u.time, "time", lambda: 1000.0)
    assert rl.is_allowed(1) is True
    assert rl.is_allowed(1) is True
    assert rl.is_allowed(1) is False

    rl._requests = {1: [1.0], 2: [995.0]}
    rl._cleanup_idle_users(now=1700.0)
    assert 2 not in rl._requests


@pytest.mark.asyncio
async def test_check_access_denied_non_admin(monkeypatch):
    monkeypatch.setattr(u.cfg, "ADMIN_IDS", [1], raising=False)
    monkeypatch.setattr(u.cfg, "RATE_LIMIT_PER_MINUTE", 20, raising=False)
    monkeypatch.setattr(u, "_rate_limiter", u.RateLimiter(20), raising=False)
    monkeypatch.setattr(u.cfg, "reload_runtime_overrides", lambda min_interval=0: None, raising=False)
    monkeypatch.setattr(u.cfg, "reload_router_env", lambda min_interval=0: None, raising=False)
    catat = MagicMock()
    monkeypatch.setattr(u, "catat", catat)

    msg = MagicMock()
    msg.reply_text = AsyncMock()
    update = SimpleNamespace(message=msg, callback_query=None, effective_message=msg)
    user = SimpleNamespace(id=2, username="guest")

    denied = await u._check_access(update, user, "/status")
    assert denied is True
    msg.reply_text.assert_called_once()
    catat.assert_called_once()


@pytest.mark.asyncio
async def test_check_access_rate_limited(monkeypatch):
    monkeypatch.setattr(u.cfg, "ADMIN_IDS", [1], raising=False)
    monkeypatch.setattr(u.cfg, "RATE_LIMIT_PER_MINUTE", 20, raising=False)
    limiter = MagicMock()
    limiter._max = 20
    limiter.is_allowed.return_value = False
    monkeypatch.setattr(u, "_rate_limiter", limiter, raising=False)
    monkeypatch.setattr(u.cfg, "reload_runtime_overrides", lambda min_interval=0: None, raising=False)
    monkeypatch.setattr(u.cfg, "reload_router_env", lambda min_interval=0: None, raising=False)

    query = MagicMock()
    query.answer = AsyncMock()
    update = SimpleNamespace(message=None, callback_query=query, effective_message=None)
    user = SimpleNamespace(id=1, username="admin")

    denied = await u._check_access(update, user, "/status")
    assert denied is True
    query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_check_access_allowed(monkeypatch):
    monkeypatch.setattr(u.cfg, "ADMIN_IDS", [1], raising=False)
    monkeypatch.setattr(u.cfg, "RATE_LIMIT_PER_MINUTE", 20, raising=False)
    limiter = MagicMock()
    limiter._max = 20
    limiter.is_allowed.return_value = True
    monkeypatch.setattr(u, "_rate_limiter", limiter, raising=False)
    monkeypatch.setattr(u.cfg, "reload_runtime_overrides", lambda min_interval=0: None, raising=False)
    monkeypatch.setattr(u.cfg, "reload_router_env", lambda min_interval=0: None, raising=False)

    msg = MagicMock()
    msg.reply_text = AsyncMock()
    update = SimpleNamespace(message=msg, callback_query=None, effective_message=msg)
    user = SimpleNamespace(id=1, username="admin")

    denied = await u._check_access(update, user, "/status")
    assert denied is False
