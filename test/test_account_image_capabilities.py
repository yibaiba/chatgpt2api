from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_service import AccountService
from services.config import config
from services.storage.factory import build_account_store, build_account_store_for_backend, get_account_storage_info
from services.storage.json_storage import JsonAccountStore
from services.storage.migrate import migrate_accounts
from services.storage.sqlite_storage import SqliteAccountStore
from services.utils import anonymize_token


class _MemoryAccountStore:
    def __init__(self, items: list[dict] | None = None) -> None:
        self._items = [dict(item) for item in (items or [])]
        self.saved_snapshots: list[list[dict]] = []

    def load_accounts(self) -> list[dict]:
        return [dict(item) for item in self._items]

    def save_accounts(self, accounts: list[dict]) -> None:
        snapshot = [dict(item) for item in accounts]
        self.saved_snapshots.append(snapshot)
        self._items = snapshot


class AccountCapabilityTests(unittest.TestCase):
    def test_unknown_quota_accounts_are_available_only_when_not_throttled(self) -> None:
        self.assertFalse(
            AccountService._is_image_account_available(
                {"status": "限流", "image_quota_unknown": True, "quota": 0}
            )
        )
        self.assertTrue(
            AccountService._is_image_account_available(
                {"status": "正常", "image_quota_unknown": True, "quota": 0}
            )
        )

    def test_prolite_variants_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(Path(tmp_dir) / "accounts.json")
            self.assertEqual(service._normalize_account_type("prolite"), "ProLite")
            self.assertEqual(service._normalize_account_type("pro_lite"), "ProLite")

    def test_search_account_type_ignores_unrelated_scalar_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(Path(tmp_dir) / "accounts.json")
            self.assertIsNone(
                service._search_account_type(
                    {
                        "amr": ["pwd", "otp", "mfa"],
                        "chatgpt_compute_residency": "no_constraint",
                        "chatgpt_data_residency": "no_constraint",
                        "user_id": "user-I52GFfLGFM0dokFk2dBiKEBn",
                    }
                )
            )

    def test_mark_image_result_does_not_consume_unknown_quota(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(Path(tmp_dir) / "accounts.json")
            service.add_accounts(["token-1"])
            service.update_account(
                "token-1",
                {
                    "status": "正常",
                    "quota": 0,
                    "image_quota_unknown": True,
                },
            )

            updated = service.mark_image_result("token-1", success=True)

            self.assertIsNotNone(updated)
            self.assertEqual(updated["quota"], 0)
            self.assertEqual(updated["status"], "正常")
            self.assertTrue(updated["image_quota_unknown"])

    def test_delete_accounts_by_status_only_removes_matching_abnormal_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(Path(tmp_dir) / "accounts.json")
            service.add_accounts(["token-normal", "token-abnormal", "token-limited", "token-disabled"])
            with mock.patch.object(
                type(config),
                "auto_remove_rate_limited_accounts",
                new_callable=mock.PropertyMock,
                return_value=False,
            ):
                service.update_account("token-normal", {"status": "正常"})
                service.update_account("token-abnormal", {"status": "异常"})
                service.update_account("token-limited", {"status": "限流"})
                service.update_account("token-disabled", {"status": "禁用"})

                result = service.delete_accounts_by_status(
                    ["token-normal", "token-abnormal", "token-limited", "token-disabled"]
                )

            self.assertEqual(2, result["removed"])
            self.assertCountEqual(["token-abnormal", "token-disabled"], result["removed_tokens"])
            remaining_tokens = [item["access_token"] for item in service.list_accounts()]
            self.assertCountEqual(["token-normal", "token-limited"], remaining_tokens)

    def test_update_account_auto_removes_rate_limited_account_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(Path(tmp_dir) / "accounts.json")
            service.add_accounts(["token-1"])

            with mock.patch.object(
                type(config),
                "auto_remove_rate_limited_accounts",
                new_callable=mock.PropertyMock,
                return_value=True,
            ):
                updated = service.update_account("token-1", {"status": "限流"})

            self.assertIsNone(updated)
            self.assertEqual([], service.list_accounts())

    def test_mark_image_result_auto_removes_rate_limited_account_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(Path(tmp_dir) / "accounts.json")
            service.add_accounts(["token-1"])
            service.update_account("token-1", {"status": "正常", "quota": 1, "image_quota_unknown": False})

            with mock.patch.object(
                type(config),
                "auto_remove_rate_limited_accounts",
                new_callable=mock.PropertyMock,
                return_value=True,
            ):
                updated = service.mark_image_result("token-1", success=True)

            self.assertIsNone(updated)
            self.assertEqual([], service.list_accounts())

    def test_account_service_uses_store_backend_for_load_and_save(self) -> None:
        store = _MemoryAccountStore(
            [
                {
                    "access_token": "token-1",
                    "status": "正常",
                    "quota": 2,
                }
            ]
        )

        service = AccountService(store)
        added = service.add_accounts(["token-2"])

        self.assertEqual(["token-1", "token-2"], sorted(service.list_tokens()))
        self.assertEqual(1, added["added"])
        self.assertTrue(store.saved_snapshots)
        self.assertEqual(["token-1", "token-2"], sorted(item["access_token"] for item in store.saved_snapshots[-1]))

    def test_account_service_rebind_store_switches_runtime_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "accounts.json"
            sqlite_path = Path(tmp_dir) / "accounts.sqlite3"
            JsonAccountStore(json_path).save_accounts(
                [{"access_token": "token-json", "status": "正常", "quota": 1}]
            )
            SqliteAccountStore(sqlite_path).save_accounts(
                [{"access_token": "token-sqlite", "status": "正常", "quota": 2}]
            )

            service = AccountService(JsonAccountStore(json_path))
            self.assertEqual(["token-json"], service.list_tokens())

            items = service.rebind_store(SqliteAccountStore(sqlite_path))

            self.assertEqual(["token-sqlite"], service.list_tokens())
            self.assertEqual(sqlite_path, service.store_file)
            self.assertEqual("token-sqlite", items[0]["access_token"])

    def test_json_account_store_round_trips_accounts_file_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "accounts.json"
            service = AccountService(JsonAccountStore(path))

            service.add_accounts(["token-1"])
            service.update_account("token-1", {"status": "正常", "quota": 3})

            reloaded = AccountService(JsonAccountStore(path))
            account = reloaded.get_account("token-1")

            self.assertIsNotNone(account)
            self.assertEqual("正常", account["status"])
            self.assertEqual(3, account["quota"])
            self.assertEqual(["token-1"], reloaded.list_tokens())

    def test_json_account_store_save_is_not_plain_write_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "accounts.json"
            store = JsonAccountStore(path)
            payload = [{"access_token": "token-1", "status": "正常", "quota": 1}]

            with mock.patch("pathlib.Path.write_text", side_effect=AssertionError("write_text should not be used")):
                store.save_accounts(payload)

            self.assertEqual(payload, json.loads(path.read_text(encoding="utf-8")))

    def test_json_account_store_ignores_invalid_json_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "accounts.json"
            path.write_text('{"access_token": "token-1"}', encoding="utf-8")

            self.assertEqual([], JsonAccountStore(path).load_accounts())

    def test_build_account_store_uses_json_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "accounts.json"
            fake_config = mock.Mock(storage_backend="json", accounts_file=path)

            store = build_account_store(fake_config)

            self.assertIsInstance(store, JsonAccountStore)
            self.assertEqual(path, store.path)

    def test_build_account_store_uses_sqlite_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "accounts.sqlite3"
            fake_config = mock.Mock(storage_backend="sqlite", storage_sqlite_path=path)

            store = build_account_store(fake_config)

            self.assertIsInstance(store, SqliteAccountStore)
            self.assertEqual(path, store.path)

    def test_build_account_store_for_backend_accepts_explicit_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "accounts.json"
            sqlite_path = Path(tmp_dir) / "accounts.sqlite3"

            self.assertIsInstance(build_account_store_for_backend("json", path=json_path), JsonAccountStore)
            self.assertIsInstance(build_account_store_for_backend("sqlite", path=sqlite_path), SqliteAccountStore)

    def test_build_account_store_for_backend_does_not_require_config_import_for_explicit_paths(self) -> None:
        script = f"""
import sys
import types
from pathlib import Path

sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})

sentinel = types.ModuleType("services.config")
def _blocked(name):
    raise RuntimeError(f"unexpected services.config access: {{name}}")
sentinel.__getattr__ = _blocked
sys.modules["services.config"] = sentinel

from services.storage.factory import build_account_store_for_backend

json_store = build_account_store_for_backend("json", path=Path("accounts.json"))
sqlite_store = build_account_store_for_backend("sqlite", path=Path("accounts.sqlite3"))
assert json_store.path == Path("accounts.json")
assert sqlite_store.path == Path("accounts.sqlite3")
"""
        result = subprocess.run(["python3", "-c", script], capture_output=True, text=True)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_build_account_store_rejects_unsupported_backend(self) -> None:
        fake_config = mock.Mock(storage_backend="postgres", accounts_file=Path("accounts.json"))

        with self.assertRaisesRegex(ValueError, "unsupported account storage backend: postgres"):
            build_account_store(fake_config)

    def test_get_account_storage_info_reports_json_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "accounts.json"
            fake_config = mock.Mock(storage_backend="json", accounts_file=path)

            info = get_account_storage_info(fake_config)

            self.assertEqual("json", info["backend"])
            self.assertEqual(["json", "sqlite"], info["available_backends"])
            self.assertEqual(str(path), info["path"])
            self.assertTrue(info["writable"])

    def test_get_account_storage_info_reports_sqlite_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "accounts.sqlite3"
            fake_config = mock.Mock(storage_backend="sqlite", storage_sqlite_path=path)

            info = get_account_storage_info(fake_config)

            self.assertEqual("sqlite", info["backend"])
            self.assertEqual(["json", "sqlite"], info["available_backends"])
            self.assertEqual(str(path), info["path"])
            self.assertTrue(info["writable"])

    def test_sqlite_account_store_round_trips_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "accounts.sqlite3"
            service = AccountService(SqliteAccountStore(path))

            service.add_accounts(["token-1"])
            service.update_account("token-1", {"status": "正常", "quota": 4})

            reloaded = AccountService(SqliteAccountStore(path))
            account = reloaded.get_account("token-1")

            self.assertIsNotNone(account)
            self.assertEqual("正常", account["status"])
            self.assertEqual(4, account["quota"])
            self.assertEqual(["token-1"], reloaded.list_tokens())

    def test_migrate_accounts_copies_json_store_into_sqlite_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "accounts.json"
            sqlite_path = Path(tmp_dir) / "accounts.sqlite3"
            service = AccountService(JsonAccountStore(json_path))
            service.add_accounts(["token-1"])
            service.update_account("token-1", {"status": "正常", "quota": 2})

            migrated = migrate_accounts(JsonAccountStore(json_path), SqliteAccountStore(sqlite_path))
            reloaded = AccountService(SqliteAccountStore(sqlite_path))

            self.assertEqual(1, migrated)
            self.assertEqual(["token-1"], reloaded.list_tokens())
            self.assertEqual(2, reloaded.get_account("token-1")["quota"])


class TokenLogTests(unittest.TestCase):
    def test_anonymize_token_hides_raw_value(self) -> None:
        token = "super-secret-token"
        token_ref = anonymize_token(token)

        self.assertTrue(token_ref.startswith("token:"))
        self.assertNotIn(token, token_ref)


if __name__ == "__main__":
    unittest.main()
