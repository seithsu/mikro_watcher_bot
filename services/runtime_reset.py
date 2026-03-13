from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core import database


DEFAULT_RESET_FILES = {
    "data/pending_acks.json": {},
    "data/ack_events.json": [],
}

DEFAULT_REMOVE_FILES = [
    "data/state.json",
    "data/monitor_state.json",
    "data/alert_gate.json",
]

DEFAULT_CLEAR_FILES = [
    "data/aktivitas.log",
    "logs/bot.log",
    "logs/monitor.log",
    "logs/pm2-bot.log",
    "logs/pm2-monitor.log",
]

DEFAULT_REMOVE_GLOBS = [
    "data/*.tmp",
]


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _clear_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8"):
        pass


def _remove_file(path: Path):
    if path.exists():
        path.unlink()


def reset_runtime_data(project_root: Path | None = None, clear_runtime_config: bool = False):
    """Reset runtime data/history agar baseline kembali fresh."""
    root = Path(project_root or Path(__file__).resolve().parents[1])

    db_summary = database.reset_all_data()
    result = {
        "database": db_summary,
        "json_reset": [],
        "files_removed": [],
        "files_cleared": [],
        "glob_removed": [],
        "runtime_config_removed": False,
    }

    for rel_path, payload in DEFAULT_RESET_FILES.items():
        path = root / rel_path
        _write_json(path, payload)
        result["json_reset"].append(rel_path)

    for rel_path in DEFAULT_REMOVE_FILES:
        path = root / rel_path
        if path.exists():
            _remove_file(path)
            result["files_removed"].append(rel_path)

    for rel_path in DEFAULT_CLEAR_FILES:
        path = root / rel_path
        if path.exists():
            _clear_file(path)
            result["files_cleared"].append(rel_path)

    for pattern in DEFAULT_REMOVE_GLOBS:
        for path in root.glob(pattern):
            if path.is_file():
                path.unlink()
                result["glob_removed"].append(str(path.relative_to(root)).replace("\\", "/"))

    runtime_config_path = root / "data/runtime_config.json"
    if clear_runtime_config and runtime_config_path.exists():
        runtime_config_path.unlink()
        result["runtime_config_removed"] = True

    return result


def restart_pm2(project_root: Path | None = None):
    """Restart bot + monitor via PM2."""
    root = Path(project_root or Path(__file__).resolve().parents[1])
    proc = subprocess.run(
        ["pm2", "startOrRestart", "ecosystem.config.js", "--update-env"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }
