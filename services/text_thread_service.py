from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
import uuid

from services.config import DATA_DIR
from services.storage.json_utils import read_json_file, write_json_atomic

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None

TEXT_THREADS_FILE = DATA_DIR / "text_threads.json"
ALLOWED_OWNER_ROLES = {"admin", "user"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TextThreadService:
    def __init__(self, store_file: Path):
        self._store_file = store_file
        self._lock_file = store_file.with_suffix(f"{store_file.suffix}.lock")
        self._lock = Lock()
        self._items = self._load_items()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    def _owner_fields(self, identity: dict[str, object]) -> tuple[str, str, str]:
        role = self._clean_text(identity.get("role")).lower()
        owner_role = role if role in ALLOWED_OWNER_ROLES else "user"
        owner_id = self._clean_text(identity.get("id")) or ("admin" if owner_role == "admin" else "unknown")
        owner_name = self._clean_text(identity.get("name")) or ("管理员" if owner_role == "admin" else "用户")
        return owner_role, owner_id, owner_name

    def _normalize_item(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        thread_id = self._clean_text(raw.get("id"))
        conversation_id = self._clean_text(raw.get("conversation_id"))
        parent_message_id = self._clean_text(raw.get("parent_message_id"))
        owner_role = self._clean_text(raw.get("owner_role")).lower()
        owner_id = self._clean_text(raw.get("owner_id"))
        if not thread_id or not conversation_id or not parent_message_id:
            return None
        if owner_role not in ALLOWED_OWNER_ROLES or not owner_id:
            return None
        created_at = self._clean_text(raw.get("created_at")) or _now_iso()
        updated_at = self._clean_text(raw.get("updated_at")) or created_at
        return {
            "id": thread_id,
            "conversation_id": conversation_id,
            "parent_message_id": parent_message_id,
            "owner_role": owner_role,
            "owner_id": owner_id,
            "owner_name": self._clean_text(raw.get("owner_name")) or ("管理员" if owner_role == "admin" else "用户"),
            "created_at": created_at,
            "updated_at": updated_at,
            "last_model": self._clean_text(raw.get("last_model")) or None,
            "last_error": self._clean_text(raw.get("last_error")) or None,
        }

    def _load_items(self) -> list[dict[str, object]]:
        loaded = read_json_file(self._store_file, default=[])
        if not isinstance(loaded, list):
            return []
        return [item for raw in loaded if (item := self._normalize_item(raw)) is not None]

    @contextmanager
    def _locked_store(self):
        with self._lock:
            lock_handle = None
            try:
                self._lock_file.parent.mkdir(parents=True, exist_ok=True)
                lock_handle = self._lock_file.open("a+", encoding="utf-8")
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                if lock_handle is not None:
                    if fcntl is not None:
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                    lock_handle.close()

    def _save_items(self, items: list[dict[str, object]]) -> None:
        write_json_atomic(self._store_file, items)
        self._items = items

    @staticmethod
    def _find_index(items: list[dict[str, object]], thread_id: str) -> int:
        for index, item in enumerate(items):
            if item.get("id") == thread_id:
                return index
        return -1

    def _can_access(self, identity: dict[str, object], item: dict[str, object]) -> bool:
        owner_role, owner_id, _owner_name = self._owner_fields(identity)
        return item.get("owner_role") == owner_role and item.get("owner_id") == owner_id

    @staticmethod
    def _copy_item(item: dict[str, object]) -> dict[str, object]:
        return dict(item)

    def create_thread(
        self,
        identity: dict[str, object],
        *,
        conversation_id: str,
        parent_message_id: str,
        model: str,
        last_error: str | None = None,
    ) -> dict[str, object]:
        owner_role, owner_id, owner_name = self._owner_fields(identity)
        now = _now_iso()
        item = {
            "id": uuid.uuid4().hex,
            "conversation_id": self._clean_text(conversation_id),
            "parent_message_id": self._clean_text(parent_message_id),
            "owner_role": owner_role,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "created_at": now,
            "updated_at": now,
            "last_model": self._clean_text(model) or None,
            "last_error": self._clean_text(last_error) or None,
        }
        with self._locked_store():
            items = self._load_items()
            items.append(item)
            self._save_items(items)
            return self._copy_item(item)

    def get_thread(self, identity: dict[str, object], thread_id: str) -> dict[str, object] | None:
        normalized_thread_id = self._clean_text(thread_id)
        if not normalized_thread_id:
            return None
        with self._locked_store():
            items = self._load_items()
            self._items = items
            index = self._find_index(items, normalized_thread_id)
            if index < 0:
                return None
            item = items[index]
            if not self._can_access(identity, item):
                return None
            return self._copy_item(item)

    def update_thread(
        self,
        identity: dict[str, object],
        thread_id: str,
        *,
        conversation_id: str,
        parent_message_id: str,
        model: str,
        last_error: str | None = None,
    ) -> dict[str, object] | None:
        normalized_thread_id = self._clean_text(thread_id)
        if not normalized_thread_id:
            return None
        with self._locked_store():
            items = self._load_items()
            index = self._find_index(items, normalized_thread_id)
            if index < 0:
                return None
            item = dict(items[index])
            if not self._can_access(identity, item):
                return None
            item["conversation_id"] = self._clean_text(conversation_id)
            item["parent_message_id"] = self._clean_text(parent_message_id)
            item["updated_at"] = _now_iso()
            item["last_model"] = self._clean_text(model) or None
            item["last_error"] = self._clean_text(last_error) or None
            items[index] = item
            self._save_items(items)
            return self._copy_item(item)


text_thread_service = TextThreadService(TEXT_THREADS_FILE)
