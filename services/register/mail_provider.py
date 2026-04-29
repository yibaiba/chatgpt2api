from __future__ import annotations

from datetime import datetime, timezone
from email import message_from_string, policy
import hashlib
import random
import re
import string
import time
from threading import Lock
from typing import Any, Callable, TypeVar

from curl_cffi.requests import Session

ResultT = TypeVar("ResultT")

_provider_lock = Lock()
_provider_index = 0


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _config(mail_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_timeout": max(1.0, float(mail_config.get("request_timeout") or 30)),
        "wait_timeout": max(1.0, float(mail_config.get("wait_timeout") or 30)),
        "wait_interval": max(0.5, float(mail_config.get("wait_interval") or 2)),
        "user_agent": str(mail_config.get("user_agent") or "Mozilla/5.0"),
    }


def _random_mailbox_name() -> str:
    return (
        f"{''.join(random.choices(string.ascii_lowercase, k=5))}"
        f"{''.join(random.choices(string.digits, k=random.randint(1, 3)))}"
        f"{''.join(random.choices(string.ascii_lowercase, k=random.randint(1, 3)))}"
    )


def _random_subdomain_label() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(4, 10)))


def _parse_received_at(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    text = _clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _extract_content(data: dict[str, Any]) -> tuple[str, str]:
    text_content = _clean_text(data.get("text_content") or data.get("text") or data.get("body") or data.get("content"))
    html_content = _clean_text(data.get("html_content") or data.get("html") or data.get("html_body") or data.get("body_html"))
    if text_content or html_content:
        return text_content, html_content
    raw = data.get("raw")
    if not isinstance(raw, str) or not raw.strip():
        return "", ""
    try:
        parsed = message_from_string(raw, policy=policy.default)
    except Exception:
        return raw, ""
    plain: list[str] = []
    html: list[str] = []
    for part in parsed.walk() if parsed.is_multipart() else [parsed]:
        if part.get_content_maintype() == "multipart":
            continue
        try:
            payload = part.get_content()
        except Exception:
            payload = ""
        if not payload:
            continue
        if part.get_content_type() == "text/html":
            html.append(str(payload))
        else:
            plain.append(str(payload))
    return "\n".join(plain).strip(), "\n".join(html).strip()


def _extract_code(message: dict[str, Any]) -> str | None:
    content = f"{message.get('subject', '')}\n{message.get('text_content', '')}\n{message.get('html_content', '')}".strip()
    if not content:
        return None
    match = re.search(r"background-color:\s*#F3F3F3[^>]*>[\s\S]*?(\d{6})[\s\S]*?</p>", content, re.I)
    if match:
        return match.group(1)
    match = re.search(r"(?:Verification code|code is|代码为|验证码)[:\s]*(\d{6})", content, re.I)
    if match and match.group(1) != "177010":
        return match.group(1)
    for code in re.findall(r">\s*(\d{6})\s*<|(?<![#&])\b(\d{6})\b", content):
        value = code[0] or code[1]
        if value and value != "177010":
            return value
    return None


def _message_tracking_ref(message: dict[str, Any]) -> str:
    provider = _clean_text(message.get("provider"))
    mailbox = _clean_text(message.get("mailbox"))
    message_id = _clean_text(message.get("message_id"))
    if message_id:
        return f"id:{provider}:{mailbox}:{message_id}"
    received_at = message.get("received_at")
    received_value = received_at.isoformat() if isinstance(received_at, datetime) else str(received_at or "")
    content = "\n".join(
        _clean_text(message.get(key))
        for key in ("subject", "sender", "text_content", "html_content")
    )
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    return f"content:{provider}:{mailbox}:{received_value}:{digest}"


class BaseMailProvider:
    name = "unknown"

    def __init__(self, conf: dict[str, Any], provider_ref: str = ""):
        self.conf = conf
        self.provider_ref = provider_ref

    def wait_for(self, mailbox: dict[str, Any], on_message: Callable[[dict[str, Any]], ResultT | None]) -> ResultT | None:
        deadline = time.monotonic() + self.conf["wait_timeout"]
        while time.monotonic() < deadline:
            message = self.fetch_latest_message(mailbox)
            if message:
                result = on_message(message)
                if result is not None:
                    return result
            time.sleep(self.conf["wait_interval"])
        return None

    def wait_for_code(self, mailbox: dict[str, Any]) -> str | None:
        seen_value = mailbox.setdefault("_seen_code_message_refs", [])
        if not isinstance(seen_value, list):
            seen_value = []
            mailbox["_seen_code_message_refs"] = seen_value
        seen_refs = {str(item) for item in seen_value}

        def extract_unseen_code(message: dict[str, Any]) -> str | None:
            ref = _message_tracking_ref(message)
            if ref in seen_refs:
                return None
            code = _extract_code(message)
            if code:
                seen_value.append(ref)
                seen_refs.add(ref)
            return code

        return self.wait_for(mailbox, extract_unseen_code)

    def close(self) -> None:
        return None


class TempMailLolProvider(BaseMailProvider):
    name = "tempmail_lol"

    def __init__(self, entry: dict[str, Any], conf: dict[str, Any]):
        super().__init__(conf, _clean_text(entry.get("provider_ref")))
        self.api_key = _clean_text(entry.get("api_key"))
        self.domains = [_clean_text(item) for item in entry.get("domains") or [] if _clean_text(item)]
        self.session = Session(impersonate="edge101", verify=True)
        self.session.headers.update(
            {
                "User-Agent": conf["user_agent"],
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        if self.api_key:
            self.session.headers["Authorization"] = f"Bearer {self.api_key}"

    @staticmethod
    def _resolve_domain(domain: str) -> tuple[str, bool]:
        text = _clean_text(domain).lower()
        if text.startswith("*.") and len(text) > 2:
            return f"{_random_subdomain_label()}.{text[2:]}", True
        return text, False

    def _request(self, method: str, path: str, *, params: dict | None = None, payload: dict | None = None, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        response = self.session.request(
            method.upper(),
            f"https://api.tempmail.lol/v2{path}",
            params=params,
            json=payload,
            timeout=self.conf["request_timeout"],
        )
        if response.status_code not in expected:
            raise RuntimeError(f"TempMail.lol request failed: {method} {path}, HTTP {response.status_code}, body={response.text[:300]}")
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"TempMail.lol {method} {path} returned a non-object response")
        return data

    def create_mailbox(self, username: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.domains:
            domain, force_random_prefix = self._resolve_domain(random.choice(self.domains))
            payload["domain"] = domain
            if force_random_prefix:
                payload["prefix"] = _random_mailbox_name()
        if username and "prefix" not in payload:
            payload["prefix"] = username
        data = self._request("POST", "/inbox/create", payload=payload, expected=(200, 201))
        address = _clean_text(data.get("address"))
        token = _clean_text(data.get("token"))
        if not address or not token:
            raise RuntimeError("TempMail.lol mailbox response is missing address or token")
        return {
            "provider": self.name,
            "provider_ref": self.provider_ref,
            "address": address,
            "token": token,
        }

    def fetch_latest_message(self, mailbox: dict[str, Any]) -> dict[str, Any] | None:
        data = self._request("GET", "/inbox", params={"token": mailbox["token"]})
        items = data.get("emails") or data.get("messages") or []
        messages = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        if not messages:
            return None
        item = max(
            messages,
            key=lambda value: (
                (_parse_received_at(value.get("created_at") or value.get("createdAt") or value.get("date") or value.get("received_at") or value.get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc)).timestamp(),
                _clean_text(value.get("id") or value.get("token")),
            ),
        )
        text_content, html_content = _extract_content(item)
        return {
            "provider": self.name,
            "mailbox": mailbox["address"],
            "message_id": _clean_text(item.get("id") or item.get("token")),
            "subject": _clean_text(item.get("subject")),
            "sender": _clean_text(item.get("from") or item.get("from_address")),
            "text_content": text_content,
            "html_content": html_content,
            "received_at": _parse_received_at(item.get("created_at") or item.get("createdAt") or item.get("date") or item.get("received_at") or item.get("timestamp")),
            "raw": item,
        }

    def close(self) -> None:
        self.session.close()


class MoEmailProvider(BaseMailProvider):
    name = "moemail"

    def __init__(self, entry: dict[str, Any], conf: dict[str, Any]):
        super().__init__(conf, _clean_text(entry.get("provider_ref")))
        self.api_base = _clean_text(entry.get("api_base")).rstrip("/")
        self.api_key = _clean_text(entry.get("api_key"))
        self.domains = [_clean_text(item) for item in entry.get("domains") or [] if _clean_text(item)]
        try:
            self.expiry_time = max(0, int(entry.get("expiry_time") or 0))
        except (TypeError, ValueError):
            self.expiry_time = 0
        self.session = Session(impersonate="edge101", verify=True)
        self.session.headers.update(
            {
                "User-Agent": conf["user_agent"],
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-Key": self.api_key,
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> dict[str, Any]:
        response = self.session.request(
            method.upper(),
            f"{self.api_base}{path}",
            params=params,
            json=payload,
            timeout=self.conf["request_timeout"],
        )
        if response.status_code not in expected:
            raise RuntimeError(
                f"MoEmail request failed: {method} {path}, HTTP {response.status_code}, body={response.text[:300]}"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"MoEmail {method} {path} returned a non-object response")
        return data

    def create_mailbox(self, username: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": username or _random_mailbox_name(),
            "expiryTime": self.expiry_time,
        }
        if self.domains:
            payload["domain"] = random.choice(self.domains)
        data = self._request("POST", "/api/emails/generate", payload=payload, expected=(200, 201))
        address = _clean_text(data.get("email"))
        email_id = _clean_text(data.get("id") or data.get("email_id"))
        if not address or not email_id:
            raise RuntimeError("MoEmail mailbox response is missing email or id")
        return {
            "provider": self.name,
            "provider_ref": self.provider_ref,
            "address": address,
            "email_id": email_id,
        }

    def fetch_latest_message(self, mailbox: dict[str, Any]) -> dict[str, Any] | None:
        email_id = _clean_text(mailbox.get("email_id"))
        if not email_id:
            raise RuntimeError("MoEmail mailbox is missing email_id")
        data = self._request("GET", f"/api/emails/{email_id}")
        items = data.get("messages") or []
        messages = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        if not messages:
            return None
        item = max(
            messages,
            key=lambda value: (
                (_parse_received_at(value.get("createdAt") or value.get("created_at") or value.get("receivedAt") or value.get("date") or value.get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc)).timestamp(),
                _clean_text(value.get("id") or value.get("message_id") or value.get("_id")),
            ),
        )
        message_id = _clean_text(item.get("id") or item.get("message_id") or item.get("_id"))
        detail = self._request("GET", f"/api/emails/{email_id}/{message_id}") if message_id else {"message": item}
        message = detail.get("message") if isinstance(detail.get("message"), dict) else detail
        sender = message.get("from") or message.get("sender") or ""
        if isinstance(sender, dict):
            sender = sender.get("address") or sender.get("email") or sender.get("name") or ""
        text_content, html_content = _extract_content(message)
        return {
            "provider": self.name,
            "mailbox": mailbox["address"],
            "message_id": message_id,
            "subject": _clean_text(message.get("subject") or item.get("subject")),
            "sender": _clean_text(sender),
            "text_content": text_content,
            "html_content": html_content,
            "received_at": _parse_received_at(
                message.get("createdAt")
                or message.get("created_at")
                or message.get("receivedAt")
                or message.get("date")
                or message.get("timestamp")
                or item.get("createdAt")
                or item.get("created_at")
                or item.get("receivedAt")
                or item.get("date")
                or item.get("timestamp")
            ),
            "raw": detail,
        }

    def close(self) -> None:
        self.session.close()


def _entries(mail_config: dict[str, Any]) -> list[dict[str, Any]]:
    items = mail_config.get("providers") if isinstance(mail_config.get("providers"), list) else []
    return [{**item, "provider_ref": _clean_text(item.get("id")) or f"{item.get('type', 'provider')}#{index + 1}"} for index, item in enumerate(items) if isinstance(item, dict)]


def _enabled_entries(mail_config: dict[str, Any]) -> list[dict[str, Any]]:
    items = [item for item in _entries(mail_config) if item.get("enabled")]
    if not items:
        raise RuntimeError("mail.providers has no enabled provider")
    return items


def _next_entry(mail_config: dict[str, Any]) -> dict[str, Any]:
    global _provider_index
    items = _enabled_entries(mail_config)
    if len(items) == 1:
        return dict(items[0])
    with _provider_lock:
        entry = dict(items[_provider_index % len(items)])
        _provider_index = (_provider_index + 1) % len(items)
        return entry


def validate_mail_config(mail_config: dict[str, Any]) -> None:
    for entry in _enabled_entries(mail_config):
        provider_type = _clean_text(entry.get("type"))
        if provider_type == "tempmail_lol":
            if not _clean_text(entry.get("api_key")):
                raise RuntimeError("tempmail_lol provider requires api_key")
            continue
        if provider_type == "moemail":
            if not _clean_text(entry.get("api_base")):
                raise RuntimeError("moemail provider requires api_base")
            if not _clean_text(entry.get("api_key")):
                raise RuntimeError("moemail provider requires api_key")
            continue
        raise RuntimeError(f"unsupported mail provider: {provider_type or 'unknown'}")


def _create_provider(mail_config: dict[str, Any], provider: str = "", provider_ref: str = "") -> BaseMailProvider:
    entry = next((dict(item) for item in _entries(mail_config) if provider_ref and item["provider_ref"] == provider_ref), None)
    entry = entry or next((dict(item) for item in _enabled_entries(mail_config) if provider and _clean_text(item.get("type")) == provider), None) or _next_entry(mail_config)
    provider_type = _clean_text(entry.get("type"))
    if provider_type == "tempmail_lol":
        return TempMailLolProvider(entry, _config(mail_config))
    if provider_type == "moemail":
        return MoEmailProvider(entry, _config(mail_config))
    raise RuntimeError(f"unsupported mail provider: {provider_type or 'unknown'}")


def create_mailbox(mail_config: dict[str, Any], username: str | None = None) -> dict[str, Any]:
    provider = _create_provider(mail_config)
    try:
        return provider.create_mailbox(username)
    finally:
        provider.close()


def wait_for_code(mail_config: dict[str, Any], mailbox: dict[str, Any]) -> str | None:
    provider = _create_provider(mail_config, _clean_text(mailbox.get("provider")), _clean_text(mailbox.get("provider_ref")))
    try:
        return provider.wait_for_code(mailbox)
    finally:
        provider.close()
