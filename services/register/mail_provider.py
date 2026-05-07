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
TEMPMAIL_TRANSIENT_HTTP_STATUSES = {502, 503, 504}
TEMPMAIL_REQUEST_RETRY_ATTEMPTS = 3
TEMPMAIL_REQUEST_RETRY_DELAY_SECONDS = 1.0

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


def _next_domain(domains: list[str]) -> str:
    items = [_clean_text(item) for item in domains if _clean_text(item)]
    if not items:
        return ""
    return random.choice(items)


def _message_matches_email(message: dict[str, Any], address: str) -> bool:
    target = _clean_text(address).lower()
    if not target:
        return False

    def extract_values(value: Any) -> list[str]:
        if isinstance(value, dict):
            values: list[str] = []
            for item in value.values():
                values.extend(extract_values(item))
            return values
        if isinstance(value, list):
            values = []
            for item in value:
                values.extend(extract_values(item))
            return values
        text = _clean_text(value)
        return [text] if text else []

    for key in ("mailbox", "address", "to", "recipient", "recipients"):
        for value in extract_values(message.get(key)):
            if target in value.lower():
                return True
    raw = message.get("raw")
    if isinstance(raw, dict):
        for value in extract_values(raw):
            if target in value.lower():
                return True
    return False


def _build_session(
    conf: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> Session:
    session = Session(impersonate="edge101", verify=True)
    session.headers.update(
        {
            "User-Agent": conf["user_agent"],
            "Accept": "application/json",
        }
    )
    if headers:
        session.headers.update(headers)
    return session


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
        response = None
        for attempt in range(1, TEMPMAIL_REQUEST_RETRY_ATTEMPTS + 1):
            response = self.session.request(
                method.upper(),
                f"https://api.tempmail.lol/v2{path}",
                params=params,
                json=payload,
                timeout=self.conf["request_timeout"],
            )
            if response.status_code in expected:
                data = response.json()
                if not isinstance(data, dict):
                    raise RuntimeError(f"TempMail.lol {method} {path} returned a non-object response")
                return data
            if response.status_code == 429 and "rate limited (free)" in response.text.lower():
                raise RuntimeError("TempMail.lol free tier is rate limited right now; wait a moment or provide an API key")
            if response.status_code in TEMPMAIL_TRANSIENT_HTTP_STATUSES and attempt < TEMPMAIL_REQUEST_RETRY_ATTEMPTS:
                time.sleep(TEMPMAIL_REQUEST_RETRY_DELAY_SECONDS * attempt)
                continue
            break
        raise RuntimeError(
            f"TempMail.lol request failed: {method} {path}, HTTP {getattr(response, 'status_code', 'unknown')}, body={getattr(response, 'text', '')[:300]}"
        )

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


class CloudflareTempMailProvider(BaseMailProvider):
    name = "cloudflare_temp_email"

    def __init__(self, entry: dict[str, Any], conf: dict[str, Any]):
        super().__init__(conf, _clean_text(entry.get("provider_ref")))
        self.api_base = _clean_text(entry.get("api_base")).rstrip("/")
        self.admin_password = _clean_text(entry.get("admin_password"))
        self.domains = [_clean_text(item) for item in entry.get("domains") or [] if _clean_text(item)]
        self.session = _build_session(
            conf,
            headers={
                "Content-Type": "application/json",
            },
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> dict[str, Any]:
        response = self.session.request(
            method.upper(),
            f"{self.api_base}{path}",
            headers=headers,
            params=params,
            json=payload,
            timeout=self.conf["request_timeout"],
        )
        if response.status_code not in expected:
            raise RuntimeError(
                f"CloudflareTempMail request failed: {method} {path}, HTTP {response.status_code}, body={response.text[:300]}"
            )
        if response.status_code == 204:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"CloudflareTempMail {method} {path} returned a non-object response")
        return data

    def create_mailbox(self, username: str | None = None) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/admin/new_address",
            headers={"x-admin-auth": self.admin_password},
            payload={
                "enablePrefix": True,
                "name": username or _random_mailbox_name(),
                "domain": _next_domain(self.domains),
            },
            expected=(200, 201),
        )
        address = _clean_text(data.get("address"))
        token = _clean_text(data.get("jwt"))
        if not address or not token:
            raise RuntimeError("CloudflareTempMail mailbox response is missing address or jwt")
        return {
            "provider": self.name,
            "provider_ref": self.provider_ref,
            "address": address,
            "token": token,
        }

    def fetch_latest_message(self, mailbox: dict[str, Any]) -> dict[str, Any] | None:
        data = self._request(
            "GET",
            "/api/mails",
            headers={"Authorization": f"Bearer {mailbox['token']}"},
            params={"limit": 10, "offset": 0},
        )
        raw_items = data.get("results") or data.get("messages") or []
        items = [item for item in raw_items if isinstance(item, dict)]
        messages = [item for item in items if _message_matches_email(item, _clean_text(mailbox.get("address")))]
        if not messages:
            return None
        item = messages[0]
        text_content, html_content = _extract_content(item)
        sender = item.get("from") or item.get("sender") or ""
        if isinstance(sender, dict):
            sender = sender.get("address") or sender.get("email") or sender.get("name") or ""
        return {
            "provider": self.name,
            "mailbox": mailbox["address"],
            "message_id": _clean_text(item.get("id") or item.get("_id")),
            "subject": _clean_text(item.get("subject")),
            "sender": _clean_text(sender),
            "text_content": text_content,
            "html_content": html_content,
            "received_at": _parse_received_at(
                item.get("createdAt")
                or item.get("created_at")
                or item.get("receivedAt")
                or item.get("date")
                or item.get("timestamp")
            ),
            "raw": item,
        }

    def close(self) -> None:
        self.session.close()


