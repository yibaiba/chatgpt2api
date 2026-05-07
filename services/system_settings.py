from __future__ import annotations

from ipaddress import ip_address
import json
import uuid
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlparse

from curl_cffi.requests import Session

from services.config import CONFIG_FILE, _load_json_object

ALLOWED_PROXY_SCHEMES = {"socks5", "socks5h"}
DEFAULT_PROXY_SELECTION_STRATEGY = "round_robin"
DEFAULT_PROXY_VALIDATE_ON_SAVE = True
PROXY_TEST_URL = "https://chatgpt.com/"
PROXY_TEST_TIMEOUT_SECONDS = 15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_proxy_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize_proxy_name(value: object) -> str:
    return str(value or "").strip()


def normalize_proxy_url(value: object) -> str:
    proxy_url = str(value or "").strip()
    if not proxy_url:
        return ""

    parsed = urlparse(proxy_url)
    if parsed.scheme.lower() not in ALLOWED_PROXY_SCHEMES or not parsed.netloc:
        raise ValueError("proxy_url must start with socks5:// or socks5h://")
    return proxy_url


def mask_proxy_url(proxy_url: str) -> str:
    normalized = normalize_proxy_url(proxy_url)
    parsed = urlparse(normalized)
    if parsed.password:
        username = f"{parsed.username}:" if parsed.username else ""
        hostname = str(parsed.hostname or "")
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        netloc = f"{username}***@{hostname}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()
    return normalized


def sanitize_proxy_error_message(proxy_url: str, message: object) -> str:
    text = str(message or "").strip() or "proxy request failed"
    masked_url = mask_proxy_url(proxy_url)
    return text.replace(proxy_url, masked_url)


