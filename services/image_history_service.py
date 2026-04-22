from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from services.config import DATA_DIR

IMAGE_HISTORY_FILE = DATA_DIR / "image_history.json"
ALLOWED_CONVERSATION_MODES = {"generate", "edit"}
ALLOWED_CONVERSATION_STATUSES = {"generating", "success", "error"}
ALLOWED_IMAGE_STATUSES = {"loading", "success", "error"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImageHistoryService:
    def __init__(self, store_file: Path):
        self._store_file = store_file
        self._lock = Lock()
        self._items = self._load_items()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _clean_count(value: Any, *, minimum: int = 0, maximum: int | None = None) -> int:
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            count = minimum
        count = max(minimum, count)
        if maximum is not None:
            count = min(maximum, count)
        return count

    def _normalize_reference_image(self, raw: object) -> dict | None:
        if not isinstance(raw, dict):
            return None
        data_url = self._clean_text(raw.get("dataUrl") or raw.get("data_url"))
        if not data_url:
            return None
        return {
            "name": self._clean_text(raw.get("name")),
            "type": self._clean_text(raw.get("type")) or "image/png",
            "dataUrl": data_url,
        }

    def _normalize_image(self, raw: object) -> dict | None:
        if not isinstance(raw, dict):
            return None
        image_id = self._clean_text(raw.get("id"))
        if not image_id:
            return None
        b64_json = self._clean_text(raw.get("b64_json"))
        mime_type = self._clean_text(raw.get("mime_type") or raw.get("mimeType")) or "image/png"
        error = self._clean_text(raw.get("error")) or None
        raw_status = self._clean_text(raw.get("status")).lower()
        if raw_status not in ALLOWED_IMAGE_STATUSES:
            raw_status = "success" if b64_json else "error" if error else "loading"
        return {
            "id": image_id,
            "status": raw_status,
            "b64_json": b64_json or None,
            "mime_type": mime_type,
            "error": error,
        }

    def _normalize_owner(self, raw: object) -> dict | None:
        if not isinstance(raw, dict):
            return None
        owner_role = self._clean_text(raw.get("ownerRole") or raw.get("owner_role")).lower()
        owner_id = self._clean_text(raw.get("ownerId") or raw.get("owner_id"))
        owner_name = self._clean_text(raw.get("ownerName") or raw.get("owner_name"))
        if owner_role not in {"admin", "user"} or not owner_id:
            return None
        return {
            "ownerRole": owner_role,
            "ownerId": owner_id,
            "ownerName": owner_name or ("管理员" if owner_role == "admin" else "普通用户"),
        }

    def _normalize_payload(self, raw: object) -> dict | None:
        if not isinstance(raw, dict):
            return None
        conversation_id = self._clean_text(raw.get("id"))
        prompt = self._clean_text(raw.get("prompt"))
        title = self._clean_text(raw.get("title")) or prompt[:5]
        model = self._clean_text(raw.get("model"))
        if not conversation_id or not prompt or not model:
            return None

        mode = self._clean_text(raw.get("mode")).lower() or "generate"
        if mode not in ALLOWED_CONVERSATION_MODES:
            mode = "generate"

        status = self._clean_text(raw.get("status")).lower() or "success"
        if status not in ALLOWED_CONVERSATION_STATUSES:
            status = "success"

        images = [image for item in list(raw.get("images") or []) if (image := self._normalize_image(item)) is not None]
        if not images:
            return None

        reference_images = [
            image for item in list(raw.get("referenceImages") or raw.get("reference_images") or [])
            if (image := self._normalize_reference_image(item)) is not None
        ]

        created_at = self._clean_text(raw.get("createdAt") or raw.get("created_at")) or _now_iso()
        return {
            "id": conversation_id,
            "title": title,
            "prompt": prompt,
            "model": model,
            "mode": mode,
            "referenceImages": reference_images,
            "count": self._clean_count(raw.get("count"), minimum=1, maximum=10),
            "images": images,
            "createdAt": created_at,
            "status": status,
            "error": self._clean_text(raw.get("error")) or None,
        }

    def _normalize_item(self, raw: object) -> dict | None:
        if not isinstance(raw, dict):
            return None
        owner = self._normalize_owner(raw)
        payload = self._normalize_payload(raw)
        if owner is None or payload is None:
            return None
        return {
            **owner,
            **payload,
            "updatedAt": self._clean_text(raw.get("updatedAt") or raw.get("updated_at")) or payload["createdAt"],
        }

    def _load_items(self) -> list[dict]:
        if not self._store_file.exists():
            return []
        try:
            loaded = json.loads(self._store_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(loaded, list):
            return []
        return [item for raw in loaded if (item := self._normalize_item(raw)) is not None]

    def _save_items(self) -> None:
        self._store_file.parent.mkdir(parents=True, exist_ok=True)
        self._store_file.write_text(json.dumps(self._items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _owner_from_identity(self, identity: dict) -> dict[str, str]:
        if identity.get("role") == "admin":
            return {
                "ownerRole": "admin",
                "ownerId": "admin",
                "ownerName": self._clean_text(identity.get("name")) or "管理员",
            }
        return {
            "ownerRole": "user",
            "ownerId": self._clean_text(identity.get("id")),
            "ownerName": self._clean_text(identity.get("name")) or "普通用户",
        }

    def _can_manage(self, identity: dict, item: dict) -> bool:
        if identity.get("role") == "admin":
            return True
        owner = self._owner_from_identity(identity)
        return item.get("ownerRole") == owner["ownerRole"] and item.get("ownerId") == owner["ownerId"]

    @staticmethod
    def _sort_items(items: list[dict]) -> list[dict]:
        return sorted(items, key=lambda item: str(item.get("createdAt") or ""), reverse=True)

    def list_conversations(self, identity: dict) -> list[dict]:
        with self._lock:
            if identity.get("role") == "admin":
                return self._sort_items([dict(item) for item in self._items])
            return self._sort_items([dict(item) for item in self._items if self._can_manage(identity, item)])

    def save_conversation(self, identity: dict, payload: dict[str, object]) -> dict:
        normalized_payload = self._normalize_payload(payload)
        if normalized_payload is None:
            raise ValueError("conversation payload is invalid")

        with self._lock:
            for index, existing in enumerate(self._items):
                if existing.get("id") != normalized_payload["id"]:
                    continue
                if not self._can_manage(identity, existing):
                    raise PermissionError("conversation not found")
                next_item = self._normalize_item(
                    {
                        **existing,
                        **normalized_payload,
                        "ownerRole": existing.get("ownerRole"),
                        "ownerId": existing.get("ownerId"),
                        "ownerName": existing.get("ownerName"),
                        "updatedAt": _now_iso(),
                    }
                )
                if next_item is None:
                    raise ValueError("conversation payload is invalid")
                self._items[index] = next_item
                self._save_items()
                return dict(next_item)

            owner = self._owner_from_identity(identity)
            next_item = self._normalize_item(
                {
                    **owner,
                    **normalized_payload,
                    "updatedAt": _now_iso(),
                }
            )
            if next_item is None:
                raise ValueError("conversation payload is invalid")
            self._items.append(next_item)
            self._save_items()
            return dict(next_item)

    def delete_conversation(self, identity: dict, conversation_id: str) -> bool:
        normalized_conversation_id = self._clean_text(conversation_id)
        if not normalized_conversation_id:
            return False
        with self._lock:
            remaining: list[dict] = []
            deleted = False
            for item in self._items:
                if item.get("id") == normalized_conversation_id and self._can_manage(identity, item):
                    deleted = True
                    continue
                remaining.append(item)
            if not deleted:
                return False
            self._items = remaining
            self._save_items()
            return True

    def clear_conversations(self, identity: dict) -> int:
        with self._lock:
            if identity.get("role") == "admin":
                removed = len(self._items)
                self._items = []
                if removed:
                    self._save_items()
                return removed

            remaining = [item for item in self._items if not self._can_manage(identity, item)]
            removed = len(self._items) - len(remaining)
            if removed:
                self._items = remaining
                self._save_items()
            return removed


image_history_service = ImageHistoryService(IMAGE_HISTORY_FILE)
