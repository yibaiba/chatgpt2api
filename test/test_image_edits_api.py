import unittest
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from services import api as api_module
from services.image_service import ImageGenerationError


class _FakeThread:
    def join(self, timeout: float | None = None) -> None:
        return None


class _FakeChatGPTService:
    last_call: dict[str, object] | None = None
    generate_error: Exception | None = None

    def __init__(self, _account_service) -> None:
        return None

    def edit_with_pool(
        self,
        prompt: str,
        images,
        model: str,
        n: int,
        *,
        response_format: str = "b64_json",
        base_url: str | None = None,
    ):
        normalized_images = list(images)
        type(self).last_call = {
            "prompt": prompt,
            "images": normalized_images,
            "model": model,
            "n": n,
            "response_format": response_format,
            "base_url": base_url,
        }
        return {
            "created": 123,
            "data": [{"b64_json": "ZmFrZQ==", "revised_prompt": prompt}],
        }

    def generate_with_pool(
        self,
        prompt: str,
        model: str,
        n: int,
        *,
        response_format: str = "b64_json",
        base_url: str | None = None,
    ):
        if type(self).generate_error is not None:
            raise type(self).generate_error
        type(self).last_call = {
            "prompt": prompt,
            "model": model,
            "n": n,
            "response_format": response_format,
            "base_url": base_url,
        }
        return {
            "created": 123,
            "data": [{"b64_json": "ZmFrZQ==", "revised_prompt": prompt}],
        }


class _FakeConfig:
    def __init__(self, images_dir: Path) -> None:
        self.base_url = ""
        self.images_dir = images_dir
        self.refresh_account_interval_minute = 60
        self.session_signing_secret = "test-session-secret"

    def verify_admin_auth_key(self, value: str) -> bool:
        return str(value or "").strip() == "test-auth"

    def get_proxy_settings(self) -> str:
        return ""


class _FakeAuthService:
    def __init__(self) -> None:
        self.reserved: list[int] = []
        self.settled: list[tuple[int, int]] = []

    def authenticate(self, auth_key: str):
        if auth_key == "test-auth":
            return {"id": "admin", "role": "admin", "name": "管理员"}
        return None

    def reserve_images_for_identity(self, _identity: dict, image_count: int):
        self.reserved.append(image_count)
        return None

    def settle_images_for_identity(self, _identity: dict, reserved_count: int, actual_count: int):
        self.settled.append((reserved_count, actual_count))
        return None


class ImageEditsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeChatGPTService.last_call = None
        _FakeChatGPTService.generate_error = None
        self.auth_header = {"Authorization": "Bearer test-auth"}
        self.auth_service = _FakeAuthService()
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        fake_config = _FakeConfig(Path(self.temp_dir.name) / "images")
        self.patches = [
            mock.patch.object(api_module, "ChatGPTService", _FakeChatGPTService),
            mock.patch.object(api_module, "auth_service", self.auth_service),
            mock.patch.object(api_module, "config", fake_config),
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

    def _wait_for_job(self, job_id: str):
        for _ in range(50):
            response = self.client.get(f"/api/image-jobs/{job_id}", headers=self.auth_header)
            self.assertEqual(response.status_code, 200)
            job = response.json()["job"]
            if job["status"] in {"success", "error"}:
                return job
            time.sleep(0.01)
        self.fail("image job did not settle")

    def test_accepts_repeated_image_field(self) -> None:
        response = self.client.post(
            "/v1/images/edits",
            headers=self.auth_header,
            data={"prompt": "test prompt", "model": "gpt-image-1", "n": "1"},
            files=[
                ("image", ("first.png", b"first", "image/png")),
                ("image", ("second.png", b"second", "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(_FakeChatGPTService.last_call)
        self.assertEqual(len(_FakeChatGPTService.last_call["images"]), 2)
        self.assertEqual(
            [item[1] for item in _FakeChatGPTService.last_call["images"]],
            ["first.png", "second.png"],
        )

    def test_rejects_too_many_files(self) -> None:
        response = self.client.post(
            "/v1/images/edits",
            headers=self.auth_header,
            data={"prompt": "test prompt", "model": "gpt-image-1", "n": "1"},
            files=[
                ("image", ("first.png", b"1", "image/png")),
                ("image", ("second.png", b"2", "image/png")),
                ("image", ("third.png", b"3", "image/png")),
                ("image", ("fourth.png", b"4", "image/png")),
                ("image", ("fifth.png", b"5", "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "at most 4 image files are allowed")

    def test_rejects_oversized_file(self) -> None:
        oversized = b"x" * (api_module.MAX_EDIT_UPLOAD_BYTES_PER_FILE + 1)
        response = self.client.post(
            "/v1/images/edits",
            headers=self.auth_header,
            data={"prompt": "test prompt", "model": "gpt-image-1", "n": "1"},
            files=[("image", ("large.png", oversized, "image/png"))],
        )

        self.assertEqual(response.status_code, 413)
        self.assertIn("image file exceeds", response.json()["detail"]["error"])

    def test_rejects_unsupported_mime_type(self) -> None:
        response = self.client.post(
            "/v1/images/edits",
            headers=self.auth_header,
            data={"prompt": "test prompt", "model": "gpt-image-1", "n": "1"},
            files=[("image", ("payload.txt", b"hello", "text/plain"))],
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "unsupported image file type")

    def test_accepts_repeated_image_bracket_field(self) -> None:
        response = self.client.post(
            "/v1/images/edits",
            headers=self.auth_header,
            data={"prompt": "test prompt", "model": "gpt-image-1", "n": "1"},
            files=[
                ("image[]", ("first.png", b"first", "image/png")),
                ("image[]", ("second.png", b"second", "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(_FakeChatGPTService.last_call)
        self.assertEqual(len(_FakeChatGPTService.last_call["images"]), 2)
        self.assertEqual(
            [item[1] for item in _FakeChatGPTService.last_call["images"]],
            ["first.png", "second.png"],
        )

    def test_edits_apply_optional_size_to_prompt(self) -> None:
        response = self.client.post(
            "/v1/images/edits",
            headers=self.auth_header,
            data={"prompt": "test prompt", "model": "gpt-image-1", "n": "1", "size": "16:9"},
            files=[("image", ("first.png", b"first", "image/png"))],
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(_FakeChatGPTService.last_call)
        self.assertEqual(
            "Make the aspect ratio 16:9 , test prompt",
            _FakeChatGPTService.last_call["prompt"],
        )

    def test_generations_apply_optional_size_to_prompt(self) -> None:
        response = self.client.post(
            "/v1/images/generations",
            headers=self.auth_header,
            json={"prompt": "test prompt", "model": "gpt-image-1", "n": 1, "size": "3:4"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(_FakeChatGPTService.last_call)
        self.assertEqual(
            "Make the aspect ratio 3:4 , test prompt",
            _FakeChatGPTService.last_call["prompt"],
        )

    def test_generation_job_completes_through_polling_api(self) -> None:
        response = self.client.post(
            "/api/image-jobs/generations",
            headers=self.auth_header,
            json={"prompt": "draw a cat", "model": "gpt-image-think", "n": 1},
        )
        self.assertEqual(response.status_code, 200)
        job = self._wait_for_job(response.json()["job"]["id"])

        self.assertEqual("success", job["status"])
        self.assertEqual("ZmFrZQ==", job["result"]["data"][0]["b64_json"])
        self.assertEqual([1], self.auth_service.reserved)
        self.assertEqual([(1, 1)], self.auth_service.settled)

    def test_generation_job_error_refunds_reserved_quota(self) -> None:
        _FakeChatGPTService.generate_error = ImageGenerationError("upstream failed")
        response = self.client.post(
            "/api/image-jobs/generations",
            headers=self.auth_header,
            json={"prompt": "draw a cat", "model": "gpt-image-think", "n": 1},
        )
        self.assertEqual(response.status_code, 200)
        job = self._wait_for_job(response.json()["job"]["id"])

        self.assertEqual("error", job["status"])
        self.assertEqual("upstream failed", job["error"])
        self.assertEqual([(1, 0)], self.auth_service.settled)


if __name__ == "__main__":
    unittest.main()
