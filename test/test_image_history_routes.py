from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.image_history_service import ImageHistoryService


class ImageHistoryRouteTests(unittest.TestCase):
    def test_normalize_image_keeps_valid_generation_route(self) -> None:
        service = ImageHistoryService(Path(tempfile.mkdtemp()) / "image_history.json")

        normalized = service._normalize_image(
            {
                "id": "img_1",
                "status": "success",
                "b64_json": "abc",
                "mime_type": "image/png",
                "generation_route": "thinking",
            }
        )

        self.assertIsNotNone(normalized)
        self.assertEqual("thinking", normalized["generation_route"])

    def test_normalize_image_drops_unknown_generation_route(self) -> None:
        service = ImageHistoryService(Path(tempfile.mkdtemp()) / "image_history.json")

        normalized = service._normalize_image(
            {
                "id": "img_1",
                "status": "success",
                "b64_json": "abc",
                "mime_type": "image/png",
                "generation_route": "mystery",
            }
        )

        self.assertIsNotNone(normalized)
        self.assertIsNone(normalized["generation_route"])

    def test_normalize_turn_keeps_codex_native_options(self) -> None:
        service = ImageHistoryService(Path(tempfile.mkdtemp()) / "image_history.json")

        normalized = service._normalize_turn(
            {
                "id": "turn_1",
                "prompt": "draw a city",
                "model": "codex-gpt-image-2",
                "mode": "generate",
                "aspectRatio": "16:9",
                "outputQuality": "4k",
                "renderQuality": "high",
                "background": "opaque",
                "outputFormat": "webp",
                "compression": 25,
                "count": 1,
                "images": [{"id": "img_1", "status": "loading"}],
            }
        )

        self.assertIsNotNone(normalized)
        self.assertEqual("16:9", normalized["aspectRatio"])
        self.assertEqual("4k", normalized["outputQuality"])
        self.assertEqual("high", normalized["renderQuality"])
        self.assertEqual("opaque", normalized["background"])
        self.assertEqual("webp", normalized["outputFormat"])
        self.assertEqual(25, normalized["compression"])

    def test_normalize_payload_keeps_legacy_codex_native_options(self) -> None:
        service = ImageHistoryService(Path(tempfile.mkdtemp()) / "image_history.json")

        normalized = service._normalize_payload(
            {
                "id": "conv_1",
                "title": "Codex",
                "prompt": "draw a city",
                "model": "codex-gpt-image-2",
                "mode": "generate",
                "aspectRatio": "16:9",
                "outputQuality": "4k",
                "renderQuality": "high",
                "background": "opaque",
                "outputFormat": "jpeg",
                "compression": 40,
                "count": 1,
                "images": [{"id": "img_1", "status": "loading"}],
            }
        )

        self.assertIsNotNone(normalized)
        self.assertEqual("high", normalized["turns"][0]["renderQuality"])
        self.assertEqual("opaque", normalized["turns"][0]["background"])
        self.assertEqual("jpeg", normalized["turns"][0]["outputFormat"])
        self.assertEqual(40, normalized["turns"][0]["compression"])

    def test_normalize_turn_keeps_inpaint_fields(self) -> None:
        """_normalize_turn 应保留 inpaintOriginalImage / inpaintMaskImage 及相关 ID 字段"""
        service = ImageHistoryService(Path(tempfile.mkdtemp()) / "image_history.json")

        normalized = service._normalize_turn(
            {
                "id": "turn_inpaint",
                "prompt": "make the sky red",
                "model": "gpt-image-1",
                "mode": "edit",
                "count": 1,
                "images": [{"id": "img_1", "status": "success", "b64_json": "abc"}],
                "inpaintOriginalImage": {
                    "name": "original.png",
                    "type": "image/png",
                    "dataUrl": "data:image/png;base64,abc",
                },
                "inpaintMaskImage": {
                    "name": "mask.png",
                    "type": "image/png",
                    "dataUrl": "data:image/png;base64,def",
                },
                "inpaintConversationId": "conv_abc",
                "inpaintParentMessageId": "msg_xyz",
            }
        )

        self.assertIsNotNone(normalized)
        self.assertIsNotNone(normalized["inpaintOriginalImage"])
        self.assertEqual("data:image/png;base64,abc", normalized["inpaintOriginalImage"]["dataUrl"])
        self.assertEqual("original.png", normalized["inpaintOriginalImage"]["name"])
        self.assertIsNotNone(normalized["inpaintMaskImage"])
        self.assertEqual("data:image/png;base64,def", normalized["inpaintMaskImage"]["dataUrl"])
        self.assertEqual("conv_abc", normalized["inpaintConversationId"])
        self.assertEqual("msg_xyz", normalized["inpaintParentMessageId"])

    def test_normalize_turn_inpaint_fields_are_none_when_absent(self) -> None:
        """普通 turn 的 inpaint 字段应为 None"""
        service = ImageHistoryService(Path(tempfile.mkdtemp()) / "image_history.json")

        normalized = service._normalize_turn(
            {
                "id": "turn_regular",
                "prompt": "draw a sunset",
                "model": "gpt-image-1",
                "mode": "generate",
                "count": 1,
                "images": [{"id": "img_1", "status": "success", "b64_json": "abc"}],
            }
        )

        self.assertIsNotNone(normalized)
        self.assertIsNone(normalized["inpaintOriginalImage"])
        self.assertIsNone(normalized["inpaintMaskImage"])
        self.assertIsNone(normalized["inpaintConversationId"])
        self.assertIsNone(normalized["inpaintParentMessageId"])

    def test_normalize_payload_preserves_inpaint_fields_through_conversation(self) -> None:
        """_normalize_payload 全链路保留 inpaint 字段"""
        service = ImageHistoryService(Path(tempfile.mkdtemp()) / "image_history.json")

        normalized = service._normalize_payload(
            {
                "id": "conv_inpaint",
                "title": "Inpaint Test",
                "turns": [
                    {
                        "id": "turn_inpaint",
                        "prompt": "make the sky red",
                        "model": "gpt-image-1",
                        "mode": "edit",
                        "count": 1,
                        "images": [{"id": "img_1", "status": "success", "b64_json": "abc"}],
                        "inpaintOriginalImage": {
                            "name": "original.png",
                            "type": "image/png",
                            "dataUrl": "data:image/png;base64,orig",
                        },
                        "inpaintMaskImage": {
                            "name": "mask.png",
                            "type": "image/png",
                            "dataUrl": "data:image/png;base64,mask",
                        },
                        "inpaintConversationId": "conv_src",
                        "inpaintParentMessageId": "msg_src",
                    }
                ],
                "ownerRole": "admin",
                "ownerId": "admin",
                "ownerName": "管理员",
            }
        )

        self.assertIsNotNone(normalized)
        turn = normalized["turns"][0]
        self.assertIsNotNone(turn["inpaintOriginalImage"])
        self.assertEqual("data:image/png;base64,orig", turn["inpaintOriginalImage"]["dataUrl"])
        self.assertIsNotNone(turn["inpaintMaskImage"])
        self.assertEqual("data:image/png;base64,mask", turn["inpaintMaskImage"]["dataUrl"])
        self.assertEqual("conv_src", turn["inpaintConversationId"])
        self.assertEqual("msg_src", turn["inpaintParentMessageId"])


if __name__ == "__main__":
    unittest.main()
