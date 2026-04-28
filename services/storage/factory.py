from __future__ import annotations

import os
from pathlib import Path

from services.config import ConfigStore, config
from services.storage.base import AccountStore
from services.storage.json_storage import JsonAccountStore
from services.storage.sqlite_storage import SqliteAccountStore

SUPPORTED_ACCOUNT_STORAGE_BACKENDS = ("json", "sqlite")


def get_account_storage_backend(config_store: ConfigStore = config) -> str:
    backend = str(getattr(config_store, "storage_backend", "json") or "json").strip().lower()
    return backend or "json"


def build_account_store_for_backend(
    backend: str,
    *,
    path: Path | None = None,
    config_store: ConfigStore = config,
) -> AccountStore:
    normalized_backend = str(backend or "").strip().lower() or "json"
    if normalized_backend == "json":
        return JsonAccountStore(path or config_store.accounts_file)
    if normalized_backend == "sqlite":
        return SqliteAccountStore(path or config_store.storage_sqlite_path)
    raise ValueError(f"unsupported account storage backend: {normalized_backend}")


def build_account_store(config_store: ConfigStore = config) -> AccountStore:
    backend = get_account_storage_backend(config_store)
    return build_account_store_for_backend(backend, config_store=config_store)


def _is_parent_writable(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.access(path.parent, os.W_OK)


def _get_account_storage_path(config_store: ConfigStore, backend: str) -> Path:
    if backend == "sqlite":
        return config_store.storage_sqlite_path
    return config_store.accounts_file


def get_account_storage_info(config_store: ConfigStore = config) -> dict[str, object]:
    backend = get_account_storage_backend(config_store)
    path = _get_account_storage_path(config_store, backend)
    info = {
        "backend": backend,
        "available_backends": list(SUPPORTED_ACCOUNT_STORAGE_BACKENDS),
        "path": str(path),
        "writable": _is_parent_writable(path),
    }
    if backend not in SUPPORTED_ACCOUNT_STORAGE_BACKENDS:
        info["error"] = f"unsupported account storage backend: {backend}"
    return info
