import unittest
from types import SimpleNamespace
from unittest import mock

from services import api as api_module


class ImageBaseUrlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_config = SimpleNamespace(base_url="https://public.example.com")
        patcher = mock.patch.object(api_module, "config", self.fake_config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_prefers_configured_base_url(self) -> None:
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="http", netloc="127.0.0.1:8000"),
            headers={"host": "127.0.0.1:8000"},
        )

        self.assertEqual(api_module.resolve_image_base_url(request), "https://public.example.com")

    def test_returns_empty_without_configured_base_url(self) -> None:
        self.fake_config.base_url = ""
        self.assertEqual(api_module.resolve_image_base_url(), "")

    def test_require_image_base_url_rejects_missing_config(self) -> None:
        self.fake_config.base_url = ""
        with self.assertRaises(api_module.HTTPException) as captured:
            api_module.require_image_base_url()
        self.assertEqual(captured.exception.status_code, 400)
        self.assertEqual(captured.exception.detail["error"], "base_url is required when response_format=url")


if __name__ == "__main__":
    unittest.main()
