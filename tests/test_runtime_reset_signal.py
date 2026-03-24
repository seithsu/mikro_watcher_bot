import json

from core.runtime_reset_signal import emit_runtime_reset_signal, read_runtime_reset_signal


def test_emit_and_read_runtime_reset_signal_roundtrip(tmp_path):
    signal_file = tmp_path / "runtime_reset_signal.json"

    payload = emit_runtime_reset_signal(
        reason="unit-test",
        clear_runtime_config=True,
        signal_file=signal_file,
    )

    loaded = read_runtime_reset_signal(signal_file)

    assert loaded["reason"] == "unit-test"
    assert loaded["clear_runtime_config"] is True
    assert isinstance(payload["ts"], float)
    assert loaded == payload


def test_read_runtime_reset_signal_missing_file_returns_empty(tmp_path):
    assert read_runtime_reset_signal(tmp_path / "missing.json") == {}


def test_read_runtime_reset_signal_invalid_payload_returns_empty(tmp_path):
    signal_file = tmp_path / "runtime_reset_signal.json"
    signal_file.write_text(json.dumps(["not-a-dict"]), encoding="utf-8")

    assert read_runtime_reset_signal(signal_file) == {}


def test_read_runtime_reset_signal_invalid_json_returns_empty(tmp_path):
    signal_file = tmp_path / "runtime_reset_signal.json"
    signal_file.write_text("{broken", encoding="utf-8")

    assert read_runtime_reset_signal(signal_file) == {}
