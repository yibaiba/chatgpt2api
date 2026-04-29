from __future__ import annotations

import base64
import hashlib
import json
import random
import secrets
import string
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

from curl_cffi.requests import Session

from . import mail_provider

AUTH_BASE = "https://auth.openai.com"
PLATFORM_BASE = "https://platform.openai.com"
PLATFORM_OAUTH_CLIENT_ID = "app_2SKx67EdpoN0G6j64rFvigXD"
PLATFORM_OAUTH_REDIRECT_URI = f"{PLATFORM_BASE}/auth/callback"
PLATFORM_OAUTH_AUDIENCE = "https://api.openai.com/v1"
PLATFORM_AUTH0_CLIENT = "eyJuYW1lIjoiYXV0aDAtc3BhLWpzIiwidmVyc2lvbiI6IjEuMjEuMCJ9"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Google Chrome";v="145", "Not?A_Brand";v="8", "Chromium";v="145"'
SEC_CH_UA_FULL_VERSION_LIST = '"Chromium";v="145.0.0.0", "Not:A-Brand";v="99.0.0.0", "Google Chrome";v="145.0.0.0"'
DEFAULT_TIMEOUT = 30

COMMON_HEADERS = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "origin": AUTH_BASE,
    "priority": "u=1, i",
    "user-agent": USER_AGENT,
    "sec-ch-ua": SEC_CH_UA,
    "sec-ch-ua-arch": '"x86_64"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version-list": SEC_CH_UA_FULL_VERSION_LIST,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"10.0.0"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

NAVIGATE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": USER_AGENT,
    "sec-ch-ua": SEC_CH_UA,
    "sec-ch-ua-arch": '"x86_64"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version-list": SEC_CH_UA_FULL_VERSION_LIST,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"10.0.0"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}


def _response_json(response: object) -> dict[str, Any]:
    try:
        data = response.json()  # type: ignore[attr-defined]
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _response_detail_suffix(response: object | None) -> str:
    data = _response_json(response) if response is not None else {}
    if not data:
        return ""
    return f", detail={json.dumps(data, ensure_ascii=False)}"


def _response_error_summary(response: object | None) -> str:
    data = _response_json(response) if response is not None else {}
    error_data = data.get("error")
    if isinstance(error_data, dict):
        code = str(error_data.get("code") or "").strip()
        message = str(error_data.get("message") or "").strip()
        parts = [part for part in (code, message) if part]
        if parts:
            return f": {' - '.join(parts)}"
    return _response_detail_suffix(response)


def _make_trace_headers() -> dict[str, str]:
    trace_id = str(random.getrandbits(64))
    parent_id = str(random.getrandbits(64))
    return {
        "traceparent": f"00-{uuid.uuid4().hex}-{format(int(parent_id), '016x')}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-parent-id": parent_id,
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": trace_id,
    }


def _generate_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _random_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    value = list(
        secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.digits)
        + secrets.choice("!@#$%")
        + "".join(secrets.choice(chars) for _ in range(max(0, length - 4)))
    )
    random.shuffle(value)
    return "".join(value)


def _random_name() -> tuple[str, str]:
    return random.choice(["James", "Robert", "John", "Michael", "David", "Mary", "Emma", "Olivia"]), random.choice(
        ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller"]
    )


