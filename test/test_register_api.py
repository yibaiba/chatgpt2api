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


class _FakeRegisterService:
    def __init__(self) -> None:
        self.state = {
            "enabled": False,
            "mail": {
                "request_timeout": 30,
                "wait_timeout": 180,
                "wait_interval": 5,
                "providers": [],
            },
            "proxy": "",
            "total": 10,
            "threads": 1,
            "mode": "total",
            "target_quota": 100,
            "target_available": 10,
            "check_interval": 5,
            "stats": {
                "success": 0,
                "fail": 0,
                "done": 0,
                "running": 0,
                "threads": 1,
                "current_quota": 0,
                "current_available": 0,
            },
            "logs": [],
        }

    def get(self):
        return dict(self.state)

    def update(self, updates: dict):
        self.state = {
            **self.state,
            **updates,
            "mail": {
                **self.state["mail"],
                **(updates.get("mail") or {}),
            },
        }
        return self.get()

    def start(self):
        self.state["enabled"] = True
        return self.get()

    def stop(self):
        self.state["enabled"] = False
        return self.get()

    def reset(self):
        self.state["logs"] = []
        self.state["stats"] = {
            "success": 0,
            "fail": 0,
            "done": 0,
            "running": 0,
            "threads": self.state["threads"],
            "current_quota": 0,
            "current_available": 0,
        }
        return self.get()


class RegisterApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.fake_register_service = _FakeRegisterService()
        fake_config = SimpleNamespace(
            base_url="",
            images_dir=Path(self.temp_dir.name) / "images",
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
            mock.patch.object(api_module, "register_service", self.fake_register_service),
            mock.patch.object(api_module, "start_limited_account_watcher", lambda _stop_event: _FakeThread()),
        ]
        for patcher in self.patches:
            patcher.start()
        self.addCleanup(self._cleanup_patches)
        self.client = TestClient(api_module.create_app())
        self.addCleanup(self.client.close)

    def _cleanup_patches(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_admin_can_read_update_and_control_register_runner(self) -> None:
        auth_header = {"Authorization": "Bearer test-auth"}

        response = self.client.get("/api/register", headers=auth_header)
        self.assertEqual(200, response.status_code)
        self.assertEqual("total", response.json()["register"]["mode"])

        update_response = self.client.post(
            "/api/register",
            headers=auth_header,
            json={
                "mode": "available",
                "target_available": 6,
                "mail": {
                    "request_timeout": 40,
                },
            },
        )
        self.assertEqual(200, update_response.status_code)
        self.assertEqual("available", update_response.json()["register"]["mode"])
        self.assertEqual(6, update_response.json()["register"]["target_available"])
        self.assertEqual(40, update_response.json()["register"]["mail"]["request_timeout"])

        start_response = self.client.post("/api/register/start", headers=auth_header)
        self.assertEqual(200, start_response.status_code)
        self.assertTrue(start_response.json()["register"]["enabled"])

        stop_response = self.client.post("/api/register/stop", headers=auth_header)
        self.assertEqual(200, stop_response.status_code)
        self.assertFalse(stop_response.json()["register"]["enabled"])

        reset_response = self.client.post("/api/register/reset", headers=auth_header)
        self.assertEqual(200, reset_response.status_code)
        self.assertEqual([], reset_response.json()["register"]["logs"])

    def test_non_admin_cannot_access_register_runner_routes(self) -> None:
        auth_header = {"Authorization": "Bearer user-auth"}

        response = self.client.get("/api/register", headers=auth_header)
        self.assertEqual(403, response.status_code)
        self.assertEqual("admin permission required", response.json()["detail"]["error"])


if __name__ == "__main__":
    unittest.main()
