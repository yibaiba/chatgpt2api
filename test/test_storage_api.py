from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from services import api as api_module


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


class StorageApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        fake_config = SimpleNamespace(
            base_url="",
            images_dir=Path(self.temp_dir.name) / "images",
            accounts_file=Path(self.temp_dir.name) / "accounts.json",
            storage_backend="json",
            refresh_account_interval_minute=60,
            session_signing_secret="test-session-secret",
            get_proxy_settings=lambda: "",
            verify_admin_auth_key=lambda value: str(value or "").strip() == "test-auth",
            get=lambda: {"auth_key_configured": True},
            update=lambda data: data,
        )
        self.patches = [
            mock.patch.object(api_module, "ChatGPTService", _FakeChatGPTService),
            mock.patch.object(api_module, "auth_service", _FakeAuthService()),
            mock.patch.object(api_module, "config", fake_config),
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

    def test_non_admin_cannot_fetch_storage_info(self) -> None:
        response = self.client.get("/api/storage/info", headers={"Authorization": "Bearer user-auth"})

        self.assertEqual(403, response.status_code)
        self.assertEqual("admin permission required", response.json()["detail"]["error"])


if __name__ == "__main__":
    unittest.main()
