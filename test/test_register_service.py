from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
