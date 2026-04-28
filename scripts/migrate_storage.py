#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.storage.factory import build_account_store_for_backend
from services.storage.migrate import migrate_accounts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate account storage data between supported backends.")
    parser.add_argument("--from-backend", dest="source_backend", required=True, choices=["json", "sqlite"])
    parser.add_argument("--to-backend", dest="destination_backend", required=True, choices=["json", "sqlite"])
    parser.add_argument("--from-path", dest="source_path", default="", help="Optional source storage path override")
    parser.add_argument("--to-path", dest="destination_path", default="", help="Optional destination storage path override")
    return parser.parse_args()


def _normalize_optional_path(raw_value: str) -> Path | None:
    value = str(raw_value or "").strip()
    return Path(value).expanduser() if value else None


def main() -> None:
    args = parse_args()
    source_path = _normalize_optional_path(args.source_path)
    destination_path = _normalize_optional_path(args.destination_path)

    if (
        args.source_backend == args.destination_backend
        and source_path is not None
        and destination_path is not None
        and source_path.resolve() == destination_path.resolve()
    ):
        raise SystemExit("source and destination storage are identical")

    source_store = build_account_store_for_backend(args.source_backend, path=source_path)
    destination_store = build_account_store_for_backend(args.destination_backend, path=destination_path)
    migrated = migrate_accounts(source_store, destination_store)

    print(
        json.dumps(
            {
                "ok": True,
                "migrated": migrated,
                "from_backend": args.source_backend,
                "to_backend": args.destination_backend,
                "from_path": str(getattr(source_store, "path", source_path or "")),
                "to_path": str(getattr(destination_store, "path", destination_path or "")),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
