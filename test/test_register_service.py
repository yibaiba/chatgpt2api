from __future__ import annotations

import threading
import time
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import services.register_service as register_service_module
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

    def test_target_modes_log_waiting_when_goal_is_already_met(self) -> None:
        cases = [
            ("quota", {"target_quota": 5}, "当前总额度 5 / 目标额度 5"),
            ("available", {"target_available": 2}, "当前可用账号 2 / 目标可用账号 2"),
        ]

        for mode, updates, expected_log in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp_dir:
                executor = mock.Mock(side_effect=AssertionError("executor should stay idle when target is already met"))
                service = RegisterService(
                    Path(tmp_dir) / "register.json",
                    accounts_service=_FakeAccountsService(),
                    executor=executor,
                )
                service.update(
                    {
                        "mode": mode,
                        "threads": 1,
                        "check_interval": 1,
                        "mail": {
                            "providers": [
                                {
                                    "type": "tempmail_lol",
                                    "enabled": True,
                                    "api_key": "demo-key",
                                }
                            ]
                        },
                        **updates,
                    }
                )

                started = service.start()
                self.assertTrue(started["enabled"])

                for _ in range(50):
                    snapshot = service.get()
                    if any(expected_log in item["text"] for item in snapshot["logs"]):
                        break
                    time.sleep(0.02)
                else:
                    self.fail(f"target wait log not found for mode={mode}")

                snapshot = service.get()
                self.assertTrue(snapshot["enabled"])
                self.assertEqual(0, snapshot["stats"]["done"])
                self.assertTrue(any("进入巡检等待" in item["text"] for item in snapshot["logs"]))
                executor.assert_not_called()
                service.stop()
                if service._runner is not None:
                    service._runner.join(timeout=1)

    def test_service_auto_restores_enabled_runner_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_file = Path(tmp_dir) / "register.json"
            accounts_service = _FakeAccountsService()
            release_executor = threading.Event()
            entered_executor = threading.Event()

            def blocking_executor(_config, _log):
                entered_executor.set()
                release_executor.wait(timeout=1)
                return {"email": "demo@example.com", "access_token": "token-resumed"}

            initial = RegisterService(store_file, accounts_service=accounts_service, executor=lambda _config, _log: {})
            initial.update(
                {
                    "mode": "total",
                    "total": 3,
                    "threads": 1,
                    "mail": {
                        "providers": [
                            {
                                "type": "tempmail_lol",
                                "enabled": True,
                            }
                        ]
                    },
                }
            )
            initial._config["enabled"] = True
            initial._config["stats"]["job_id"] = "resume-job"
            initial._config["stats"]["done"] = 2
            initial._config["stats"]["success"] = 1
            initial._config["stats"]["fail"] = 1
            initial._save_locked()

            resumed = RegisterService(store_file, accounts_service=accounts_service, executor=blocking_executor)
            try:
                for _ in range(50):
                    if entered_executor.is_set():
                        break
                    time.sleep(0.02)
                else:
                    self.fail("register runner did not auto-resume")

                snapshot = resumed.get()
                self.assertTrue(snapshot["enabled"])
                self.assertEqual("resume-job", snapshot["stats"]["job_id"])
                self.assertGreaterEqual(snapshot["stats"]["done"], 2)
                self.assertTrue(any("自动恢复" in item["text"] for item in snapshot["logs"]))
            finally:
                release_executor.set()
                if resumed._runner is not None:
                    resumed._runner.join(timeout=1)

    def test_consecutive_failures_trigger_runner_backoff_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            executor = mock.Mock(side_effect=RuntimeError("temporary upstream failure"))
            service = RegisterService(
                Path(tmp_dir) / "register.json",
                accounts_service=_FakeAccountsService(),
                executor=executor,
            )
            service.update(
                {
                    "mode": "total",
                    "total": 3,
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

            with (
                mock.patch.object(register_service_module, "REGISTER_FAILURE_BACKOFF_BASE_SECONDS", 0.01),
                mock.patch.object(register_service_module, "REGISTER_FAILURE_BACKOFF_MAX_SECONDS", 0.02),
            ):
                service.start()
                if service._runner is not None:
                    service._runner.join(timeout=1)

            snapshot = service.get()
            self.assertFalse(snapshot["enabled"])
            self.assertEqual(3, snapshot["stats"]["fail"])
            self.assertTrue(any("连续失败 2 次" in item["text"] for item in snapshot["logs"]))
            self.assertEqual(3, executor.call_count)

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

    def test_validate_mail_config_accepts_new_supported_provider_types(self) -> None:
        cases = [
            ("tempmail_lol", {"type": "tempmail_lol", "enabled": True}),
            (
                "cloudflare_temp_email",
                {"type": "cloudflare_temp_email", "enabled": True, "api_base": "https://mail.example.com", "admin_password": "secret"},
            ),
            ("duckmail", {"type": "duckmail", "enabled": True, "api_key": "duck-key"}),
            ("gptmail", {"type": "gptmail", "enabled": True, "api_key": "gpt-key"}),
            (
                "inbucket",
                {"type": "inbucket", "enabled": True, "api_base": "https://mail.example.com", "domains": ["example.com"]},
            ),
            ("yyds_mail", {"type": "yyds_mail", "enabled": True, "api_key": "yyds-key"}),
        ]

        for provider_type, provider in cases:
            with self.subTest(provider_type=provider_type):
                mail_provider.validate_mail_config({"providers": [provider]})

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
    def __init__(self, status_code: int, payload: dict | None = None, text: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text if text is not None else str(self._payload)

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

    def test_password_verify_failure_includes_response_detail(self) -> None:
        authorize_response = _FakeResponse(200, {})
        verify_response = _FakeResponse(
            400,
            {"error": {"code": "invalid_request", "message": "password rejected"}},
        )
        request_mock = mock.Mock(side_effect=[(authorize_response, None), (verify_response, None)])

        with mock.patch(
            "services.register.openai_register.request_with_local_retry",
            request_mock,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"password_verify_http_400: invalid_request - password rejected",
            ):
                self.registrar._login_and_exchange_tokens(
                    "demo@example.com",
                    "Password1!",
                    {"provider": "tempmail_lol", "address": "demo@example.com"},
                )

        self.assertEqual(2, request_mock.call_count)

    def test_password_verify_retries_once_when_challenge_expired(self) -> None:
        authorize_response = _FakeResponse(200, {})
        expired_response = _FakeResponse(
            400,
            {"error": {"code": "registration_login_challenge_expired", "message": "password challenge expired"}},
        )
        success_response = _FakeResponse(
            200,
            {"continue_url": "https://platform.openai.com/auth/callback?code=demo"},
        )
        request_mock = mock.Mock(
            side_effect=[
                (authorize_response, None),
                (expired_response, None),
                (authorize_response, None),
                (success_response, None),
            ]
        )

        with (
            mock.patch(
                "services.register.openai_register.request_with_local_retry",
                request_mock,
            ),
            mock.patch(
                "services.register.openai_register.exchange_platform_tokens",
                return_value={"access_token": "access", "refresh_token": "refresh", "id_token": "id"},
            ) as exchange_mock,
        ):
            tokens = self.registrar._login_and_exchange_tokens(
                "demo@example.com",
                "Password1!",
                {"provider": "tempmail_lol", "address": "demo@example.com"},
            )

        self.assertEqual("access", tokens["access_token"])
        self.assertEqual(4, request_mock.call_count)
        exchange_mock.assert_called_once()
        self.log.assert_any_call("登录密码挑战已过期，刷新授权后重试一次", "warning")

    def test_password_verify_retries_once_when_authorization_step_is_invalid(self) -> None:
        authorize_response = _FakeResponse(200, {})
        invalid_step_response = _FakeResponse(
            400,
            {"error": {"code": "invalid_auth_step", "message": "Invalid authorization step."}},
        )
        success_response = _FakeResponse(
            200,
            {"continue_url": "https://platform.openai.com/auth/callback?code=demo"},
        )
        request_mock = mock.Mock(
            side_effect=[
                (authorize_response, None),
                (invalid_step_response, None),
                (authorize_response, None),
                (success_response, None),
            ]
        )

        with (
            mock.patch(
                "services.register.openai_register.request_with_local_retry",
                request_mock,
            ),
            mock.patch(
                "services.register.openai_register.exchange_platform_tokens",
                return_value={"access_token": "access", "refresh_token": "refresh", "id_token": "id"},
            ) as exchange_mock,
        ):
            tokens = self.registrar._login_and_exchange_tokens(
                "demo@example.com",
                "Password1!",
                {"provider": "tempmail_lol", "address": "demo@example.com"},
            )

        self.assertEqual("access", tokens["access_token"])
        self.assertEqual(4, request_mock.call_count)
        exchange_mock.assert_called_once()
        self.log.assert_any_call("登录授权步骤失效，刷新授权后重试一次", "warning")


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

    def test_tempmail_provider_surfaces_free_tier_rate_limit_hint(self) -> None:
        session = mock.Mock()
        session.headers = {}
        session.request.return_value = _FakeResponse(429, {"error": "Rate limited (free)"}, text='{"error":"Rate limited (free)"}')
        with mock.patch("services.register.mail_provider.Session", return_value=session):
            provider = mail_provider.TempMailLolProvider(
                {
                    "type": "tempmail_lol",
                    "api_key": "",
                },
                {
                    "request_timeout": 30,
                    "wait_timeout": 30,
                    "wait_interval": 2,
                    "user_agent": "Mozilla/5.0",
                },
            )
            try:
                with self.assertRaisesRegex(RuntimeError, "free tier is rate limited"):
                    provider.create_mailbox()
            finally:
                provider.close()


class MailProviderFactoryTests(unittest.TestCase):
    def test_create_mailbox_dispatches_new_provider_types(self) -> None:
        cases = [
            ("cloudflare_temp_email", "CloudflareTempMailProvider"),
            ("duckmail", "DuckMailProvider"),
            ("gptmail", "GptMailProvider"),
            ("inbucket", "InbucketMailProvider"),
            ("yyds_mail", "YydsMailProvider"),
        ]

        for provider_type, class_name in cases:
            with self.subTest(provider_type=provider_type):
                instance = mock.Mock()
                instance.create_mailbox.return_value = {"provider": provider_type, "provider_ref": "demo-ref"}
                with mock.patch.object(mail_provider, class_name, return_value=instance) as provider_class:
                    result = mail_provider.create_mailbox(
                        {
                            "providers": [
                                {
                                    "id": "demo",
                                    "type": provider_type,
                                    "enabled": True,
                                }
                            ]
                        },
                        "demo-user",
                    )

                self.assertEqual(provider_type, result["provider"])
                provider_class.assert_called_once()
                instance.create_mailbox.assert_called_once_with("demo-user")
                instance.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
