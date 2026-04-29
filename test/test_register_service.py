from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.register import mail_provider
from services.register.openai_register import PlatformRegistrar
from services.register_service import RegisterService


class _FakeAccountsService:
    def __init__(self) -> None:
        self.items = [
            {"status": "正常", "quota": 5, "imageQuotaUnknown": False},
            {"status": "正常", "quota": 0, "imageQuotaUnknown": True},
            {"status": "限流", "quota": 9, "imageQuotaUnknown": False},
        ]
        self.added_tokens: list[str] = []
        self.refreshed_tokens: list[str] = []

    def list_accounts(self):
        return list(self.items)

    def add_accounts(self, tokens: list[str]):
        self.added_tokens.extend(tokens)
        return {"added": len(tokens), "skipped": 0, "items": []}

    def refresh_accounts(self, tokens: list[str]):
        self.refreshed_tokens.extend(tokens)
        return {"refreshed": len(tokens), "errors": [], "items": []}


class _SequenceMailProvider(mail_provider.BaseMailProvider):
    def __init__(self, messages: list[dict]) -> None:
        super().__init__({"wait_timeout": 0.05, "wait_interval": 0.001})
        self._messages = messages
        self._index = 0

    def fetch_latest_message(self, _mailbox: dict[str, object]) -> dict | None:
        if not self._messages:
            return None
        if self._index >= len(self._messages):
            return self._messages[-1]
        message = self._messages[self._index]
        self._index += 1
        return message


