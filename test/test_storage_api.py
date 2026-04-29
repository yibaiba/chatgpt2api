from __future__ import annotations

import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fastapi.testclient import TestClient

from services import api as api_module
from services import config as config_module


os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class _FakeThread:
    def join(self, timeout: float | None = None) -> None:
        return None


class _FakeChatGPTService:
    def __init__(self, _account_service) -> None:
        return None


class _FakeAuthService:
    def authenticate(self, auth_key: str):
        if auth_key == "test-auth":
            return {"id": "admin", "role": "admin", "name": "管理员"}
        if auth_key == "user-auth":
            return {"id": "user-1", "role": "user", "name": "普通用户", "image_quota": 1, "total_generated": 0, "last_used_at": None}
        return None

    def build_session_from_identity(self, identity: dict) -> dict:
        return {
            "id": str(identity.get("id") or "unknown"),
            "role": str(identity.get("role") or "user"),
            "name": str(identity.get("name") or "普通用户"),
            "image_quota": identity.get("image_quota"),
            "total_generated": identity.get("total_generated"),
            "last_used_at": identity.get("last_used_at"),
            "image_history_persistence_mode": "browser",
        }


class _FakeAccountService:
    def __init__(self) -> None:
        self.rebind_paths: list[Path] = []
        self.raise_error: Exception | None = None

    def rebind_store(self, store) -> list[dict]:
        if self.raise_error is not None:
            raise self.raise_error
        path = getattr(store, "path", None)
        if isinstance(path, Path):
            self.rebind_paths.append(path)
        return []


class StorageApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_file = Path(self.temp_dir.name) / "config.json"
        self.config_file.write_text('{"auth-key":"test-auth"}\n', encoding="utf-8")
        self.fake_config = config_module.ConfigStore(self.config_file)
        self.fake_account_service = _FakeAccountService()
        self.patches = [
            mock.patch.object(api_module, "ChatGPTService", _FakeChatGPTService),
            mock.patch.object(api_module, "auth_service", _FakeAuthService()),
            mock.patch.object(api_module, "config", self.fake_config),
            mock.patch.object(api_module, "account_service", self.fake_account_service),
            mock.patch.object(api_module, "start_limited_account_watcher", lambda _stop_event: _FakeThread()),
            mock.patch.object(api_module, "start_remote_account_sync_watcher", lambda _stop_event: _FakeThread()),
        ]
        for patcher in self.patches:
            patcher.start()
        self.addCleanup(self._cleanup_patches)
        self.client = TestClient(api_module.create_app())
        self.addCleanup(self.client.close)

    def _cleanup_patches(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_admin_can_fetch_storage_info(self) -> None:
        response = self.client.get("/api/storage/info", headers={"Authorization": "Bearer test-auth"})

        self.assertEqual(200, response.status_code)
        payload = response.json()["storage"]
        self.assertEqual("json", payload["backend"])
        self.assertEqual(["json", "sqlite"], payload["available_backends"])
        self.assertTrue(payload["path"].endswith("accounts.json"))
        self.assertTrue(payload["writable"])
        self.assertFalse(payload["env_override_active"])

    def test_non_admin_cannot_fetch_storage_info(self) -> None:
        response = self.client.get("/api/storage/info", headers={"Authorization": "Bearer user-auth"})

        self.assertEqual(403, response.status_code)
        self.assertEqual("admin permission required", response.json()["detail"]["error"])

    def test_admin_save_settings_rebinds_runtime_storage_backend(self) -> None:
        sqlite_path = Path(self.temp_dir.name) / "runtime.sqlite3"

        response = self.client.post(
            "/api/settings",
            headers={"Authorization": "Bearer test-auth"},
            json={
                "storage_backend": "sqlite",
                "storage_sqlite_path": str(sqlite_path),
            },
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()["config"]
        self.assertEqual("sqlite", payload["storage_backend"])
        self.assertEqual(str(sqlite_path), payload["storage_sqlite_path"])
        self.assertEqual([sqlite_path], self.fake_account_service.rebind_paths)

        info_response = self.client.get("/api/storage/info", headers={"Authorization": "Bearer test-auth"})
        self.assertEqual(200, info_response.status_code)
        self.assertEqual("sqlite", info_response.json()["storage"]["backend"])
        self.assertEqual(str(sqlite_path), info_response.json()["storage"]["path"])

    def test_admin_save_settings_rejects_unsupported_storage_backend(self) -> None:
        response = self.client.post(
            "/api/settings",
            headers={"Authorization": "Bearer test-auth"},
            json={"storage_backend": "postgres"},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("unsupported storage_backend: postgres", response.json()["detail"]["error"])
        self.assertEqual([], self.fake_account_service.rebind_paths)
        self.assertEqual("json", self.fake_config.storage_backend)

    def test_admin_save_settings_rolls_back_when_runtime_rebind_fails(self) -> None:
        sqlite_path = Path(self.temp_dir.name) / "runtime.sqlite3"
        self.fake_account_service.raise_error = RuntimeError("boom")

        response = self.client.post(
            "/api/settings",
            headers={"Authorization": "Bearer test-auth"},
            json={
                "storage_backend": "sqlite",
                "storage_sqlite_path": str(sqlite_path),
            },
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("failed to apply storage settings: boom", response.json()["detail"]["error"])
        self.assertEqual("json", self.fake_config.storage_backend)
        self.assertTrue(self.fake_config.accounts_file.name.endswith("accounts.json"))

    def test_admin_save_settings_rejects_runtime_storage_switch_when_env_path_override_is_active(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "CHATGPT2API_STORAGE_SQLITE_PATH": str(Path(self.temp_dir.name) / "env.sqlite3"),
            },
            clear=False,
        ):
            response = self.client.post(
                "/api/settings",
                headers={"Authorization": "Bearer test-auth"},
                json={"storage_backend": "sqlite"},
            )

        self.assertEqual(400, response.status_code)
        self.assertIn(
            "storage settings are controlled by environment overrides",
            response.json()["detail"]["error"],
        )
        self.assertEqual([], self.fake_account_service.rebind_paths)
        self.assertEqual("json", self.fake_config.storage_backend)

    def test_admin_save_settings_ignores_effective_storage_fields_when_env_override_is_active(self) -> None:
        env_sqlite_path = Path(self.temp_dir.name) / "env.sqlite3"
        with mock.patch.dict(
            os.environ,
            {
                "CHATGPT2API_STORAGE_BACKEND": "json",
                "CHATGPT2API_STORAGE_SQLITE_PATH": str(env_sqlite_path),
            },
            clear=False,
        ):
            response = self.client.post(
                "/api/settings",
                headers={"Authorization": "Bearer test-auth"},
                json={
                    "storage_backend": "json",
                    "storage_sqlite_path": str(env_sqlite_path),
                    "refresh_account_interval_minute": 9,
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(9, response.json()["config"]["refresh_account_interval_minute"])
        self.assertEqual(
            [config_module.DATA_DIR / "accounts.json"],
            self.fake_account_service.rebind_paths,
        )
        self.assertEqual(9, self.fake_config.refresh_account_interval_minute)
        self.assertEqual("json", self.fake_config.storage_backend)
        self.assertEqual("json", self.fake_config.data["storage_backend"])
        self.assertNotIn("storage_sqlite_path", self.fake_config.data)

    def test_admin_save_settings_allows_future_sqlite_path_when_only_backend_override_is_active(self) -> None:
        future_sqlite_path = Path(self.temp_dir.name) / "future.sqlite3"
        with mock.patch.dict(
            os.environ,
            {"CHATGPT2API_STORAGE_BACKEND": "json"},
            clear=False,
        ):
            response = self.client.post(
                "/api/settings",
                headers={"Authorization": "Bearer test-auth"},
                json={"storage_sqlite_path": str(future_sqlite_path)},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(str(future_sqlite_path), self.fake_config.data["storage_sqlite_path"])
        self.assertEqual(
            [config_module.DATA_DIR / "accounts.json"],
            self.fake_account_service.rebind_paths,
        )


if __name__ == "__main__":
    unittest.main()