def _normalize_check_status(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_proxy_entry(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None

    try:
        proxy_url = normalize_proxy_url(raw.get("proxy_url"))
    except ValueError:
        return None
    if not proxy_url:
        return None

    parsed = urlparse(proxy_url)
    return {
        "id": str(raw.get("id") or _new_proxy_id()).strip() or _new_proxy_id(),
        "name": normalize_proxy_name(raw.get("name")),
        "proxy_url": proxy_url,
        "scheme": parsed.scheme.lower(),
        "last_checked_at": str(raw.get("last_checked_at") or "").strip() or None,
        "last_check_ok": raw.get("last_check_ok") if isinstance(raw.get("last_check_ok"), bool) else None,
        "last_check_status": _normalize_check_status(raw.get("last_check_status")),
        "last_check_error": str(raw.get("last_check_error") or "").strip() or None,
        "created_at": str(raw.get("created_at") or _now_iso()).strip() or _now_iso(),
        "updated_at": str(raw.get("updated_at") or raw.get("created_at") or _now_iso()).strip() or _now_iso(),
    }


def serialize_proxy_entry(item: dict) -> dict[str, object]:
    return {
        "id": str(item.get("id") or "").strip(),
        "name": normalize_proxy_name(item.get("name")),
        "proxy_url": normalize_proxy_url(item.get("proxy_url")),
        "scheme": str(item.get("scheme") or "").strip(),
        "last_checked_at": item.get("last_checked_at"),
        "last_check_ok": item.get("last_check_ok"),
        "last_check_status": item.get("last_check_status"),
        "last_check_error": item.get("last_check_error"),
        "created_at": str(item.get("created_at") or "").strip(),
        "updated_at": str(item.get("updated_at") or "").strip(),
    }


def build_proxy_settings(items: list[dict]) -> dict[str, object]:
    return {
        "items": [dict(item) for item in items],
        "enabled": bool(items),
        "selection_strategy": DEFAULT_PROXY_SELECTION_STRATEGY,
        "validate_on_save": DEFAULT_PROXY_VALIDATE_ON_SAVE,
    }


def build_legacy_proxy_settings(items: list[dict]) -> dict[str, object]:
    if not items:
        return {
            "proxy_url": "",
            "enabled": False,
            "scheme": None,
        }

    first = items[0]
    return {
        "proxy_url": str(first.get("proxy_url") or ""),
        "enabled": True,
        "scheme": str(first.get("scheme") or "") or None,
    }


def build_session_proxies(proxy_url: str) -> dict[str, str]:
    normalized = normalize_proxy_url(proxy_url)
    return {
        "http": normalized,
        "https": normalized,
    }


def get_proxy_ip_family(proxy_url: str) -> str | None:
    normalized = normalize_proxy_url(proxy_url)
    hostname = str(urlparse(normalized).hostname or "").strip()
    if not hostname:
        return None
    try:
        address = ip_address(hostname)
    except ValueError:
        return None
    return "ipv6" if address.version == 6 else "ipv4"


def validate_proxy_url(proxy_url: str) -> dict[str, object]:
    normalized = normalize_proxy_url(proxy_url)
    checked_at = _now_iso()
    session = Session(impersonate="edge101", verify=True)
    session.proxies = build_session_proxies(normalized)
    try:
        response = session.get(PROXY_TEST_URL, timeout=PROXY_TEST_TIMEOUT_SECONDS)
        return {
            "last_checked_at": checked_at,
            "last_check_ok": True,
            "last_check_status": int(getattr(response, "status_code", 0) or 0) or None,
            "last_check_error": None,
        }
    except Exception as exc:
        return {
            "last_checked_at": checked_at,
            "last_check_ok": False,
            "last_check_status": None,
            "last_check_error": sanitize_proxy_error_message(normalized, exc),
        }
    finally:
        session.close()


class SystemSettingsService:
    def __init__(self):
        self._lock = Lock()
        self._proxy_pool = self._load_proxy_pool()
        self._round_robin_index = 0

    def _read_raw_config(self) -> dict[str, object]:
        if not CONFIG_FILE.exists() or CONFIG_FILE.is_dir():
            return {}
        return _load_json_object(CONFIG_FILE, name="config.json")

    def _write_raw_config(self, raw_config: dict[str, object]) -> None:
        try:
            CONFIG_FILE.write_text(
                json.dumps(raw_config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise ValueError("config.json is not writable; remove the read-only mount from /app/config.json") from exc

    def _load_proxy_pool(self) -> list[dict]:
        raw_config = self._read_raw_config()
        raw_pool = raw_config.get("proxy_pool")
        items: list[dict] = []
        if isinstance(raw_pool, list):
            items = [item for raw in raw_pool if (item := normalize_proxy_entry(raw)) is not None]
        elif "proxy_url" in raw_config:
            legacy_item = normalize_proxy_entry({"proxy_url": raw_config.get("proxy_url")})
            if legacy_item is not None:
                items = [legacy_item]
        return items

    def _save_proxy_pool(self) -> None:
        raw_config = self._read_raw_config()
        raw_config.pop("proxy_url", None)
        if self._proxy_pool:
            raw_config["proxy_pool"] = [serialize_proxy_entry(item) for item in self._proxy_pool]
        else:
            raw_config.pop("proxy_pool", None)
        self._write_raw_config(raw_config)

    def list_proxy_entries(self) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._proxy_pool]

    def get_proxy_pool_settings(self) -> dict[str, object]:
        return build_proxy_settings(self.list_proxy_entries())

    def get_proxy_settings(self) -> dict[str, object]:
        return build_legacy_proxy_settings(self.list_proxy_entries())

    def _ensure_unique_proxy_url(self, proxy_url: str, *, exclude_id: str | None = None) -> None:
        for item in self._proxy_pool:
            if exclude_id and item["id"] == exclude_id:
                continue
            if item["proxy_url"] == proxy_url:
                raise ValueError("proxy_url already exists")

    def create_proxy_entry(self, name: object, proxy_url: object) -> dict:
        normalized_url = normalize_proxy_url(proxy_url)
        normalized_name = normalize_proxy_name(name)
        validation = validate_proxy_url(normalized_url)
        if not validation["last_check_ok"]:
            raise ValueError(f"proxy validation failed: {validation['last_check_error']}")

        item = normalize_proxy_entry(
            {
                "id": _new_proxy_id(),
                "name": normalized_name,
                "proxy_url": normalized_url,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                **validation,
            }
        )
        if item is None:
            raise ValueError("proxy_url is required")

        with self._lock:
            self._ensure_unique_proxy_url(normalized_url)
            self._proxy_pool.append(item)
            self._save_proxy_pool()
            return dict(item)

    def update_proxy_entry(self, proxy_id: str, updates: dict[str, object]) -> dict | None:
        with self._lock:
            current = next((dict(item) for item in self._proxy_pool if item["id"] == proxy_id), None)
        if current is None:
            return None

        merged = {
            **current,
            **{key: value for key, value in updates.items() if value is not None},
        }
        merged["name"] = normalize_proxy_name(merged.get("name"))
        merged["proxy_url"] = normalize_proxy_url(merged.get("proxy_url"))
        validation = validate_proxy_url(str(merged["proxy_url"]))
        if not validation["last_check_ok"]:
            raise ValueError(f"proxy validation failed: {validation['last_check_error']}")

        merged.update(validation)
        merged["updated_at"] = _now_iso()
        item = normalize_proxy_entry(merged)
        if item is None:
            raise ValueError("proxy_url is required")

        with self._lock:
            self._ensure_unique_proxy_url(item["proxy_url"], exclude_id=proxy_id)
            for index, existing in enumerate(self._proxy_pool):
                if existing["id"] != proxy_id:
                    continue
                self._proxy_pool[index] = item
                self._save_proxy_pool()
                return dict(item)
        return None

    def delete_proxy_entry(self, proxy_id: str) -> bool:
        with self._lock:
            before = len(self._proxy_pool)
            self._proxy_pool = [item for item in self._proxy_pool if item["id"] != proxy_id]
            if len(self._proxy_pool) == before:
                return False
            if self._round_robin_index >= len(self._proxy_pool):
                self._round_robin_index = 0
            self._save_proxy_pool()
            return True

    def replace_proxy_with_single_entry(self, proxy_url: object) -> dict[str, object]:
        normalized_url = normalize_proxy_url(proxy_url)
        items: list[dict]
        if normalized_url:
            validation = validate_proxy_url(normalized_url)
            if not validation["last_check_ok"]:
                raise ValueError(f"proxy validation failed: {validation['last_check_error']}")
            item = normalize_proxy_entry(
                {
                    "id": _new_proxy_id(),
                    "name": "",
                    "proxy_url": normalized_url,
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                    **validation,
                }
            )
            items = [item] if item is not None else []
        else:
            items = []

        with self._lock:
            self._proxy_pool = items
            self._round_robin_index = 0
            self._save_proxy_pool()
        return build_legacy_proxy_settings(items)

    def update_proxy_url(self, proxy_url: object) -> dict[str, object]:
        return self.replace_proxy_with_single_entry(proxy_url)

    def get_next_proxy_entry(self) -> dict | None:
        with self._lock:
            if not self._proxy_pool:
                return None
            preferred_pool = [item for item in self._proxy_pool if get_proxy_ip_family(str(item.get("proxy_url") or "")) == "ipv6"]
            selection_pool = preferred_pool or self._proxy_pool
            index = self._round_robin_index % len(selection_pool)
            self._round_robin_index = (index + 1) % len(selection_pool)
            return dict(selection_pool[index])

    def apply_next_proxy(self, session: Session) -> Session:
        entry = self.get_next_proxy_entry()
        if entry is not None:
            session.proxies = build_session_proxies(str(entry["proxy_url"]))
        return session


system_settings_service = SystemSettingsService()
