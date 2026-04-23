from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from services.config import DATA_DIR, config

AUTH_USERS_FILE = DATA_DIR / "auth_users.json"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AuthService:
    def __init__(self, admin_auth_key: str, store_file: Path):
        self._admin_auth_key = self._clean_text(admin_auth_key)
        self._store_file = store_file
        self._lock = Lock()
        self._users = self._load_users()

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

    def _normalize_user(self, raw: object) -> dict | None:
        if not isinstance(raw, dict):
            return None
        auth_key = self._clean_text(raw.get("auth_key") or raw.get("auth-key"))
        if not auth_key or auth_key == self._admin_auth_key:
            return None
        created_at = self._clean_text(raw.get("created_at")) or _now_text()
        updated_at = self._clean_text(raw.get("updated_at")) or created_at
        user_id = self._clean_text(raw.get("id")) or uuid.uuid4().hex[:12]
        name = self._clean_text(raw.get("name")) or f"普通用户-{user_id[:6]}"
        return {
            "id": user_id,
            "name": name,
            "role": "user",
            "auth_key": auth_key,
            "image_quota": self._clean_quota(raw.get("image_quota")),
            "total_generated": self._clean_quota(raw.get("total_generated")),
            "last_used_at": self._clean_text(raw.get("last_used_at")) or None,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def _load_users(self) -> list[dict]:
        if not self._store_file.exists():
            return []
        try:
            loaded = json.loads(self._store_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(loaded, list):
            return []
        return [user for item in loaded if (user := self._normalize_user(item)) is not None]

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
            if self._clean_text(user.get("auth_key")) == auth_key:
                return index
        return -1

    def _ensure_unique_auth_key(self, auth_key: str, *, exclude_user_id: str | None = None) -> None:
        if not auth_key:
            raise ValueError("auth_key is required")
        if auth_key == self._admin_auth_key:
            raise ValueError("auth_key conflicts with admin auth-key")
        for user in self._users:
            if user.get("id") == exclude_user_id:
                continue
            if self._clean_text(user.get("auth_key")) == auth_key:
                raise ValueError("auth_key already exists")

    @staticmethod
    def _public_user(user: dict) -> dict:
        return {
            "id": user.get("id"),
            "name": user.get("name"),
            "role": "user",
            "auth_key": user.get("auth_key"),
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

    def authenticate(self, auth_key: str) -> dict | None:
        normalized = self._clean_text(auth_key)
        if not normalized:
            return None
        if normalized == self._admin_auth_key:
            return {"role": "admin", "name": "管理员", "auth_key": normalized}
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

    def list_users(self) -> list[dict]:
        with self._lock:
            return [self._public_user(user) for user in self._users]

    def create_user(self, name: str, auth_key: str, image_quota: int) -> dict:
        normalized_auth_key = self._clean_text(auth_key)
        normalized_name = self._clean_text(name)
        now = _now_text()
        with self._lock:
            self._ensure_unique_auth_key(normalized_auth_key)
            user = self._normalize_user(
                {
                    "id": uuid.uuid4().hex[:12],
                    "name": normalized_name,
                    "auth_key": normalized_auth_key,
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
            next_auth_key = self._clean_text(updates.get("auth_key")) if "auth_key" in updates else self._clean_text(current.get("auth_key"))
            self._ensure_unique_auth_key(next_auth_key, exclude_user_id=normalized_user_id)
            merged = {
                **current,
                **updates,
                "id": normalized_user_id,
                "auth_key": next_auth_key,
                "updated_at": _now_text(),
            }
            user = self._normalize_user(merged)
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
        normalized_auth_key = self._clean_text(auth_key)
        requested = self._clean_quota(image_count)
        if requested <= 0 or normalized_auth_key == self._admin_auth_key:
            return None
        with self._lock:
            index = self._find_user_index_by_auth_key(normalized_auth_key)
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
        normalized_auth_key = self._clean_text(auth_key)
        reserved = self._clean_quota(reserved_count)
        actual = min(reserved, self._clean_quota(actual_count))
        if reserved <= 0 or normalized_auth_key == self._admin_auth_key:
            return None
        with self._lock:
            index = self._find_user_index_by_auth_key(normalized_auth_key)
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


auth_service = AuthService(config.auth_key, AUTH_USERS_FILE)
