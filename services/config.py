from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
from pathlib import Path

from services.auth_security import derive_session_secret, hash_auth_secret, verify_auth_secret

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.json"


@dataclass(frozen=True)
class LoadedSettings:
    auth_key: str
    refresh_account_interval_minute: int
    remote_account_sync_interval_minute: int


def _read_json_object(path: Path, *, name: str) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_dir():
        print(
            f"Warning: {name} at '{path}' is a directory, ignoring it and falling back to other configuration sources.",
            file=sys.stderr,
        )
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_json_object(path: Path, *, name: str) -> dict[str, object]:
    return _read_json_object(path, name=name)


def _load_settings() -> LoadedSettings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_config = _read_json_object(CONFIG_FILE, name="config.json")
    auth_key = str(os.getenv("CHATGPT2API_AUTH_KEY") or raw_config.get("auth-key") or raw_config.get("auth-key-hash") or "").strip()
    if not auth_key:
        raise ValueError(
            "❌ auth-key 未设置！\n"
            "请在环境变量 CHATGPT2API_AUTH_KEY 中设置，或者在 config.json 中填写 auth-key。"
        )

    try:
        refresh_interval = int(raw_config.get("refresh_account_interval_minute", 5))
    except (TypeError, ValueError):
        refresh_interval = 5
    try:
        remote_sync_interval = int(raw_config.get("remote_account_sync_interval_minute", 60))
    except (TypeError, ValueError):
        remote_sync_interval = 60

    return LoadedSettings(
        auth_key=auth_key,
        refresh_account_interval_minute=refresh_interval,
        remote_account_sync_interval_minute=remote_sync_interval,
    )


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self._migrate_admin_auth_key_storage()
        if not self.auth_key_configured:
            raise ValueError(
                "❌ auth-key 未设置！\n"
                "请按以下任意一种方式解决：\n"
                "1. 在 Render 的 Environment 变量中添加：\n"
                "   CHATGPT2API_AUTH_KEY = your_real_auth_key\n"
                "2. 或者在 config.json 中填写：\n"
                '   "auth-key": "your_real_auth_key"'
            )

    def _load(self) -> dict[str, object]:
        return _read_json_object(self.path, name="config.json")

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _migrate_admin_auth_key_storage(self) -> None:
        raw_auth_key = str(self.data.get("auth-key") or "").strip()
        if not raw_auth_key:
            return
        self.data["auth-key-hash"] = hash_auth_secret(raw_auth_key)
        self.data.pop("auth-key", None)
        self._save()

    @staticmethod
    def _normalize_clamped_int(
            value: object,
            *,
            fallback: int,
            min_value: int,
            max_value: int,
    ) -> int:
        if value in (None, ""):
            return fallback
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return fallback
        integer = int(numeric)
        return max(min_value, min(max_value, integer))

    @staticmethod
    def _normalize_bool(value: object, *, fallback: bool = False) -> bool:
        if value is None:
            return fallback
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _normalize_sensitive_words(value: object) -> list[str]:
        if isinstance(value, str):
            raw_items = value.splitlines()
        elif isinstance(value, list):
            raw_items = value
        else:
            return []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            word = str(item or "").strip()
            if not word:
                continue
            dedupe_key = word.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append(word)
        return normalized

    @staticmethod
    def _normalize_storage_backend(value: object) -> str:
        backend = str(value or "json").strip().lower() or "json"
        if backend not in {"json", "sqlite"}:
            raise ValueError(f"unsupported storage_backend: {backend}")
        return backend

    @staticmethod
    def _normalize_storage_sqlite_path(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _path_from_storage_sqlite_value(value: object) -> Path:
        raw_path = ConfigStore._normalize_storage_sqlite_path(value) or str(DATA_DIR / "accounts.sqlite3")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        return path

    def _build_public_data(self, data: dict[str, object]) -> dict[str, object]:
        public_data = dict(data)
        public_data.pop("auth-key", None)
        public_data.pop("auth-key-hash", None)
        public_data["auth-key"] = ""
        public_data["auth_key_configured"] = self.auth_key_configured
        public_data["auto_remove_rate_limited_accounts"] = self._normalize_bool(
            public_data.get("auto_remove_rate_limited_accounts"),
            fallback=False,
        )
        public_data["sensitive_word_filter_enabled"] = self._normalize_bool(
            public_data.get("sensitive_word_filter_enabled"),
            fallback=False,
        )
        public_data["sensitive_words"] = self._normalize_sensitive_words(public_data.get("sensitive_words"))
        public_data["storage_backend"] = self.storage_backend
        public_data["storage_sqlite_path"] = str(self.storage_sqlite_path)
        public_data["storage_env_override_active"] = self.has_storage_env_override()
        return public_data

    def _resolve_storage_sqlite_path(self, data: dict[str, object] | None = None) -> Path:
        source = self.data if data is None else data
        return self._path_from_storage_sqlite_value(
            os.getenv("CHATGPT2API_STORAGE_SQLITE_PATH")
            or source.get("storage_sqlite_path"),
        )

    def storage_backend_env_override(self) -> str | None:
        raw_backend = str(os.getenv("CHATGPT2API_STORAGE_BACKEND") or "").strip()
        if not raw_backend:
            return None
        return self._normalize_storage_backend(raw_backend)

    def storage_sqlite_path_env_override(self) -> Path | None:
        raw_path = str(os.getenv("CHATGPT2API_STORAGE_SQLITE_PATH") or "").strip()
        if not raw_path:
            return None
        return self._path_from_storage_sqlite_value(raw_path)

    def active_storage_override_env_vars(self) -> list[str]:
        names: list[str] = []
        if self.storage_backend_env_override() is not None:
            names.append("CHATGPT2API_STORAGE_BACKEND")
        if self.storage_sqlite_path_env_override() is not None:
            names.append("CHATGPT2API_STORAGE_SQLITE_PATH")
        return names

    def has_storage_env_override(self) -> bool:
        return bool(self.active_storage_override_env_vars())

    def resolved_storage_backend(self, data: dict[str, object] | None = None) -> str:
        override = self.storage_backend_env_override()
        if override is not None:
            return override
        source = self.data if data is None else data
        return self._normalize_storage_backend(source.get("storage_backend") or "json")

    def resolved_storage_sqlite_path(self, data: dict[str, object] | None = None) -> Path:
        return self._resolve_storage_sqlite_path(data)

    def effective_account_storage_target(self, data: dict[str, object] | None = None) -> tuple[str, Path]:
        backend = self.resolved_storage_backend(data)
        return backend, (self.accounts_file if backend == "json" else self.resolved_storage_sqlite_path(data))

    @property
    def auth_key(self) -> str:
        return str(os.getenv("CHATGPT2API_AUTH_KEY") or "").strip()

    @property
    def auth_key_configured(self) -> bool:
        return bool(self.auth_key or str(self.data.get("auth-key-hash") or self.data.get("auth-key") or "").strip())

    @property
    def auth_key_hash(self) -> str:
        env_auth_key = self.auth_key
        if env_auth_key:
            return hash_auth_secret(env_auth_key)
        return str(self.data.get("auth-key-hash") or "").strip()

    @property
    def session_signing_secret(self) -> str:
        env_session_secret = str(os.getenv("CHATGPT2API_SESSION_SECRET") or "").strip()
        if env_session_secret:
            return env_session_secret
        env_auth_key = self.auth_key
        if env_auth_key:
            return derive_session_secret(env_auth_key)
        return self.auth_key_hash

    def verify_admin_auth_key(self, auth_key: str) -> bool:
        candidate = str(auth_key or "").strip()
        if not candidate:
            return False
        env_auth_key = self.auth_key
        if env_auth_key:
            return candidate == env_auth_key
        stored_hash = str(self.data.get("auth-key-hash") or self.data.get("auth-key") or "").strip()
        return verify_auth_secret(candidate, stored_hash)

    @property
    def accounts_file(self) -> Path:
        return DATA_DIR / "accounts.json"

    @property
    def refresh_account_interval_minute(self) -> int:
        return self._normalize_clamped_int(
            self.data.get("refresh_account_interval_minute"),
            fallback=5,
            min_value=1,
            max_value=10 ** 9,
        )

    @property
    def refresh_account_batch_size(self) -> int:
        return self._normalize_clamped_int(
            self.data.get("refresh_account_batch_size"),
            fallback=3,
            min_value=1,
            max_value=10,
        )

    @property
    def remote_account_sync_interval_minute(self) -> int:
        return self._normalize_clamped_int(
            self.data.get("remote_account_sync_interval_minute"),
            fallback=60,
            min_value=1,
            max_value=10 ** 9,
        )

    @property
    def auto_remove_rate_limited_accounts(self) -> bool:
        return self._normalize_bool(self.data.get("auto_remove_rate_limited_accounts"), fallback=False)

    @property
    def sensitive_word_filter_enabled(self) -> bool:
        return self._normalize_bool(self.data.get("sensitive_word_filter_enabled"), fallback=False)

    @property
    def sensitive_words(self) -> list[str]:
        return self._normalize_sensitive_words(self.data.get("sensitive_words"))

    @property
    def images_dir(self) -> Path:
        path = DATA_DIR / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def base_url(self) -> str:
        return str(
            os.getenv("CHATGPT2API_BASE_URL")
            or self.data.get("base_url")
            or ""
        ).strip().rstrip("/")

    @property
    def image_history_persistence_mode(self) -> str:
        return "server" if self.data.get("image_history_persistence_mode") == "server" else "browser"

    @property
    def storage_backend(self) -> str:
        return self.resolved_storage_backend()

    @property
    def storage_sqlite_path(self) -> Path:
        return self.resolved_storage_sqlite_path()

    def get(self) -> dict[str, object]:
        return self._build_public_data(self.data)

    def get_proxy_settings(self) -> str:
        return str(self.data.get("proxy") or "").strip()

    def update(self, data: dict[str, object]) -> dict[str, object]:
        incoming = dict(data or {})
        next_data = dict(self.data)
        next_data.update(incoming)
        next_data.pop("auth_key_configured", None)
        next_data.pop("auth-key", None)
        next_data.pop("auth-key-hash", None)

        if "auth-key" in incoming:
            next_auth_key = str(incoming.get("auth-key") or "").strip()
            if next_auth_key:
                next_data["auth-key-hash"] = hash_auth_secret(next_auth_key)
            elif str(self.data.get("auth-key-hash") or "").strip():
                next_data["auth-key-hash"] = str(self.data.get("auth-key-hash") or "").strip()
        elif str(self.data.get("auth-key-hash") or "").strip():
            next_data["auth-key-hash"] = str(self.data.get("auth-key-hash") or "").strip()

        next_data["refresh_account_interval_minute"] = self._normalize_clamped_int(
            next_data.get("refresh_account_interval_minute"),
            fallback=5,
            min_value=1,
            max_value=10 ** 9,
        )
        next_data["refresh_account_batch_size"] = self._normalize_clamped_int(
            next_data.get("refresh_account_batch_size"),
            fallback=3,
            min_value=1,
            max_value=10,
        )
        next_data["remote_account_sync_interval_minute"] = self._normalize_clamped_int(
            next_data.get("remote_account_sync_interval_minute"),
            fallback=60,
            min_value=1,
            max_value=10 ** 9,
        )
        next_data["auto_remove_rate_limited_accounts"] = self._normalize_bool(
            next_data.get("auto_remove_rate_limited_accounts"),
            fallback=False,
        )
        next_data["sensitive_word_filter_enabled"] = self._normalize_bool(
            next_data.get("sensitive_word_filter_enabled"),
            fallback=False,
        )
        next_data["sensitive_words"] = self._normalize_sensitive_words(next_data.get("sensitive_words"))
        next_data["storage_backend"] = self._normalize_storage_backend(next_data.get("storage_backend"))
        normalized_sqlite_path = self._normalize_storage_sqlite_path(next_data.get("storage_sqlite_path"))
        if normalized_sqlite_path:
            next_data["storage_sqlite_path"] = normalized_sqlite_path
        else:
            next_data.pop("storage_sqlite_path", None)
        self.data = next_data
        self._save()
        return self._build_public_data(next_data)


config = ConfigStore(CONFIG_FILE)
