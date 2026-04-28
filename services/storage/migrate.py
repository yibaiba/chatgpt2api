from __future__ import annotations

from services.storage.base import AccountStore


def migrate_accounts(source_store: AccountStore, destination_store: AccountStore) -> int:
    accounts = source_store.load_accounts()
    destination_store.save_accounts(accounts)
    return len(accounts)
