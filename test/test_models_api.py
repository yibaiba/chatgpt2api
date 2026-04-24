from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.api import create_app
from services.utils import SUPPORTED_IMAGE_MODELS


class ModelsApiTests(unittest.TestCase):
    def test_v1_models_matches_supported_image_models(self) -> None:
        app = create_app()
        route = next(route for route in app.routes if getattr(route, "path", None) == "/v1/models")

        response = route.endpoint()
        if hasattr(response, "__await__"):
            import asyncio

            response = asyncio.run(response)

        self.assertEqual(response["object"], "list")
        self.assertEqual(
            [item["id"] for item in response["data"]],
            list(SUPPORTED_IMAGE_MODELS),
        )


if __name__ == "__main__":
    unittest.main()
