from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from services.auth_security import hash_auth_secret, is_hashed_auth_secret, verify_auth_secret
from services.config import DATA_DIR, config

AUTH_USERS_FILE = DATA_DIR / "auth_users.json"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AuthService:
    def __init__(self, config_store, store_file: Path):
        self._config = config_store
        self._store_file = store_file
        self._lock = Lock()
        self._users = []
        self._load_users()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _clean_quota(value: Any) -> int:
        try:
            quota = int(value or 0)
        except (TypeError, ValueError):
            quota = 0
        return max(0, quota)

    def _normalize_user(self, raw: object) -> tuple[dict | None, bool]:
        if not isinstance(raw, dict):
            return None, False
        migrated = False
        raw_plaintext_auth_key = self._clean_text(raw.get("auth_key") or raw.get("auth-key"))
        stored_auth_key_hash = self._clean_text(raw.get("auth_key_hash") or raw.get("auth-key-hash"))
        if stored_auth_key_hash:
            if is_hashed_auth_secret(stored_auth_key_hash):
                auth_key_hash = stored_auth_key_hash
            else:
                if self._config.verify_admin_auth_key(stored_auth_key_hash):
                    return None, False
                auth_key_hash = hash_auth_secret(stored_auth_key_hash)
                migrated = True
            migrated = migrated or bool(raw_plaintext_auth_key)
        else:
            if not raw_plaintext_auth_key or self._config.verify_admin_auth_key(raw_plaintext_auth_key):
                return None, False
            auth_key_hash = hash_auth_secret(raw_plaintext_auth_key)
            migrated = True
        created_at = self._clean_text(raw.get("created_at")) or _now_text()
        updated_at = self._clean_text(raw.get("updated_at")) or created_at
        user_id = self._clean_text(raw.get("id")) or uuid.uuid4().hex[:12]
        name = self._clean_text(raw.get("name")) or f"普通用户-{user_id[:6]}"
        return (
            {
                "id": user_id,
                "name": name,
                "role": "user",
                "auth_key_hash": auth_key_hash,
                "image_quota": self._clean_quota(raw.get("image_quota")),
                "total_generated": self._clean_quota(raw.get("total_generated")),
                "last_used_at": self._clean_text(raw.get("last_used_at")) or None,
                "created_at": created_at,
                "updated_at": updated_at,
            },
            migrated,
        )

    def _load_users(self) -> None:
        if not self._store_file.exists():
            self._users = []
            return
        try:
            loaded = json.loads(self._store_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._users = []
            return
        if not isinstance(loaded, list):
            self._users = []
            return
        users: list[dict] = []
        migrated = False
        for item in loaded:
            user, normalized_migrated = self._normalize_user(item)
            if user is None:
                continue
            users.append(user)
            migrated = migrated or normalized_migrated
        self._users = users
        if migrated:
            self._save_users()

    def _save_users(self) -> None:
        self._store_file.parent.mkdir(parents=True, exist_ok=True)
        self._store_file.write_text(json.dumps(self._users, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _find_user_index_by_id(self, user_id: str) -> int:
        for index, user in enumerate(self._users):
            if user.get("id") == user_id:
                return index
        return -1

    def _find_user_index_by_auth_key(self, auth_key: str) -> int:
        for index, user in enumerate(self._users):
            if verify_auth_secret(auth_key, user.get("auth_key_hash")):
                return index
        return -1

    def _ensure_unique_auth_key(self, auth_key: str, *, exclude_user_id: str | None = None) -> None:
        if not auth_key:
            raise ValueError("auth_key is required")
        if self._config.verify_admin_auth_key(auth_key):
            raise ValueError("auth_key conflicts with admin auth-key")
        for user in self._users:
            if user.get("id") == exclude_user_id:
                continue
            if verify_auth_secret(auth_key, user.get("auth_key_hash")):
                raise ValueError("auth_key already exists")

    @staticmethod
    def _public_user(user: dict) -> dict:
        return {
            "id": user.get("id"),
            "name": user.get("name"),
            "role": "user",
            "auth_key": "",
            "auth_key_set": bool(str(user.get("auth_key_hash") or "").strip()),
            "image_quota": int(user.get("image_quota") or 0),
            "total_generated": int(user.get("total_generated") or 0),
            "last_used_at": user.get("last_used_at"),
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
        }

    @staticmethod
    def _public_session(identity: dict) -> dict:
        if identity.get("role") == "admin":
            return {
                "id": "admin",
                "role": "admin",
                "name": "管理员",
                "image_quota": None,
                "total_generated": None,
                "last_used_at": None,
                "image_history_persistence_mode": config.image_history_persistence_mode,
            }
        return {
            "id": identity.get("id") or "unknown",
            "role": "user",
            "name": identity.get("name") or "普通用户",
            "image_quota": int(identity.get("image_quota") or 0),
            "total_generated": int(identity.get("total_generated") or 0),
            "last_used_at": identity.get("last_used_at"),
            "image_history_persistence_mode": config.image_history_persistence_mode,
        }

    @staticmethod
    def admin_identity() -> dict[str, object]:
        return {
            "id": "admin",
            "role": "admin",
            "name": "管理员",
        }

    def authenticate(self, auth_key: str) -> dict | None:
        normalized = self._clean_text(auth_key)
        if not normalized:
            return None
        if self._config.verify_admin_auth_key(normalized):
            return self.admin_identity()
        with self._lock:
            index = self._find_user_index_by_auth_key(normalized)
            if index < 0:
                return None
            return dict(self._users[index])

    def build_session(self, auth_key: str) -> dict | None:
        identity = self.authenticate(auth_key)
        if identity is None:
            return None
        return self._public_session(identity)

    def build_session_from_identity(self, identity: dict) -> dict:
        return self._public_session(identity)

    def list_users(self) -> list[dict]:
        with self._lock:
            return [self._public_user(user) for user in self._users]

    def get_user_by_id(self, user_id: str) -> dict | None:
        normalized_user_id = self._clean_text(user_id)
        if not normalized_user_id:
            return None
        with self._lock:
            index = self._find_user_index_by_id(normalized_user_id)
            if index < 0:
                return None
            return dict(self._users[index])

    def create_user(self, name: str, auth_key: str, image_quota: int) -> dict:
        normalized_auth_key = self._clean_text(auth_key)
        normalized_name = self._clean_text(name)
        now = _now_text()
        with self._lock:
            self._ensure_unique_auth_key(normalized_auth_key)
            user, _ = self._normalize_user(
                {
                    "id": uuid.uuid4().hex[:12],
                    "name": normalized_name,
                    "auth_key_hash": hash_auth_secret(normalized_auth_key),
                    "image_quota": image_quota,
                    "total_generated": 0,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            if user is None:
                raise ValueError("user is invalid")
            self._users.append(user)
            self._save_users()
            return self._public_user(user)

    def update_user(self, user_id: str, updates: dict[str, object]) -> dict | None:
        normalized_user_id = self._clean_text(user_id)
        if not normalized_user_id:
            return None
        with self._lock:
            index = self._find_user_index_by_id(normalized_user_id)
            if index < 0:
                return None
            current = dict(self._users[index])
            merged = {
                **current,
                **updates,
                "id": normalized_user_id,
                "updated_at": _now_text(),
            }
            if "auth_key" in updates:
                next_auth_key = self._clean_text(updates.get("auth_key"))
                self._ensure_unique_auth_key(next_auth_key, exclude_user_id=normalized_user_id)
                merged["auth_key_hash"] = hash_auth_secret(next_auth_key)
            else:
                merged["auth_key_hash"] = self._clean_text(current.get("auth_key_hash"))
            merged.pop("auth_key", None)
            user, _ = self._normalize_user(merged)
            if user is None:
                return None
            self._users[index] = user
            self._save_users()
            return self._public_user(user)

    def delete_user(self, user_id: str) -> bool:
        normalized_user_id = self._clean_text(user_id)
        if not normalized_user_id:
            return False
        with self._lock:
            before = len(self._users)
            self._users = [user for user in self._users if user.get("id") != normalized_user_id]
            if len(self._users) == before:
                return False
            self._save_users()
            return True

    def reserve_images(self, auth_key: str, image_count: int) -> dict | None:
        identity = self.authenticate(auth_key)
        if identity is None:
            return None
        return self.reserve_images_for_identity(identity, image_count)

    def reserve_images_for_identity(self, identity: dict, image_count: int) -> dict | None:
        requested = self._clean_quota(image_count)
        if requested <= 0 or identity.get("role") == "admin":
            return None
        normalized_user_id = self._clean_text(identity.get("id"))
        if not normalized_user_id:
            return None
        with self._lock:
            index = self._find_user_index_by_id(normalized_user_id)
            if index < 0:
                return None
            user = dict(self._users[index])
            current_quota = int(user.get("image_quota") or 0)
            if current_quota < requested:
                raise ValueError("普通用户剩余可生成图片数量不足")
            user["image_quota"] = current_quota - requested
            user["updated_at"] = _now_text()
            self._users[index] = user
            self._save_users()
            return self._public_user(user)

    def settle_images(self, auth_key: str, reserved_count: int, actual_count: int) -> dict | None:
        identity = self.authenticate(auth_key)
        if identity is None:
            return None
        return self.settle_images_for_identity(identity, reserved_count, actual_count)

    def settle_images_for_identity(self, identity: dict, reserved_count: int, actual_count: int) -> dict | None:
        reserved = self._clean_quota(reserved_count)
        actual = min(reserved, self._clean_quota(actual_count))
        if reserved <= 0 or identity.get("role") == "admin":
            return None
        normalized_user_id = self._clean_text(identity.get("id"))
        if not normalized_user_id:
            return None
        with self._lock:
            index = self._find_user_index_by_id(normalized_user_id)
            if index < 0:
                return None
            user = dict(self._users[index])
            refund = max(0, reserved - actual)
            user["image_quota"] = self._clean_quota(user.get("image_quota")) + refund
            user["total_generated"] = self._clean_quota(user.get("total_generated")) + actual
            if actual > 0:
                user["last_used_at"] = _now_text()
            user["updated_at"] = _now_text()
            self._users[index] = user
            self._save_users()
            return self._public_user(user)

auth_service = AuthService(config, AUTH_USERS_FILE)
