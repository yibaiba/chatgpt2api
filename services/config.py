from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
from pathlib import Path

from services.auth_security import hash_auth_secret, verify_auth_secret

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.json"


@dataclass(frozen=True)
class LoadedSettings:
    auth_key: str
    refresh_account_interval_minute: int


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

    return LoadedSettings(
        auth_key=auth_key,
        refresh_account_interval_minute=refresh_interval,
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
        return str(os.getenv("CHATGPT2API_SESSION_SECRET") or self.auth_key_hash or "").strip()

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

    def get(self) -> dict[str, object]:
        public_data = dict(self.data)
        public_data.pop("auth-key", None)
        public_data.pop("auth-key-hash", None)
        public_data["auth-key"] = ""
        public_data["auth_key_configured"] = self.auth_key_configured
        return public_data

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
        self.data = next_data
        self._save()
        return self.get()


config = ConfigStore(CONFIG_FILE)