def _random_birthdate() -> str:
    return f"{random.randint(1996, 2006):04d}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class SentinelTokenGenerator:
    MAX_ATTEMPTS = 500_000
    ERROR_PREFIX = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D"

    def __init__(self, device_id: str, user_agent: str):
        self.device_id = device_id
        self.user_agent = user_agent
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a_32(text: str) -> str:
        value = 2166136261
        for char in text:
            value ^= ord(char)
            value = (value * 16777619) & 0xFFFFFFFF
        value ^= value >> 16
        value = (value * 2246822507) & 0xFFFFFFFF
        value ^= value >> 13
        value = (value * 3266489909) & 0xFFFFFFFF
        value ^= value >> 16
        return format(value & 0xFFFFFFFF, "08x")

    def _get_config(self) -> list[Any]:
        perf_now = random.uniform(1000, 50000)
        return [
            "1920x1080",
            time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime()),
            4294705152,
            random.random(),
            self.user_agent,
            "https://sentinel.openai.com/sentinel/20260124ceb8/sdk.js",
            None,
            None,
            "en-US",
            random.random(),
            random.choice(["vendorSub-undefined", "plugins-undefined", "mimeTypes-undefined", "hardwareConcurrency-undefined"]),
            random.choice(["location", "implementation", "URL", "documentURI", "compatMode"]),
            random.choice(["Object", "Function", "Array", "Number", "parseFloat", "undefined"]),
            perf_now,
            self.sid,
            "",
            random.choice([4, 8, 12, 16]),
            time.time() * 1000 - perf_now,
        ]

    @staticmethod
    def _b64(data: Any) -> str:
        return base64.b64encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).decode("ascii")

    def generate_requirements_token(self) -> str:
        data = self._get_config()
        data[3] = 1
        data[9] = round(random.uniform(5, 50))
        return "gAAAAAC" + self._b64(data)

    def generate_token(self, seed: str, difficulty: str) -> str:
        start = time.time()
        data = self._get_config()
        difficulty = str(difficulty or "0")
        for attempt in range(self.MAX_ATTEMPTS):
            data[3] = attempt
            data[9] = round((time.time() - start) * 1000)
            payload = self._b64(data)
            if self._fnv1a_32(seed + payload)[: len(difficulty)] <= difficulty:
                return "gAAAAAB" + payload + "~S"
        return "gAAAAAB" + self.ERROR_PREFIX + self._b64(str(None))


