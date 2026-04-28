from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from pathlib import Path
from typing import Any


class SqliteAccountStore:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                position INTEGER NOT NULL,
                access_token TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    def load_accounts(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM accounts ORDER BY position ASC, access_token ASC"
            ).fetchall()

        items: list[dict[str, Any]] = []
        for (payload,) in rows:
            try:
                item = json.loads(payload)
            except Exception:
                continue
            if isinstance(item, dict):
                items.append(item)
        return items

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        rows = [
            (
                index,
                str(item.get("access_token") or "").strip(),
                json.dumps(item, ensure_ascii=False),
            )
            for index, item in enumerate(accounts)
            if isinstance(item, dict) and str(item.get("access_token") or "").strip()
        ]
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM accounts")
            connection.executemany(
                "INSERT INTO accounts (position, access_token, payload) VALUES (?, ?, ?)",
                rows,
            )
            connection.commit()
