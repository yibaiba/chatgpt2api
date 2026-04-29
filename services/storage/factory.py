from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from services.storage.base import AccountStore
from services.storage.json_storage import JsonAccountStore
from services.storage.sqlite_storage import SqliteAccountStore

if TYPE_CHECKING:
    from services.config import ConfigStore

SUPPORTED_ACCOUNT_STORAGE_BACKENDS = ("json", "sqlite")
DEFAULT_STORAGE_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_JSON_ACCOUNTS_PATH = DEFAULT_STORAGE_DIR / "accounts.json"
DEFAULT_SQLITE_ACCOUNTS_PATH = DEFAULT_STORAGE_DIR / "accounts.sqlite3"


def _get_default_config_store() -> "ConfigStore":
    from services.config import config

    return config


def _resolve_config_store(config_store: "ConfigStore | None") -> "ConfigStore":
    return _get_default_config_store() if config_store is None else config_store


def get_account_storage_backend(config_store: "ConfigStore | None" = None) -> str:
    backend = str(getattr(_resolve_config_store(config_store), "storage_backend", "json") or "json").strip().lower()
    return backend or "json"


def build_account_store_for_backend(
    backend: str,
    *,
    path: Path | None = None,
    config_store: "ConfigStore | None" = None,
) -> AccountStore:
    normalized_backend = str(backend or "").strip().lower() or "json"
    if normalized_backend == "json":
        if path is not None:
            return JsonAccountStore(path)
        if config_store is not None:
            return JsonAccountStore(config_store.accounts_file)
        return JsonAccountStore(DEFAULT_JSON_ACCOUNTS_PATH)
    if normalized_backend == "sqlite":
        if path is not None:
            return SqliteAccountStore(path)
        if config_store is not None:
            return SqliteAccountStore(config_store.storage_sqlite_path)
        return SqliteAccountStore(DEFAULT_SQLITE_ACCOUNTS_PATH)
    raise ValueError(f"unsupported account storage backend: {normalized_backend}")


def build_account_store(config_store: "ConfigStore | None" = None) -> AccountStore:
    active_config = _resolve_config_store(config_store)
    backend = get_account_storage_backend(active_config)
    return build_account_store_for_backend(backend, config_store=active_config)


def _get_account_storage_path(config_store: "ConfigStore | None", backend: str) -> Path:
    active_config = _resolve_config_store(config_store)
    if backend == "sqlite":
        return active_config.storage_sqlite_path
    return active_config.accounts_file


def get_account_storage_info(config_store: "ConfigStore | None" = None) -> dict[str, object]:
    active_config = _resolve_config_store(config_store)
    backend = get_account_storage_backend(active_config)
    path = _get_account_storage_path(active_config, backend)
    info = {
        "backend": backend,
        "available_backends": list(SUPPORTED_ACCOUNT_STORAGE_BACKENDS),
        "path": str(path),
        "writable": _is_parent_writable(path),
    }
    has_override = getattr(active_config, "has_storage_env_override", None)
    if callable(has_override):
        info["env_override_active"] = bool(has_override())
    if backend not in SUPPORTED_ACCOUNT_STORAGE_BACKENDS:
        info["error"] = f"unsupported account storage backend: {backend}"
    return info


def _is_parent_writable(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.access(path.parent, os.W_OK)