class DuckMailProvider(BaseMailProvider):
    name = "duckmail"

    def __init__(self, entry: dict[str, Any], conf: dict[str, Any]):
        super().__init__(conf, _clean_text(entry.get("provider_ref")))
        self.api_key = _clean_text(entry.get("api_key"))
        self.default_domain = _clean_text(entry.get("default_domain")) or "duckmail.sbs"
        self.session = _build_session(
            conf,
            headers={
                "Content-Type": "application/json",
            },
        )

    @staticmethod
    def _items(data: object) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            raw = data.get("hydra:member") or data.get("member") or data.get("data") or []
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)]
        return []

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str = "",
        use_api_key: bool = False,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 201, 204),
    ) -> object:
        headers = {}
        if use_api_key or token:
            headers["Authorization"] = f"Bearer {self.api_key if use_api_key else token}"
        response = self.session.request(
            method.upper(),
            f"https://api.duckmail.sbs{path}",
            headers=headers,
            params=params,
            json=payload,
            timeout=self.conf["request_timeout"],
        )
        if response.status_code not in expected:
            raise RuntimeError(
                f"DuckMail request failed: {method} {path}, HTTP {response.status_code}, body={response.text[:300]}"
            )
        if response.status_code == 204:
            return {}
        return response.json()

    def create_mailbox(self, username: str | None = None) -> dict[str, Any]:
        domains = self._items(self._request("GET", "/domains", use_api_key=True))
        domain = _clean_text(random.choice(domains).get("domain")) if domains else self.default_domain
        password = "".join(random.choices(string.ascii_letters + string.digits, k=12))
        address = f"{username or _random_mailbox_name()}@{domain}"
        payload = {"address": address, "password": password}
        account = self._request("POST", "/accounts", use_api_key=True, payload=payload)
        token_data = self._request("POST", "/token", use_api_key=True, payload=payload)
        account_id = _clean_text(account.get("id")) if isinstance(account, dict) else ""
        token = _clean_text(token_data.get("token")) if isinstance(token_data, dict) else ""
        return {
            "provider": self.name,
            "provider_ref": self.provider_ref,
            "address": address,
            "token": token,
            "password": password,
            "account_id": account_id,
        }

    def fetch_latest_message(self, mailbox: dict[str, Any]) -> dict[str, Any] | None:
        data = self._request("GET", "/messages", token=_clean_text(mailbox.get("token")), params={"page": 1})
        items = self._items(data)
        if not items:
            return None
        item = items[0]
        message_id = _clean_text(item.get("id") or item.get("@id")).replace("/messages/", "")
        if message_id:
            detail = self._request("GET", f"/messages/{message_id}", token=_clean_text(mailbox.get("token")))
            if isinstance(detail, dict):
                item = detail
        sender = item.get("from") or ""
        if isinstance(sender, dict):
            sender = sender.get("address") or sender.get("name") or ""
        html_content = item.get("html") or ""
        if isinstance(html_content, list):
            html_content = "".join(str(value) for value in html_content)
        return {
            "provider": self.name,
            "mailbox": mailbox["address"],
            "message_id": message_id,
            "subject": _clean_text(item.get("subject")),
            "sender": _clean_text(sender),
            "text_content": _clean_text(item.get("text") or item.get("text_content")),
            "html_content": _clean_text(html_content),
            "received_at": _parse_received_at(
                item.get("createdAt") or item.get("created_at") or item.get("receivedAt") or item.get("date")
            ),
            "raw": item,
        }

    def close(self) -> None:
        self.session.close()