def build_sentinel_token(session: Session, device_id: str, flow: str) -> str:
    generator = SentinelTokenGenerator(device_id, USER_AGENT)
    response = session.post(
        "https://sentinel.openai.com/backend-api/sentinel/req",
        data=json.dumps({"p": generator.generate_requirements_token(), "id": device_id, "flow": flow}),
        headers={
            "Content-Type": "text/plain;charset=UTF-8",
            "Referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html",
            "Origin": "https://sentinel.openai.com",
            "User-Agent": USER_AGENT,
            "sec-ch-ua": SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
        timeout=20,
    )
    data = _response_json(response)
    token = str(data.get("token") or "").strip()
    if response.status_code != 200 or not token:
        raise RuntimeError(f"sentinel_req_failed_{response.status_code}")
    proof = data.get("proofofwork") or {}
    p_value = (
        generator.generate_token(str(proof.get("seed") or ""), str(proof.get("difficulty") or "0"))
        if proof.get("required") and proof.get("seed")
        else generator.generate_requirements_token()
    )
    return json.dumps({"p": p_value, "t": "", "c": token, "id": device_id, "flow": flow}, separators=(",", ":"))


def create_session(proxy: str = "") -> Session:
    kwargs: dict[str, Any] = {"impersonate": "edge101", "verify": True}
    if proxy:
        kwargs["proxy"] = proxy
    session = Session(**kwargs)
    session.headers.update({"accept-language": "en-US,en;q=0.9"})
    return session


def request_with_local_retry(session: Session, method: str, url: str, retry_attempts: int = 3, **kwargs: Any):
    last_error = ""
    for _ in range(max(1, retry_attempts)):
        try:
            return session.request(method.upper(), url, timeout=DEFAULT_TIMEOUT, **kwargs), ""
        except Exception as error:
            last_error = str(error)
            time.sleep(1)
    return None, last_error


def validate_otp(session: Session, device_id: str, code: str):
    headers = dict(COMMON_HEADERS)
    headers["referer"] = f"{AUTH_BASE}/email-verification"
    headers["oai-device-id"] = device_id
    headers.update(_make_trace_headers())
    response, error = request_with_local_retry(session, "post", f"{AUTH_BASE}/api/accounts/email-otp/validate", json={"code": code}, headers=headers)
    if response is not None and response.status_code == 200:
        return response, ""
    headers["openai-sentinel-token"] = build_sentinel_token(session, device_id, "authorize_continue")
    return request_with_local_retry(session, "post", f"{AUTH_BASE}/api/accounts/email-otp/validate", json={"code": code}, headers=headers)


def extract_oauth_callback_params_from_url(url: str) -> dict[str, str] | None:
    if not url:
        return None
    try:
        params = parse_qs(urlparse(url).query)
    except Exception:
        return None
    code = str((params.get("code") or [""])[0]).strip()
    if not code:
        return None
    return {
        "code": code,
        "state": str((params.get("state") or [""])[0]).strip(),
        "scope": str((params.get("scope") or [""])[0]).strip(),
    }


def extract_oauth_callback_params_from_consent_session(session: Session, consent_url: str, device_id: str) -> dict[str, str] | None:
    current_url = f"{AUTH_BASE}{consent_url}" if consent_url.startswith("/") else consent_url
    for _ in range(10):
        response = session.get(current_url, headers=NAVIGATE_HEADERS, timeout=30, allow_redirects=False)
        callback = extract_oauth_callback_params_from_url(str(response.url)) or extract_oauth_callback_params_from_url(str(response.headers.get("Location") or "").strip())
        if callback:
            return callback
        location = str(response.headers.get("Location") or "").strip()
        if response.status_code not in (301, 302, 303, 307, 308) or not location:
            break
        current_url = f"{AUTH_BASE}{location}" if location.startswith("/") else location
    raw = session.cookies.get("oai-client-auth-session", domain=".auth.openai.com") or session.cookies.get("oai-client-auth-session")
    if not raw:
        return None
    try:
        first_part = raw.split(".")[0]
        padding = 4 - len(first_part) % 4
        if padding != 4:
            first_part += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(first_part))
        workspace_id = payload["workspaces"][0]["id"]
    except Exception:
        return None
    headers = dict(COMMON_HEADERS)
    headers["referer"] = consent_url
    headers["oai-device-id"] = device_id
    headers.update(_make_trace_headers())
    workspace_response = session.post(f"{AUTH_BASE}/api/accounts/workspace/select", json={"workspace_id": workspace_id}, headers=headers, timeout=30, allow_redirects=False)
    callback = extract_oauth_callback_params_from_url(str(workspace_response.headers.get("Location") or "").strip())
    if callback:
        return callback
    workspace_data = _response_json(workspace_response)
    organizations = ((workspace_data.get("data") or {}).get("orgs") or []) if isinstance(workspace_data, dict) else []
    if not organizations:
        return None
    organization = organizations[0] or {}
    org_id = str(organization.get("id") or "").strip()
    project_id = str(((organization.get("projects") or [{}])[0]).get("id") or "").strip()
    if not org_id:
        return None
    org_headers = dict(COMMON_HEADERS)
    org_headers["referer"] = str(workspace_data.get("continue_url") or consent_url)
    org_headers["oai-device-id"] = device_id
    org_headers.update(_make_trace_headers())
    body = {"org_id": org_id}
    if project_id:
        body["project_id"] = project_id
    org_response = session.post(f"{AUTH_BASE}/api/accounts/organization/select", json=body, headers=org_headers, timeout=30, allow_redirects=False)
    return extract_oauth_callback_params_from_url(str(org_response.headers.get("Location") or "").strip())


def exchange_platform_tokens(proxy: str, session: Session, device_id: str, code_verifier: str, consent_url: str) -> dict[str, str] | None:
    callback = extract_oauth_callback_params_from_consent_session(session, consent_url, device_id)
    if not callback:
        return None
    code = str(callback.get("code") or "").strip()
    if not code:
        return None
    exchange_session = create_session(proxy)
    try:
        response = exchange_session.post(
            f"{AUTH_BASE}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": PLATFORM_OAUTH_REDIRECT_URI,
                "client_id": PLATFORM_OAUTH_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            timeout=60,
        )
    finally:
        exchange_session.close()
    data = _response_json(response)
    if response.status_code != 200 or not data.get("access_token") or not data.get("refresh_token") or not data.get("id_token"):
        return None
    payload = _decode_jwt_payload(str(data.get("id_token") or "")) or _decode_jwt_payload(str(data.get("access_token") or ""))
    return {
        "email": str(payload.get("email") or "").strip(),
        "access_token": str(data.get("access_token") or "").strip(),
        "refresh_token": str(data.get("refresh_token") or "").strip(),
        "id_token": str(data.get("id_token") or "").strip(),
    }


