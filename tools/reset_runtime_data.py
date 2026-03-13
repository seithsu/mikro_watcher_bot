from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.runtime_reset import reset_runtime_data, restart_pm2


def build_parser():
    parser = argparse.ArgumentParser(
        description="Reset histori/runtime data Mikro Watcher agar baseline fresh lagi."
    )
    parser.add_argument(
        "--clear-runtime-config",
        action="store_true",
        help="Ikut hapus data/runtime_config.json.",
    )
    parser.add_argument(
        "--restart-pm2",
        action="store_true",
        help="Restart PM2 setelah reset selesai.",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    project_root = PROJECT_ROOT
    result = reset_runtime_data(
        project_root=project_root,
        clear_runtime_config=bool(args.clear_runtime_config),
    )

    payload = {
        "status": "ok",
        "reset": result,
    }

    if args.restart_pm2:
        payload["pm2"] = restart_pm2(project_root=project_root)

    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
