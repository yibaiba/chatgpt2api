from __future__ import annotations

import unittest
from unittest import mock

from services import api as api_module


class _FakeAccountService:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = list(tokens)
        self.refresh_calls: list[list[str]] = []

    def list_tokens(self) -> list[str]:
        return list(self._tokens)

    def refresh_accounts(self, access_tokens: list[str]) -> dict[str, object]:
        self.refresh_calls.append(list(access_tokens))
        return {"refreshed": len(access_tokens), "errors": [], "items": []}


class AccountRefreshWatcherTests(unittest.TestCase):
    def test_refresh_all_accounts_once_refreshes_every_token(self) -> None:
        fake_account_service = _FakeAccountService(["token-a", "token-b", "token-c"])

        with mock.patch.object(api_module, "account_service", fake_account_service):
            refreshed = api_module.refresh_all_accounts_once()

        self.assertEqual(3, refreshed)
        self.assertEqual([["token-a", "token-b", "token-c"]], fake_account_service.refresh_calls)

    def test_refresh_all_accounts_once_skips_empty_pool(self) -> None:
        fake_account_service = _FakeAccountService([])

        with mock.patch.object(api_module, "account_service", fake_account_service):
            refreshed = api_module.refresh_all_accounts_once()

        self.assertEqual(0, refreshed)
        self.assertEqual([], fake_account_service.refresh_calls)
