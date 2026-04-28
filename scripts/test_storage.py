#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.storage import build_account_store_for_backend


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an isolated storage backend round-trip check.")
    parser.add_argument("--backend", choices=["json", "sqlite"], default="json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        path = base_dir / ("accounts.json" if args.backend == "json" else "accounts.sqlite3")
        store = build_account_store_for_backend(args.backend, path=path)
        payload = [
            {
                "access_token": "token-1",
                "status": "正常",
                "quota": 3,
            }
        ]
        store.save_accounts(payload)
        loaded = store.load_accounts()

        if loaded != payload:
            raise SystemExit(f"round-trip mismatch for backend={args.backend}")

        print(
            json.dumps(
                {
                    "ok": True,
                    "backend": args.backend,
                    "path": str(path),
                    "items": len(loaded),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