class RegisterServiceTests(unittest.TestCase):
    def test_update_normalizes_and_persists_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json", accounts_service=_FakeAccountsService(), executor=lambda _config, _log: {})

            updated = service.update(
                {
                    "threads": "99",
                    "total": "0",
                    "mode": "quota",
                    "target_quota": "120",
                    "check_interval": "0",
                    "mail": {
                        "request_timeout": "45",
                        "providers": [
                            {
                                "type": "tempmail_lol",
                                "enabled": True,
                                "api_key": "demo-key",
                                "domains": ["demo.example"],
                            }
                        ],
                    },
                }
            )

            self.assertEqual(32, updated["threads"])
            self.assertEqual(1, updated["total"])
            self.assertEqual("quota", updated["mode"])
            self.assertEqual(120, updated["target_quota"])
            self.assertEqual(1, updated["check_interval"])
            self.assertEqual(45, updated["mail"]["request_timeout"])
            self.assertEqual(2, updated["stats"]["current_available"])
            self.assertEqual(5, updated["stats"]["current_quota"])

            reloaded = RegisterService(Path(tmp_dir) / "register.json", accounts_service=_FakeAccountsService())
            self.assertEqual("tempmail_lol", reloaded.get()["mail"]["providers"][0]["type"])

    def test_update_persists_moemail_provider_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json", accounts_service=_FakeAccountsService(), executor=lambda _config, _log: {})

            updated = service.update(
                {
                    "mail": {
                        "providers": [
                            {
                                "type": "moemail",
                                "enabled": True,
                                "api_key": "mo-key",
                                "api_base": "https://mail.example.com/",
                                "expiry_time": "600",
                                "domains": ["alpha.example", "beta.example"],
                            }
                        ]
                    }
                }
            )

            provider = updated["mail"]["providers"][0]
            self.assertEqual("moemail", provider["type"])
            self.assertEqual("mo-key", provider["api_key"])
            self.assertEqual("https://mail.example.com/", provider["api_base"])
            self.assertEqual(600, provider["expiry_time"])
            self.assertEqual(["alpha.example", "beta.example"], provider["domains"])

            reloaded = RegisterService(Path(tmp_dir) / "register.json", accounts_service=_FakeAccountsService())
            reloaded_provider = reloaded.get()["mail"]["providers"][0]
            self.assertEqual("moemail", reloaded_provider["type"])
            self.assertEqual("https://mail.example.com/", reloaded_provider["api_base"])
            self.assertEqual(600, reloaded_provider["expiry_time"])

    def test_start_requires_enabled_supported_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json", accounts_service=_FakeAccountsService(), executor=lambda _config, _log: {})

            with self.assertRaisesRegex(ValueError, "mail.providers has no enabled provider"):
                service.start()

    def test_start_runs_executor_and_imports_access_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            accounts_service = _FakeAccountsService()

            def fake_executor(_config, log):
                log("模拟注册成功", "success")
                return {"email": "demo@example.com", "access_token": "token-1"}

            service = RegisterService(
                Path(tmp_dir) / "register.json",
                accounts_service=accounts_service,
                executor=fake_executor,
            )
            service.update(
                {
                    "total": 1,
                    "threads": 1,
                    "mail": {
                        "providers": [
                            {
                                "type": "tempmail_lol",
                                "enabled": True,
                                "api_key": "demo-key",
                            }
                        ]
                    },
                }
            )

            started = service.start()
            self.assertTrue(started["enabled"])
            if service._runner is not None:
                service._runner.join(timeout=1)
            finished = service.get()

            self.assertFalse(finished["enabled"])
            self.assertEqual(1, finished["stats"]["success"])
            self.assertEqual(["token-1"], accounts_service.added_tokens)
            self.assertEqual(["token-1"], accounts_service.refreshed_tokens)
            self.assertTrue(any("模拟注册成功" in item["text"] for item in finished["logs"]))

    def test_start_accepts_moemail_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            accounts_service = _FakeAccountsService()

            def fake_executor(_config, log):
                log("使用 moemail 模拟注册成功", "success")
                return {"email": "demo@example.com", "access_token": "token-mo"}

            service = RegisterService(
                Path(tmp_dir) / "register.json",
                accounts_service=accounts_service,
                executor=fake_executor,
            )
            service.update(
                {
                    "total": 1,
                    "threads": 1,
                    "mail": {
                        "providers": [
                            {
                                "type": "moemail",
                                "enabled": True,
                                "api_key": "demo-key",
                                "api_base": "https://mail.example.com",
                            }
                        ]
                    },
                }
            )

            started = service.start()
            self.assertTrue(started["enabled"])
            if service._runner is not None:
                service._runner.join(timeout=1)
            finished = service.get()

            self.assertFalse(finished["enabled"])
            self.assertEqual(1, finished["stats"]["success"])
            self.assertEqual(["token-mo"], accounts_service.added_tokens)
            self.assertEqual(["token-mo"], accounts_service.refreshed_tokens)

    def test_start_rejects_moemail_without_api_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json", accounts_service=_FakeAccountsService(), executor=lambda _config, _log: {})
            service.update(
                {
                    "mail": {
                        "providers": [
                            {
                                "type": "moemail",
                                "enabled": True,
                                "api_key": "demo-key",
                            }
                        ]
                    }
                }
            )

            with self.assertRaisesRegex(ValueError, "moemail provider requires api_base"):
                service.start()

    def test_default_mail_wait_interval_uses_faster_polling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json", accounts_service=_FakeAccountsService())

            self.assertEqual(2, service.get()["mail"]["wait_interval"])


