from __future__ import annotations

from typing import Any, Protocol


class AccountStore(Protocol):
    def load_accounts(self) -> list[dict[str, Any]]:
        ...

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        ...