class GptMailProvider(BaseMailProvider):
    name = "gptmail"

    def __init__(self, entry: dict[str, Any], conf: dict[str, Any]):
        super().__init__(conf, _clean_text(entry.get("provider_ref")))
        self.api_key = _clean_text(entry.get("api_key"))
        self.default_domain = _clean_text(entry.get("default_domain"))
        self.session = _build_session(
            conf,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self.api_key,
            },
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> object:
        response = self.session.request(
            method.upper(),
            f"https://mail.chatgpt.org.uk{path}",
            params=params,
            json=payload,
            timeout=self.conf["request_timeout"],
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"GPTMail request failed: {method} {path}, HTTP {response.status_code}, body={response.text[:300]}"
            )
        data = response.json()
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    def create_mailbox(self, username: str | None = None) -> dict[str, Any]:
        payload = {key: value for key, value in {"prefix": username, "domain": self.default_domain}.items() if value}
        data = self._request("POST" if payload else "GET", "/api/generate-email", payload=payload or None)
        if not isinstance(data, dict):
            raise RuntimeError("GPTMail mailbox response returned an invalid payload")
        return {
            "provider": self.name,
            "provider_ref": self.provider_ref,
            "address": _clean_text(data.get("email")),
        }

    def fetch_latest_message(self, mailbox: dict[str, Any]) -> dict[str, Any] | None:
        data = self._request("GET", "/api/emails", params={"email": mailbox["address"]})
        emails = [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        if not emails and isinstance(data, dict):
            raw = data.get("emails") or []
            emails = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
        if not emails:
            return None
        item = max(emails, key=lambda value: (float(value.get("timestamp") or 0), _clean_text(value.get("id"))))
        message_id = _clean_text(item.get("id"))
        if message_id:
            detail = self._request("GET", f"/api/email/{message_id}")
            if isinstance(detail, dict):
                item = detail
        return {
            "provider": self.name,
            "mailbox": mailbox["address"],
            "message_id": message_id,
            "subject": _clean_text(item.get("subject")),
            "sender": _clean_text(item.get("from_address")),
            "text_content": _clean_text(item.get("content")),
            "html_content": _clean_text(item.get("html_content")),
            "received_at": _parse_received_at(item.get("timestamp") or item.get("created_at")),
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


class InbucketMailProvider(BaseMailProvider):
    name = "inbucket"

    def __init__(self, entry: dict[str, Any], conf: dict[str, Any]):
        super().__init__(conf, _clean_text(entry.get("provider_ref")))
        self.api_base = _clean_text(entry.get("api_base")).rstrip("/")
        self.domains = [_clean_text(item) for item in entry.get("domains") or [] if _clean_text(item)]
        self.random_subdomain = bool(entry.get("random_subdomain", True))
        self.session = _build_session(conf)

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected: tuple[int, ...] = (200,),
    ) -> object:
        response = self.session.request(
            method.upper(),
            f"{self.api_base}{path}",
            timeout=self.conf["request_timeout"],
        )
        if response.status_code not in expected:
            raise RuntimeError(
                f"Inbucket request failed: {method} {path}, HTTP {response.status_code}, body={response.text[:300]}"
            )
        if response.status_code == 204:
            return {}
        content_type = _clean_text(response.headers.get("content-type")).lower()
        return response.json() if "application/json" in content_type else response.text

    @staticmethod
    def _mailbox_name(address: str) -> str:
        local_part, _, _ = _clean_text(address).partition("@")
        return local_part

    def create_mailbox(self, username: str | None = None) -> dict[str, Any]:
        base_domain = _next_domain(self.domains)
        if not base_domain:
            raise RuntimeError("inbucket provider requires at least one domain")
        local_part = username or _random_mailbox_name()
        domain = f"{_random_subdomain_label()}.{base_domain}" if self.random_subdomain else base_domain
        address = f"{local_part}@{domain}"
        return {
            "provider": self.name,
            "provider_ref": self.provider_ref,
            "address": address,
            "base_domain": base_domain,
            "mailbox_name": self._mailbox_name(address),
        }

    def fetch_latest_message(self, mailbox: dict[str, Any]) -> dict[str, Any] | None:
        mailbox_name = _clean_text(mailbox.get("mailbox_name")) or self._mailbox_name(_clean_text(mailbox.get("address")))
        if not mailbox_name:
            raise RuntimeError("Inbucket mailbox is missing mailbox_name")
        data = self._request("GET", f"/api/v1/mailbox/{mailbox_name}")
        items = [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        if not items:
            return None
        items.sort(
            key=lambda value: (
                (_parse_received_at(value.get("date")) or datetime.fromtimestamp(0, tz=timezone.utc)).timestamp(),
                _clean_text(value.get("id")),
            ),
            reverse=True,
        )
        address = _clean_text(mailbox.get("address"))
        for item in items:
            message_id = _clean_text(item.get("id"))
            if not message_id:
                continue
            detail = self._request("GET", f"/api/v1/mailbox/{mailbox_name}/{message_id}")
            if not isinstance(detail, dict):
                continue
            header = detail.get("header") if isinstance(detail.get("header"), dict) else {}
            body = detail.get("body") if isinstance(detail.get("body"), dict) else {}
            normalized = {
                "provider": self.name,
                "mailbox": mailbox_name,
                "message_id": message_id,
                "subject": _clean_text(detail.get("subject") or item.get("subject")),
                "sender": _clean_text(detail.get("from") or item.get("from")),
                "text_content": _clean_text(body.get("text")),
                "html_content": _clean_text(body.get("html")),
                "received_at": _parse_received_at(detail.get("date") or item.get("date")),
                "to": header.get("To") if isinstance(header, dict) else None,
                "raw": detail,
            }
            if _message_matches_email(normalized, address):
                return normalized
        return None

    def close(self) -> None:
        self.session.close()


class YydsMailProvider(BaseMailProvider):
    name = "yyds_mail"

    def __init__(self, entry: dict[str, Any], conf: dict[str, Any]):
        super().__init__(conf, _clean_text(entry.get("provider_ref")))
        self.api_base = _clean_text(entry.get("api_base")) or "https://maliapi.215.im/v1"
        self.api_base = self.api_base.rstrip("/")
        self.api_key = _clean_text(entry.get("api_key"))
        self.domains = [_clean_text(item) for item in entry.get("domains") or [] if _clean_text(item)]
        self.subdomain = _clean_text(entry.get("subdomain"))
        self.wildcard = bool(entry.get("wildcard"))
        self.session = _build_session(
            conf,
            headers={
                "Content-Type": "application/json",
            },
        )

    @staticmethod
    def _items(data: object) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            raw = data.get("items") or data.get("messages") or data.get("data") or []
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)]
        return []

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str = "",
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 201, 204),
    ) -> object:
        headers = {"Authorization": f"Bearer {token}"} if token else {"X-API-Key": self.api_key}
        response = self.session.request(
            method.upper(),
            f"{self.api_base}{path}",
            headers=headers,
            params=params,
            json=payload,
            timeout=self.conf["request_timeout"],
        )
        if response.status_code not in expected:
            raise RuntimeError(
                f"YYDSMail request failed: {method} {path}, HTTP {response.status_code}, body={response.text[:300]}"
            )
        if response.status_code == 204:
            return {}
        data = response.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(f"YYDSMail request failed: {data.get('errorCode') or data.get('error')}")
        if isinstance(data, dict) and isinstance(data.get("data"), (dict, list)):
            return data.get("data")
        return data

    def create_mailbox(self, username: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"localPart": username or _random_mailbox_name()}
        if self.domains:
            payload["domain"] = _next_domain(self.domains)
        if self.subdomain:
            payload["subdomain"] = self.subdomain
        data = self._request("POST", "/accounts/wildcard" if self.wildcard else "/accounts", payload=payload)
        if not isinstance(data, dict):
            raise RuntimeError("YYDSMail mailbox response returned an invalid payload")
        address = _clean_text(data.get("address") or data.get("email"))
        token = _clean_text(
            data.get("token")
            or data.get("temp_token")
            or data.get("tempToken")
            or data.get("access_token")
        )
        if not address or not token:
            raise RuntimeError("YYDSMail mailbox response is missing address or token")
        return {
            "provider": self.name,
            "provider_ref": self.provider_ref,
            "address": address,
            "token": token,
            "account_id": _clean_text(data.get("id")),
        }

    def fetch_latest_message(self, mailbox: dict[str, Any]) -> dict[str, Any] | None:
        data = self._request(
            "GET",
            "/messages",
            token=_clean_text(mailbox.get("token")),
            params={"address": mailbox["address"]},
        )
        messages = [item for item in self._items(data) if isinstance(item, dict)]
        if not messages:
            return None
        item = max(
            messages,
            key=lambda value: (
                (
                    _parse_received_at(
                        value.get("createdAt")
                        or value.get("created_at")
                        or value.get("receivedAt")
                        or value.get("date")
                        or value.get("timestamp")
                    )
                    or datetime.fromtimestamp(0, tz=timezone.utc)
                ).timestamp(),
                _clean_text(value.get("id")),
            ),
        )
        message_id = _clean_text(item.get("id") or item.get("message_id"))
        if message_id:
            detail = self._request(
                "GET",
                f"/messages/{message_id}",
                token=_clean_text(mailbox.get("token")),
                params={"address": mailbox["address"]},
            )
            if isinstance(detail, dict):
                item = detail
        text_content, html_content = _extract_content(item)
        sender = item.get("from") or item.get("sender") or ""
        if isinstance(sender, dict):
            sender = sender.get("address") or sender.get("email") or sender.get("name") or ""
        return {
            "provider": self.name,
            "mailbox": mailbox["address"],
            "message_id": message_id,
            "subject": _clean_text(item.get("subject")),
            "sender": _clean_text(sender),
            "text_content": text_content,
            "html_content": html_content,
            "received_at": _parse_received_at(
                item.get("createdAt")
                or item.get("created_at")
                or item.get("receivedAt")
                or item.get("date")
                or item.get("timestamp")
            ),
            "raw": item,
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
        if provider_type == "cloudflare_temp_email":
            if not _clean_text(entry.get("api_base")):
                raise RuntimeError("cloudflare_temp_email provider requires api_base")
            if not _clean_text(entry.get("admin_password")):
                raise RuntimeError("cloudflare_temp_email provider requires admin_password")
            continue
        if provider_type == "tempmail_lol":
            continue
        if provider_type == "duckmail":
            if not _clean_text(entry.get("api_key")):
                raise RuntimeError("duckmail provider requires api_key")
            continue
        if provider_type == "gptmail":
            if not _clean_text(entry.get("api_key")):
                raise RuntimeError("gptmail provider requires api_key")
            continue
        if provider_type == "moemail":
            if not _clean_text(entry.get("api_base")):
                raise RuntimeError("moemail provider requires api_base")
            if not _clean_text(entry.get("api_key")):
                raise RuntimeError("moemail provider requires api_key")
            continue
        if provider_type == "inbucket":
            if not _clean_text(entry.get("api_base")):
                raise RuntimeError("inbucket provider requires api_base")
            if not [_clean_text(item) for item in entry.get("domains") or [] if _clean_text(item)]:
                raise RuntimeError("inbucket provider requires at least one domain")
            continue
        if provider_type == "yyds_mail":
            if not _clean_text(entry.get("api_key")):
                raise RuntimeError("yyds_mail provider requires api_key")
            continue
        raise RuntimeError(f"unsupported mail provider: {provider_type or 'unknown'}")


def _create_provider(mail_config: dict[str, Any], provider: str = "", provider_ref: str = "") -> BaseMailProvider:
    entry = next((dict(item) for item in _entries(mail_config) if provider_ref and item["provider_ref"] == provider_ref), None)
    entry = entry or next((dict(item) for item in _enabled_entries(mail_config) if provider and _clean_text(item.get("type")) == provider), None) or _next_entry(mail_config)
    provider_type = _clean_text(entry.get("type"))
    if provider_type == "cloudflare_temp_email":
        return CloudflareTempMailProvider(entry, _config(mail_config))
    if provider_type == "tempmail_lol":
        return TempMailLolProvider(entry, _config(mail_config))
    if provider_type == "duckmail":
        return DuckMailProvider(entry, _config(mail_config))
    if provider_type == "gptmail":
        return GptMailProvider(entry, _config(mail_config))
    if provider_type == "moemail":
        return MoEmailProvider(entry, _config(mail_config))
    if provider_type == "inbucket":
        return InbucketMailProvider(entry, _config(mail_config))
    if provider_type == "yyds_mail":
        return YydsMailProvider(entry, _config(mail_config))
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
