from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.api import create_app
from services.utils import SUPPORTED_API_MODELS, SUPPORTED_IMAGE_MODELS
from services.chatgpt_service import ChatGPTService


class ModelsApiTests(unittest.TestCase):
    def test_v1_models_returns_auto_and_local_image_aliases(self) -> None:
        app = create_app()
        route = next(route for route in app.routes if getattr(route, "path", None) == "/v1/models")

        response = route.endpoint()
        if hasattr(response, "__await__"):
            import asyncio

            response = asyncio.run(response)

        self.assertEqual(response["object"], "list")
        model_ids = [item["id"] for item in response["data"]]
        self.assertTrue(model_ids)
        self.assertEqual("auto", model_ids[0])
        for model in SUPPORTED_IMAGE_MODELS:
            self.assertIn(model, model_ids)

    def test_chatgpt_service_list_models_merges_discovered_text_models_with_local_image_aliases(self) -> None:
        service = ChatGPTService(mock.Mock())
        with mock.patch.object(service, "_discover_text_models", return_value=["gpt-4.1", "gpt-5", "o3"]):
            models = service.list_models()

        self.assertEqual(
            models,
            ["auto", "gpt-4.1", "gpt-5", "o3", "gpt-image-1", "gpt-image-2", "codex-gpt-image-2", "gpt-image-think"],
        )

    def test_chatgpt_service_list_models_falls_back_to_static_supported_models(self) -> None:
        service = ChatGPTService(mock.Mock())
        with mock.patch.object(service, "_discover_text_models", side_effect=RuntimeError("boom")):
            models = service.list_models()

        self.assertEqual(models, list(SUPPORTED_API_MODELS))


if __name__ == "__main__":
    unittest.main()