class PlatformRegistrar:
    def __init__(self, proxy: str, mail_config: dict[str, Any], log: Callable[[str, str], None]):
        self.proxy = str(proxy or "").strip()
        self.mail_config = mail_config
        self.log = log
        self.session = create_session(self.proxy)
        self.device_id = str(uuid.uuid4())

    def close(self) -> None:
        self.session.close()

    def _step(self, text: str, level: str = "info") -> None:
        self.log(text, level)

    def _navigate_headers(self, referer: str = "") -> dict[str, str]:
        headers = dict(NAVIGATE_HEADERS)
        if referer:
            headers["referer"] = referer
        return headers

    def _json_headers(self, referer: str) -> dict[str, str]:
        headers = dict(COMMON_HEADERS)
        headers["referer"] = referer
        headers["oai-device-id"] = self.device_id
        headers.update(_make_trace_headers())
        return headers

    def _platform_authorize(self, email: str) -> None:
        self._step("开始 platform authorize")
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")
        _, code_challenge = _generate_pkce()
        params = {
            "issuer": AUTH_BASE,
            "client_id": PLATFORM_OAUTH_CLIENT_ID,
            "audience": PLATFORM_OAUTH_AUDIENCE,
            "redirect_uri": PLATFORM_OAUTH_REDIRECT_URI,
            "device_id": self.device_id,
            "screen_hint": "login_or_signup",
            "max_age": "0",
            "login_hint": email,
            "scope": "openid profile email offline_access",
            "response_type": "code",
            "response_mode": "query",
            "state": secrets.token_urlsafe(32),
            "nonce": secrets.token_urlsafe(32),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "auth0Client": PLATFORM_AUTH0_CLIENT,
        }
        response, error = request_with_local_retry(self.session, "get", f"{AUTH_BASE}/api/accounts/authorize?{urlencode(params)}", headers=self._navigate_headers(f"{PLATFORM_BASE}/"), allow_redirects=True)
        if response is None or response.status_code != 200:
            raise RuntimeError(
                error
                or f"platform_authorize_http_{getattr(response, 'status_code', 'unknown')}{_response_error_summary(response)}"
            )

    def _register_user(self, email: str, password: str) -> None:
        headers = self._json_headers(f"{AUTH_BASE}/create-account/password")
        headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "username_password_create")
        response, error = request_with_local_retry(self.session, "post", f"{AUTH_BASE}/api/accounts/user/register", json={"username": email, "password": password}, headers=headers)
        if response is None or response.status_code != 200:
            data = _response_json(response) if response is not None else {}
            if data.get("message") == "Failed to create account. Please try again.":
                self._step("注册失败提示: 邮箱域名很可能因滥用被封禁，请更换邮箱域名", "warning")
            raise RuntimeError(
                error
                or f"user_register_http_{getattr(response, 'status_code', 'unknown')}{_response_detail_suffix(response)}"
            )

    def _send_otp(self) -> None:
        response, error = request_with_local_retry(self.session, "get", f"{AUTH_BASE}/api/accounts/email-otp/send", headers=self._navigate_headers(f"{AUTH_BASE}/create-account/password"), allow_redirects=True)
        if response is None or response.status_code not in (200, 302):
            raise RuntimeError(error or f"send_otp_http_{getattr(response, 'status_code', 'unknown')}")

    def _validate_otp(self, code: str) -> None:
        response, error = validate_otp(self.session, self.device_id, code)
        if response is None or response.status_code != 200:
            raise RuntimeError(error or f"validate_otp_http_{getattr(response, 'status_code', 'unknown')}")

    def _create_account(self, name: str, birthdate: str) -> None:
        headers = self._json_headers(f"{AUTH_BASE}/about-you")
        headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "oauth_create_account")
        response, error = request_with_local_retry(self.session, "post", f"{AUTH_BASE}/api/accounts/create_account", json={"name": name, "birthdate": birthdate}, headers=headers)
        if response is None or response.status_code not in (200, 302):
            data = _response_json(response) if response is not None else {}
            if data.get("message") == "Failed to create account. Please try again.":
                self._step("创建账号失败提示: 邮箱域名很可能因滥用被封禁，请更换邮箱域名", "warning")
            raise RuntimeError(
                error
                or f"create_account_http_{getattr(response, 'status_code', 'unknown')}{_response_detail_suffix(response)}"
            )

    def _login_and_exchange_tokens(self, email: str, password: str, mailbox: dict[str, Any]) -> dict[str, str]:
        code_verifier, code_challenge = _generate_pkce()
        params = {
            "issuer": AUTH_BASE,
            "client_id": PLATFORM_OAUTH_CLIENT_ID,
            "audience": PLATFORM_OAUTH_AUDIENCE,
            "redirect_uri": PLATFORM_OAUTH_REDIRECT_URI,
            "device_id": self.device_id,
            "screen_hint": "login_or_signup",
            "max_age": "0",
            "login_hint": email,
            "scope": "openid profile email offline_access",
            "response_type": "code",
            "response_mode": "query",
            "state": secrets.token_urlsafe(32),
            "nonce": secrets.token_urlsafe(32),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "auth0Client": PLATFORM_AUTH0_CLIENT,
        }
        response, error = request_with_local_retry(self.session, "get", f"{AUTH_BASE}/api/accounts/authorize?{urlencode(params)}", headers=self._navigate_headers(f"{PLATFORM_BASE}/"), allow_redirects=True)
        if response is None:
            raise RuntimeError(error or "platform_login_authorize_failed")
        headers = self._json_headers(f"{AUTH_BASE}/log-in/password")
        headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "password_verify")
        response, error = request_with_local_retry(self.session, "post", f"{AUTH_BASE}/api/accounts/password/verify", json={"password": password}, headers=headers, allow_redirects=False)
        if response is None or response.status_code != 200:
            raise RuntimeError(error or f"password_verify_http_{getattr(response, 'status_code', 'unknown')}")
        payload = _response_json(response)
        continue_url = str(payload.get("continue_url") or "").strip()
        page_type = str(((payload.get("page") or {}).get("type")) or "")
        if page_type == "email_otp_verification" or "email-verification" in continue_url or "email-otp" in continue_url:
            code = mail_provider.wait_for_code(self.mail_config, mailbox)
            if not code:
                raise RuntimeError("login email verification timed out")
            response, reason = validate_otp(self.session, self.device_id, code)
            if response is None or response.status_code != 200:
                raise RuntimeError(reason or "login email verification failed")
            otp_payload = _response_json(response)
            continue_url = str(otp_payload.get("continue_url") or continue_url).strip()
        if not continue_url:
            continue_url = f"{AUTH_BASE}/sign-in-with-chatgpt/codex/consent"
        tokens = exchange_platform_tokens(self.proxy, self.session, self.device_id, code_verifier, continue_url)
        if not tokens:
            raise RuntimeError("token exchange failed")
        return tokens

    def register(self, config: dict[str, Any]) -> dict[str, str]:
        mailbox = mail_provider.create_mailbox(config["mail"])
        email = str(mailbox.get("address") or "").strip()
        if not email:
            raise RuntimeError("mail provider did not return an email address")
        password = _random_password()
        first_name, last_name = _random_name()
        self._platform_authorize(email)
        self._register_user(email, password)
        self._send_otp()
        code = mail_provider.wait_for_code(config["mail"], mailbox)
        if not code:
            raise RuntimeError("waiting for signup verification code timed out")
        self._validate_otp(code)
        self._create_account(f"{first_name} {last_name}", _random_birthdate())
        tokens = self._login_and_exchange_tokens(email, password, mailbox)
        return {
            "email": email,
            "password": password,
            "access_token": str(tokens.get("access_token") or "").strip(),
            "refresh_token": str(tokens.get("refresh_token") or "").strip(),
            "id_token": str(tokens.get("id_token") or "").strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def register_once(config: dict[str, Any], log: Callable[[str, str], None]) -> dict[str, str]:
    mail_provider.validate_mail_config(config["mail"])
    registrar = PlatformRegistrar(str(config.get("proxy") or ""), config["mail"], log)
    try:
        return registrar.register(config)
    finally:
        registrar.close()