class MailProviderPollingTests(unittest.TestCase):
    def test_wait_for_code_skips_seen_message_refs(self) -> None:
        provider = _SequenceMailProvider(
            [
                {
                    "provider": "test",
                    "mailbox": "demo@example.com",
                    "message_id": "msg-1",
                    "subject": "Verification code",
                    "text_content": "Verification code: 123456",
                    "html_content": "",
                },
                {
                    "provider": "test",
                    "mailbox": "demo@example.com",
                    "message_id": "msg-1",
                    "subject": "Verification code",
                    "text_content": "Verification code: 123456",
                    "html_content": "",
                },
                {
                    "provider": "test",
                    "mailbox": "demo@example.com",
                    "message_id": "msg-2",
                    "subject": "Verification code",
                    "text_content": "Verification code: 654321",
                    "html_content": "",
                },
            ]
        )
        mailbox = {"address": "demo@example.com"}

        first_code = provider.wait_for_code(mailbox)
        second_code = provider.wait_for_code(mailbox)

        self.assertEqual("123456", first_code)
        self.assertEqual("654321", second_code)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class OpenAIRegisterErrorReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = mock.Mock()
        self.log = mock.Mock()
        self.create_session = mock.patch(
            "services.register.openai_register.create_session",
            return_value=self.session,
        )
        self.create_session.start()
        self.addCleanup(self.create_session.stop)
        self.build_sentinel_token = mock.patch(
            "services.register.openai_register.build_sentinel_token",
            return_value="sentinel-token",
        )
        self.build_sentinel_token.start()
        self.addCleanup(self.build_sentinel_token.stop)
        self.registrar = PlatformRegistrar("", {"providers": []}, self.log)

    def tearDown(self) -> None:
        self.registrar.close()

    def test_platform_authorize_includes_error_code_and_message(self) -> None:
        response = _FakeResponse(
            429,
            {"error": {"code": "rate_limited", "message": "too many attempts"}},
        )

        with mock.patch(
            "services.register.openai_register.request_with_local_retry",
            return_value=(response, None),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"platform_authorize_http_429: rate_limited - too many attempts",
            ):
                self.registrar._platform_authorize("demo@example.com")

    def test_register_user_includes_response_detail_and_warning(self) -> None:
        response = _FakeResponse(
            400,
            {"message": "Failed to create account. Please try again.", "trace_id": "trace-1"},
        )

        with mock.patch(
            "services.register.openai_register.request_with_local_retry",
            return_value=(response, None),
        ):
            with self.assertRaises(RuntimeError) as context:
                self.registrar._register_user("demo@example.com", "Password1!")

        self.assertIn("user_register_http_400", str(context.exception))
        self.assertIn('"trace_id": "trace-1"', str(context.exception))
        self.log.assert_any_call(
            "注册失败提示: 邮箱域名很可能因滥用被封禁，请更换邮箱域名",
            "warning",
        )

    def test_create_account_includes_response_detail_and_warning(self) -> None:
        response = _FakeResponse(
            400,
            {"message": "Failed to create account. Please try again.", "trace_id": "trace-2"},
        )

        with mock.patch(
            "services.register.openai_register.request_with_local_retry",
            return_value=(response, None),
        ):
            with self.assertRaises(RuntimeError) as context:
                self.registrar._create_account("Demo User", "2000-01-01")

        self.assertIn("create_account_http_400", str(context.exception))
        self.assertIn('"trace_id": "trace-2"', str(context.exception))
        self.log.assert_any_call(
            "创建账号失败提示: 邮箱域名很可能因滥用被封禁，请更换邮箱域名",
            "warning",
        )

    def test_validate_otp_includes_response_message(self) -> None:
        response = _FakeResponse(400, {"message": "expired otp"})

        with mock.patch(
            "services.register.openai_register.validate_otp",
            return_value=(response, None),
        ):
            with self.assertRaisesRegex(RuntimeError, r"validate_otp_http_400: expired otp"):
                self.registrar._validate_otp("123456")

    def test_login_authorize_failure_stops_before_password_verify(self) -> None:
        response = _FakeResponse(
            429,
            {"error": {"code": "rate_limited", "message": "too many attempts"}},
        )
        request_mock = mock.Mock(return_value=(response, None))

        with mock.patch(
            "services.register.openai_register.request_with_local_retry",
            request_mock,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"platform_login_authorize_http_429: rate_limited - too many attempts",
            ):
                self.registrar._login_and_exchange_tokens(
                    "demo@example.com",
                    "Password1!",
                    {"provider": "tempmail_lol", "address": "demo@example.com"},
                )

        self.assertEqual(1, request_mock.call_count)


class MailProviderSecurityTests(unittest.TestCase):
    def test_moemail_provider_enables_tls_verification(self) -> None:
        session = mock.Mock()
        session.headers = mock.Mock()
        with mock.patch("services.register.mail_provider.Session", return_value=session) as session_class:
            provider = mail_provider.MoEmailProvider(
                {
                    "type": "moemail",
                    "api_base": "https://mail.example.com",
                    "api_key": "demo-key",
                    "domains": ["alpha.example"],
                },
                {
                    "request_timeout": 30,
                    "wait_timeout": 30,
                    "wait_interval": 2,
                    "user_agent": "Mozilla/5.0",
                },
            )
            try:
                session_class.assert_called_once_with(impersonate="edge101", verify=True)
            finally:
                provider.close()


if __name__ == "__main__":
    unittest.main()
