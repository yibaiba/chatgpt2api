from __future__ import annotations

from pathlib import Path
from typing import Any

from services.storage.json_utils import read_json_file, write_json_atomic


class JsonAccountStore:
    def __init__(self, path: Path):
        self.path = path

    def load_accounts(self) -> list[dict[str, Any]]:
        data = read_json_file(self.path, default=[])
        return data if isinstance(data, list) else []

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        write_json_atomic(self.path, list(accounts))
