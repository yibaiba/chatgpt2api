from __future__ import annotations

import base64
import io
import json
import os
import unittest
from unittest import mock

from PIL import Image

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.image_service import (
    EditInputImage,
    ImageGenerationError,
    _build_output_candidate_score,
    _build_edit_input_payload,
    _build_image_result_data,
    _composite_inpaint_onto_original,
    _build_regular_picture_v2_body,
    _collect_edit_output,
    _download_as_base64,
    _extract_image_ids,
    _build_picture_v2_edit_input_payload,
    _parse_sse,
    _run_legacy_regular_generation_mode,
    _run_legacy_regular_edit_mode,
    _resolve_upstream_edit_model,
    _resolve_upstream_model,
    _select_best_output_candidate,
    _send_regular_edit_conversation,
    edit_image_result,
    generate_image_result,
)
from services.chatgpt_service import ChatGPTService
from services.utils import ImageRequestOptions


class ImageModelRoutingTests(unittest.TestCase):
    def _png_bytes(self, image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _download_response(self, status_code: int, content: bytes = b"", text: str = ""):
        response = mock.Mock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 400
        response.content = content
        response.text = text
        return response

    def _stream_response(self, *events: dict, status_code: int = 200, text: str = ""):
        response = mock.Mock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 400
        response.text = text
        response.iter_lines.return_value = [
            f"data: {json.dumps(event)}".encode("utf-8")
            for event in events
        ]
        return response

    def test_standard_model_uses_regular_picture_pipeline_slug(self) -> None:
        with mock.patch("services.image_service.account_service.get_account", return_value={"type": "Pro"}):
            upstream_model, use_thinking = _resolve_upstream_model("token", "gpt-image-2")

        self.assertEqual("gpt-5-3", upstream_model)
        self.assertFalse(use_thinking)

    def test_codex_model_keeps_codex_slug_for_paid_accounts(self) -> None:
        with mock.patch("services.image_service.account_service.get_account", return_value={"type": "Pro"}):
            upstream_model, use_thinking = _resolve_upstream_model("token", "codex-gpt-image-2")

        self.assertEqual("codex-gpt-image-2", upstream_model)
        self.assertFalse(use_thinking)

    def test_think_model_keeps_thinking_route(self) -> None:
        with mock.patch("services.image_service.account_service.get_account", return_value={"type": "Free"}):
            upstream_model, use_thinking = _resolve_upstream_model("token", "gpt-image-think")

        self.assertEqual("auto", upstream_model)
        self.assertTrue(use_thinking)

    def test_think_model_uses_reasoning_model_for_paid_accounts(self) -> None:
        with mock.patch("services.image_service.account_service.get_account", return_value={"type": "Pro"}):
            upstream_model, use_thinking = _resolve_upstream_model("token", "gpt-image-think")

        self.assertEqual("gpt-5-3", upstream_model)
        self.assertTrue(use_thinking)

    def test_inpaint_with_pool_reuses_existing_conversation_context(self) -> None:
        account_service = mock.Mock()
        account_service.get_available_access_token.return_value = "token-a"
        account_service.mark_image_result.return_value = {"quota": 1}
        service = ChatGPTService(account_service)

        with mock.patch(
            "services.chatgpt_service.inpaint_image_result",
            return_value={"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]},
        ) as inpaint_mock:
            result = service.inpaint_with_pool(
                "replace center character",
                (b"orig", "orig.png", "image/png"),
                b"mask",
                "gpt-image-2",
                conversation_id="conv-123",
                parent_message_id="msg-456",
            )

        self.assertEqual(123, result["created"])
        self.assertEqual("conv-123", inpaint_mock.call_args.kwargs["conversation_id"])
        self.assertEqual("msg-456", inpaint_mock.call_args.kwargs["parent_message_id"])

    def test_inpaint_with_pool_falls_back_without_conversation_context_on_404(self) -> None:
        account_service = mock.Mock()
        account_service.get_available_access_token.return_value = "token-a"
        account_service.mark_image_result.return_value = {"quota": 1}
        service = ChatGPTService(account_service)

        with mock.patch(
            "services.chatgpt_service.inpaint_image_result",
            side_effect=[
                ImageGenerationError("conversation failed: 404"),
                {"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]},
            ],
        ) as inpaint_mock:
            result = service.inpaint_with_pool(
                "replace center character",
                (b"orig", "orig.png", "image/png"),
                b"mask",
                "gpt-image-2",
                conversation_id="conv-123",
                parent_message_id="msg-456",
            )

        self.assertEqual(123, result["created"])
        self.assertEqual(2, inpaint_mock.call_count)
        self.assertEqual("conv-123", inpaint_mock.call_args_list[0].kwargs["conversation_id"])
        self.assertEqual("msg-456", inpaint_mock.call_args_list[0].kwargs["parent_message_id"])
        self.assertEqual("", inpaint_mock.call_args_list[1].kwargs["conversation_id"])
        self.assertEqual("", inpaint_mock.call_args_list[1].kwargs["parent_message_id"])

    def test_edit_models_follow_upstream_picture_pipeline_slug(self) -> None:
        self.assertEqual("gpt-5-3", _resolve_upstream_edit_model("gpt-image-2"))
        self.assertEqual("gpt-5-3", _resolve_upstream_edit_model("gpt-image-think"))
        self.assertEqual("gpt-5-3", _resolve_upstream_edit_model("gpt-image-1"))
        self.assertEqual("codex-gpt-image-2", _resolve_upstream_edit_model("codex-gpt-image-2"))

    def test_codex_generation_requires_paid_account(self) -> None:
        with mock.patch("services.image_service.account_service.get_account", return_value={"type": "Free"}):
            with self.assertRaisesRegex(ImageGenerationError, "Plus, Team, or Pro"):
                generate_image_result(
                    access_token="token",
                    prompt="draw a cat",
                    model="codex-gpt-image-2",
                )

    def test_codex_generate_uses_native_responses_route(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), color=(128, 64, 255)).save(buffer, format="PNG")
        image_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
        session = mock.Mock()
        session.post.return_value = self._stream_response(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "image_generation_call",
                    "result": image_b64,
                    "output_format": "png",
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_123",
                    "created_at": 123,
                    "status": "completed",
                },
            },
        )

        with (
            mock.patch(
                "services.image_service.account_service.get_account",
                return_value={"type": "Pro", "user_id": "user_123"},
            ),
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
            mock.patch("services.image_service._chat_requirements") as chat_requirements,
            mock.patch("services.image_service._run_regular_generation_mode") as regular_generation,
        ):
            result = generate_image_result(
                access_token="token",
                prompt="draw a cat",
                model="codex-gpt-image-2",
                image_options=ImageRequestOptions(size="2048x1024"),
            )

        self.assertEqual(123, result["created"])
        self.assertIn("b64_json", result["data"][0])
        chat_requirements.assert_not_called()
        regular_generation.assert_not_called()
        session.post.assert_called_once()
        self.assertTrue(session.post.call_args.args[0].endswith("/backend-api/codex/responses"))
        self.assertEqual(
            {
                "type": "image_generation",
                "output_format": "png",
                "size": "2048x1024",
            },
            session.post.call_args.kwargs["json"]["tools"][0],
        )
        self.assertEqual("you are a helpful assistant", session.post.call_args.kwargs["json"]["instructions"])
        self.assertEqual("auto", session.post.call_args.kwargs["json"]["tool_choice"])
        self.assertEqual("gpt-5.4", session.post.call_args.kwargs["json"]["model"])
        self.assertEqual("user_123", session.post.call_args.kwargs["headers"]["chatgpt-account-id"])
        self.assertEqual("test-session", session.post.call_args.kwargs["headers"]["session_id"])

    def test_codex_edit_uses_native_responses_route_without_upload(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), color=(12, 34, 56)).save(buffer, format="PNG")
        image_data = buffer.getvalue()
        image_b64 = base64.b64encode(image_data).decode("ascii")
        session = mock.Mock()
        session.post.return_value = self._stream_response(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "image_generation_call",
                    "result": image_b64,
                    "output_format": "png",
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_456",
                    "created_at": 456,
                    "status": "completed",
                },
            },
        )

        with (
            mock.patch(
                "services.image_service.account_service.get_account",
                return_value={"type": "Pro", "user_id": "user_123"},
            ),
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
            mock.patch("services.image_service._upload_image") as upload_image,
            mock.patch("services.image_service._chat_requirements") as chat_requirements,
        ):
            result = edit_image_result(
                access_token="token",
                prompt="make it brighter",
                images=[(image_data, "reference.png", "image/png")],
                model="codex-gpt-image-2",
            )

        self.assertEqual(456, result["created"])
        self.assertIn("b64_json", result["data"][0])
        upload_image.assert_not_called()
        chat_requirements.assert_not_called()
        session.post.assert_called_once()
        input_payload = session.post.call_args.kwargs["json"]["input"]
        self.assertEqual("user", input_payload[0]["role"])
        self.assertEqual("input_text", input_payload[0]["content"][0]["type"])
        self.assertTrue(
            input_payload[0]["content"][1]["image_url"].startswith("data:image/png;base64,")
        )
        self.assertEqual("you are a helpful assistant", session.post.call_args.kwargs["json"]["instructions"])
        self.assertEqual("auto", session.post.call_args.kwargs["json"]["tool_choice"])

    def test_codex_responses_missing_image_output_raises_clear_error(self) -> None:
        session = mock.Mock()
        session.post.return_value = self._stream_response(
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_789",
                    "created_at": 789,
                    "status": "completed",
                    "output": [],
                },
            },
        )

        with (
            mock.patch(
                "services.image_service.account_service.get_account",
                return_value={"type": "Pro", "user_id": "user_123"},
            ),
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
        ):
            with self.assertRaisesRegex(
                ImageGenerationError,
                "codex responses did not return image output",
            ):
                edit_image_result(
                    access_token="token",
                    prompt="make it brighter",
                    images=[(b"png", "reference.png", "image/png")],
                    model="codex-gpt-image-2",
                )

    def test_codex_generate_wraps_connection_closed_post_error(self) -> None:
        session = mock.Mock()

        with (
            mock.patch(
                "services.image_service.account_service.get_account",
                return_value={"type": "Pro", "user_id": "user_123"},
            ),
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
            mock.patch(
                "services.image_service._retry",
                side_effect=RuntimeError(
                    "Failed to perform, curl: (56) Connection closed abruptly. "
                    "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
                ),
            ),
        ):
            with self.assertRaisesRegex(
                ImageGenerationError,
                "upstream image connection failed, please retry later",
            ):
                generate_image_result(
                    access_token="token",
                    prompt="draw a cat",
                    model="codex-gpt-image-2",
                )

    def test_codex_generate_wraps_connection_closed_stream_error(self) -> None:
        session = mock.Mock()
        response = mock.Mock()
        response.ok = True
        response.iter_lines.side_effect = RuntimeError(
            "Failed to perform, curl: (56) Connection closed abruptly. "
            "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
        )
        session.post.return_value = response

        with (
            mock.patch(
                "services.image_service.account_service.get_account",
                return_value={"type": "Pro", "user_id": "user_123"},
            ),
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
        ):
            with self.assertRaisesRegex(
                ImageGenerationError,
                "upstream image connection failed, please retry later",
            ):
                generate_image_result(
                    access_token="token",
                    prompt="draw a cat",
                    model="codex-gpt-image-2",
                )

    def test_edit_payload_preserves_attachment_metadata(self) -> None:
        image = EditInputImage(
            file_id="file_123",
            data=b"abc",
            file_name="reference.png",
            mime_type="image/png",
            width=640,
            height=480,
        )

        image_parts, attachments = _build_edit_input_payload([image])

        self.assertEqual("image_asset_pointer", image_parts[0]["content_type"])
        self.assertEqual("sediment://file_123", image_parts[0]["asset_pointer"])
        self.assertEqual("file_123", attachments[0]["id"])
        self.assertEqual("image/png", attachments[0]["mime_type"])

    def test_picture_v2_edit_payload_uses_file_service_pointer(self) -> None:
        image = EditInputImage(
            file_id="file_123",
            data=b"abc",
            file_name="reference.png",
            mime_type="image/png",
            width=640,
            height=480,
        )

        image_parts, attachments = _build_picture_v2_edit_input_payload([image])

        self.assertEqual("file-service://file_123", image_parts[0]["asset_pointer"])
        self.assertEqual("image/png", attachments[0]["mimeType"])

    def test_download_as_base64_retries_transient_download_failure(self) -> None:
        session = mock.Mock()
        session.get.side_effect = [
            self._download_response(502, text="bad gateway"),
            self._download_response(200, content=b"image-bytes"),
        ]

        b64_json = _download_as_base64(session, "https://example.com/image.png")

        self.assertEqual("aW1hZ2UtYnl0ZXM=", b64_json)
        self.assertEqual(2, session.get.call_count)

    def test_download_as_base64_reports_final_download_status(self) -> None:
        session = mock.Mock()
        session.get.return_value = self._download_response(403, text="expired")

        with self.assertRaisesRegex(ImageGenerationError, r"download image failed: HTTP 403: expired"):
            _download_as_base64(session, "https://example.com/image.png")

    def test_download_as_base64_retries_timeout_exception(self) -> None:
        session = mock.Mock()
        session.get.side_effect = [
            Exception("Failed to perform, curl: (28) Operation timed out after 60002 milliseconds with 1703751 bytes received."),
            self._download_response(200, content=b"image-bytes"),
        ]

        b64_json = _download_as_base64(session, "https://example.com/image.png")

        self.assertEqual("aW1hZ2UtYnl0ZXM=", b64_json)
        self.assertEqual(2, session.get.call_count)

    def test_download_as_base64_reports_timeout_as_connection_failure(self) -> None:
        session = mock.Mock()
        session.get.side_effect = Exception(
            "Failed to perform, curl: (28) Operation timed out after 60002 milliseconds with 1703751 bytes received."
        )

        with self.assertRaisesRegex(ImageGenerationError, r"upstream image connection failed, please retry later"):
            _download_as_base64(session, "https://example.com/image.png")

    def test_build_output_candidate_score_prefers_exact_size(self) -> None:
        exact_score = _build_output_candidate_score((941, 1672), (941, 1672))
        square_score = _build_output_candidate_score((1254, 1254), (941, 1672))

        self.assertLess(exact_score, square_score)

    def test_select_best_output_candidate_prefers_exact_size_over_first_candidate(self) -> None:
        square_candidate = ("file_square", b"square", (1254, 1254))
        exact_candidate = ("file_exact", b"exact", (941, 1672))

        selected = _select_best_output_candidate(
            [square_candidate, exact_candidate],
            (941, 1672),
        )

        self.assertEqual(exact_candidate, selected)

    def test_select_best_output_candidate_prefers_closest_aspect_ratio_when_no_exact_size(self) -> None:
        square_candidate = ("file_square", b"square", (1254, 1254))
        portrait_candidate = ("file_portrait", b"portrait", (1086, 1448))
        patch_candidate = ("file_patch", b"patch", (320, 320))

        selected = _select_best_output_candidate(
            [square_candidate, portrait_candidate, patch_candidate],
            (941, 1672),
        )

        self.assertEqual(portrait_candidate, selected)

    def test_composite_inpaint_same_size_patch_canvas_filters_placeholder_background(self) -> None:
        original = Image.new("RGBA", (20, 20), (12, 34, 56, 255))
        raw_output = Image.new("RGBA", (20, 20), (252, 252, 252, 255))
        for y in range(20):
            for x in range(20):
                shade = 252 if (x + y) % 2 == 0 else 196
                raw_output.putpixel((x, y), (shade, shade, shade, 255))
        for y in range(8, 12):
            for x in range(8, 12):
                raw_output.putpixel((x, y), (220, 30, 30, 255))

        mask = Image.new("RGBA", (20, 20), (255, 255, 255, 0))
        for y in range(6, 14):
            for x in range(6, 14):
                mask.putpixel((x, y), (255, 255, 255, 255))

        composited_bytes = _composite_inpaint_onto_original(
            self._png_bytes(raw_output),
            self._png_bytes(original),
            self._png_bytes(mask),
        )

        with Image.open(io.BytesIO(composited_bytes)) as composited:
            self.assertEqual((220, 30, 30, 255), composited.getpixel((9, 9)))
            self.assertEqual((12, 34, 56, 255), composited.getpixel((7, 7)))

    def test_composite_inpaint_same_size_full_frame_keeps_neutral_result_when_not_patch_canvas(self) -> None:
        original = Image.new("RGBA", (20, 20), (12, 34, 56, 255))
        raw_output = Image.new("RGBA", (20, 20), (230, 230, 230, 255))

        mask = Image.new("RGBA", (20, 20), (255, 255, 255, 0))
        for y in range(6, 14):
            for x in range(6, 14):
                mask.putpixel((x, y), (255, 255, 255, 255))

        composited_bytes = _composite_inpaint_onto_original(
            self._png_bytes(raw_output),
            self._png_bytes(original),
            self._png_bytes(mask),
        )

        with Image.open(io.BytesIO(composited_bytes)) as composited:
            self.assertEqual((230, 230, 230, 255), composited.getpixel((9, 9)))
            self.assertEqual((12, 34, 56, 255), composited.getpixel((2, 2)))

    def test_composite_inpaint_same_size_full_frame_light_background_keeps_mask_area(self) -> None:
        original = Image.new("RGBA", (24, 24), (12, 34, 56, 255))
        raw_output = Image.new("RGBA", (24, 24), (242, 242, 242, 255))
        for y in range(9, 15):
            for x in range(9, 15):
                raw_output.putpixel((x, y), (220, 30, 30, 255))

        mask = Image.new("RGBA", (24, 24), (255, 255, 255, 0))
        for y in range(6, 18):
            for x in range(6, 18):
                mask.putpixel((x, y), (255, 255, 255, 255))

        composited_bytes = _composite_inpaint_onto_original(
            self._png_bytes(raw_output),
            self._png_bytes(original),
            self._png_bytes(mask),
        )

        with Image.open(io.BytesIO(composited_bytes)) as composited:
            self.assertEqual((242, 242, 242, 255), composited.getpixel((7, 7)))
            self.assertEqual((220, 30, 30, 255), composited.getpixel((12, 12)))
            self.assertEqual((12, 34, 56, 255), composited.getpixel((3, 3)))

    def test_composite_inpaint_same_size_full_frame_feathers_context_past_mask_edge(self) -> None:
        original = Image.new("RGBA", (24, 24), (12, 34, 56, 255))
        raw_output = Image.new("RGBA", (24, 24), (12, 34, 56, 255))
        for y in range(8, 16):
            for x in range(8, 16):
                raw_output.putpixel((x, y), (220, 30, 30, 255))
        for y in range(7, 17):
            raw_output.putpixel((7, y), (80, 200, 80, 255))
            raw_output.putpixel((16, y), (80, 200, 80, 255))
        for x in range(7, 17):
            raw_output.putpixel((x, 7), (80, 200, 80, 255))
            raw_output.putpixel((x, 16), (80, 200, 80, 255))

        mask = Image.new("RGBA", (24, 24), (255, 255, 255, 0))
        for y in range(8, 16):
            for x in range(8, 16):
                mask.putpixel((x, y), (255, 255, 255, 255))

        composited_bytes = _composite_inpaint_onto_original(
            self._png_bytes(raw_output),
            self._png_bytes(original),
            self._png_bytes(mask),
        )

        with Image.open(io.BytesIO(composited_bytes)) as composited:
            self.assertEqual((220, 30, 30, 255), composited.getpixel((12, 12)))
            edge_pixel = composited.getpixel((7, 12))
            self.assertGreater(edge_pixel[1], 34)
            self.assertNotEqual((12, 34, 56, 255), edge_pixel)
            self.assertEqual((12, 34, 56, 255), composited.getpixel((4, 12)))

    def test_composite_inpaint_same_size_near_full_mask_stays_full_frame(self) -> None:
        original = Image.new("RGBA", (32, 32), (30, 40, 80, 255))
        raw_output = Image.new("RGBA", (32, 32), (252, 252, 252, 255))
        for y in range(32):
            for x in range(32):
                shade = 252 if (x + y) % 2 == 0 else 196
                raw_output.putpixel((x, y), (shade, shade, shade, 255))
        for y in range(10, 22):
            for x in range(10, 22):
                raw_output.putpixel((x, y), (220, 30, 30, 255))

        mask = Image.new("RGBA", (32, 32), (255, 255, 255, 0))
        for y in range(8, 24):
            for x in range(8, 24):
                mask.putpixel((x, y), (255, 255, 255, 255))

        composited_bytes = _composite_inpaint_onto_original(
            self._png_bytes(raw_output),
            self._png_bytes(original),
            self._png_bytes(mask),
        )

        with Image.open(io.BytesIO(composited_bytes)) as composited:
            self.assertEqual((252, 252, 252, 255), composited.getpixel((9, 9)))
            self.assertEqual((220, 30, 30, 255), composited.getpixel((16, 16)))
            self.assertEqual((30, 40, 80, 255), composited.getpixel((1, 1)))

    def test_composite_inpaint_same_size_full_frame_with_strong_outside_drift_prefers_generated_frame(self) -> None:
        original = Image.new("RGBA", (24, 24), (12, 34, 56, 255))
        raw_output = Image.new("RGBA", (24, 24), (170, 210, 120, 255))
        for y in range(8, 16):
            for x in range(8, 16):
                raw_output.putpixel((x, y), (220, 30, 30, 255))

        mask = Image.new("RGBA", (24, 24), (255, 255, 255, 0))
        for y in range(9, 15):
            for x in range(9, 15):
                mask.putpixel((x, y), (255, 255, 255, 255))

        composited_bytes = _composite_inpaint_onto_original(
            self._png_bytes(raw_output),
            self._png_bytes(original),
            self._png_bytes(mask),
        )

        with Image.open(io.BytesIO(composited_bytes)) as composited:
            self.assertEqual((170, 210, 120, 255), composited.getpixel((2, 2)))
            self.assertEqual((220, 30, 30, 255), composited.getpixel((12, 12)))

    def test_composite_inpaint_square_output_with_local_mask_uses_bbox_projection(self) -> None:
        original = Image.new("RGBA", (100, 100), (12, 34, 56, 255))
        raw_output = Image.new("RGBA", (50, 50), (210, 210, 210, 255))
        for y in range(18, 32):
            for x in range(18, 32):
                raw_output.putpixel((x, y), (220, 30, 30, 255))

        mask = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
        for y in range(10, 30):
            for x in range(40, 60):
                mask.putpixel((x, y), (255, 255, 255, 255))

        composited_bytes = _composite_inpaint_onto_original(
            self._png_bytes(raw_output),
            self._png_bytes(original),
            self._png_bytes(mask),
        )

        with Image.open(io.BytesIO(composited_bytes)) as composited:
            center_pixel = composited.getpixel((50, 20))
            self.assertGreaterEqual(center_pixel[0], 200)
            self.assertLessEqual(center_pixel[1], 80)
            self.assertLessEqual(center_pixel[2], 80)
            self.assertEqual(255, center_pixel[3])
            self.assertEqual((12, 34, 56, 255), composited.getpixel((10, 10)))

    def test_composite_inpaint_different_size_full_frame_variant_with_local_mask_keeps_scene_alignment(self) -> None:
        original = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        for y in range(100):
            for x in range(100):
                original.putpixel((x, y), (x, y, 120, 255))

        raw_output = original.resize((120, 120), Image.Resampling.BICUBIC)
        for y in range(54, 66):
            for x in range(54, 66):
                raw_output.putpixel((x, y), (220, 30, 30, 255))

        mask = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
        for y in range(40, 60):
            for x in range(40, 60):
                mask.putpixel((x, y), (255, 255, 255, 255))

        composited_bytes = _composite_inpaint_onto_original(
            self._png_bytes(raw_output),
            self._png_bytes(original),
            self._png_bytes(mask),
        )

        with Image.open(io.BytesIO(composited_bytes)) as composited:
            center_pixel = composited.getpixel((50, 50))
            self.assertGreaterEqual(center_pixel[0], 210)
            self.assertLessEqual(center_pixel[1], 40)
            self.assertLessEqual(center_pixel[2], 40)
            self.assertEqual(255, center_pixel[3])
            # 若误把整图结果压进局部 bbox，这个点会采样到整图左上角，颜色会明显偏离原场景。
            self.assertEqual((42, 42, 120, 255), composited.getpixel((42, 42)))
            self.assertEqual((12, 12, 120, 255), composited.getpixel((12, 12)))

    def test_build_image_result_data_resizes_and_reencodes_requested_output(self) -> None:
        source = io.BytesIO()
        Image.new("RGBA", (1024, 1024), (255, 0, 0, 255)).save(source, format="PNG")

        with mock.patch("services.image_service._fetch_image_bytes", return_value=source.getvalue()):
            result = _build_image_result_data(
                "draw a cat",
                "b64_json",
                "regular",
                image_options=ImageRequestOptions(size="2048x1024", output_format="webp", compression=20),
                session=mock.Mock(),
                download_url="https://example.com/image.png",
                base_url=None,
            )

        self.assertEqual("image/webp", result["mime_type"])
        decoded = base64.b64decode(result["b64_json"])
        with Image.open(io.BytesIO(decoded)) as generated:
            self.assertEqual((2048, 1024), generated.size)
            self.assertEqual("WEBP", generated.format)

    def test_regular_picture_payload_without_images_uses_text_message(self) -> None:
        body = _build_regular_picture_v2_body("draw a cat", "parent", "gpt-5-3")

        self.assertEqual("text", body["messages"][0]["content"]["content_type"])
        self.assertEqual(["draw a cat"], body["messages"][0]["content"]["parts"])
        self.assertNotIn("attachments", body["messages"][0]["metadata"])

    def test_legacy_regular_generation_retries_without_conversation_id_after_404(self) -> None:
        response = mock.Mock()
        with (
            mock.patch(
                "services.image_service._send_conversation",
                side_effect=[ImageGenerationError("conversation failed: 404"), response],
            ) as send_conversation,
            mock.patch(
                "services.image_service._parse_sse",
                return_value={"conversation_id": "conversation_regular", "file_ids": ["file_output_1"], "text": ""},
            ) as parse_sse,
        ):
            parsed = _run_legacy_regular_generation_mode(
                session=mock.Mock(),
                access_token="token",
                device_id="device",
                chat_token="chat-token",
                proof_token=None,
                parent_message_id="parent",
                prompt="draw a cat",
                upstream_model="gpt-5-3",
                conversation_id="conversation_existing",
            )

        self.assertEqual("conversation_regular", parsed["conversation_id"])
        self.assertEqual(2, send_conversation.call_count)
        self.assertEqual("conversation_existing", send_conversation.call_args_list[0].kwargs["conversation_id"])
        self.assertEqual("", send_conversation.call_args_list[1].kwargs["conversation_id"])
        parse_sse.assert_called_once_with(response)

    def test_legacy_regular_edit_retries_without_conversation_id_after_403(self) -> None:
        response = mock.Mock()
        with (
            mock.patch(
                "services.image_service._send_edit_conversation",
                side_effect=[ImageGenerationError("conversation failed: 403"), response],
            ) as send_edit,
            mock.patch("services.image_service._parse_sse", return_value={"conversation_id": "conversation_regular"}) as parse_sse,
        ):
            parsed = _run_legacy_regular_edit_mode(
                session=mock.Mock(),
                access_token="token",
                device_id="device",
                chat_token="chat-token",
                proof_token=None,
                parent_message_id="parent",
                prompt="make it brighter",
                upstream_model="auto",
                images=[],
                conversation_id="conversation_existing",
            )

        self.assertEqual({"conversation_id": "conversation_regular"}, parsed)
        self.assertEqual(2, send_edit.call_count)
        self.assertEqual("conversation_existing", send_edit.call_args_list[0].kwargs["conversation_id"])
        self.assertEqual("", send_edit.call_args_list[1].kwargs["conversation_id"])
        parse_sse.assert_called_once_with(response)

    def test_standard_generation_uses_regular_picture_pipeline(self) -> None:
        session = mock.Mock()

        with (
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
            mock.patch("services.image_service._chat_requirements", return_value=("chat-token", {})),
            mock.patch(
                "services.image_service._run_regular_generation_mode",
                return_value={"conversation_id": "conversation_regular", "file_ids": ["file_output"], "text": ""},
            ) as run_regular,
            mock.patch("services.image_service._conversation_init") as conversation_init,
            mock.patch("services.image_service._run_legacy_regular_generation_mode") as run_legacy,
            mock.patch("services.image_service._fetch_download_url", return_value="https://example.com/image.png"),
            mock.patch("services.image_service._fetch_image_bytes", return_value=b"fake"),
        ):
            result = generate_image_result(
                access_token="token",
                prompt="draw a cat",
                model="gpt-image-2",
            )

        self.assertEqual("regular", result["data"][0]["generation_route"])
        run_regular.assert_called_once()
        self.assertEqual("gpt-5-3", run_regular.call_args.args[7])
        conversation_init.assert_not_called()
        run_legacy.assert_not_called()
        session.close.assert_called_once()

    def test_standard_generation_regular_pipeline_forbidden_falls_back_to_legacy(self) -> None:
        session = mock.Mock()

        with (
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
            mock.patch("services.image_service._chat_requirements", return_value=("chat-token", {})),
            mock.patch("services.image_service._run_regular_generation_mode", side_effect=ImageGenerationError("f/conversation failed: 403")),
            mock.patch("services.image_service._conversation_init", return_value="conversation_initial"),
            mock.patch(
                "services.image_service._run_legacy_regular_generation_mode",
                return_value={"conversation_id": "conversation_regular", "file_ids": ["file_output"], "text": ""},
            ) as run_legacy,
            mock.patch("services.image_service._fetch_download_url", return_value="https://example.com/image.png"),
            mock.patch("services.image_service._fetch_image_bytes", return_value=b"fake"),
        ):
            result = generate_image_result(
                access_token="token",
                prompt="draw a cat",
                model="gpt-image-2",
            )

        self.assertEqual("fallback", result["data"][0]["generation_route"])
        run_legacy.assert_called_once()
        self.assertEqual("gpt-5-3", run_legacy.call_args.args[7])
        self.assertEqual("conversation_initial", run_legacy.call_args.args[8])

    def test_extract_image_ids_accepts_new_message_shapes(self) -> None:
        mapping = {
            "node_1": {
                "message": {
                    "author": {"role": "assistant"},
                    "content": {
                        "content_type": "output_image",
                        "items": [
                            {"asset_pointer": "file-service://file_output_1"},
                            {"nested": {"asset_pointer": "sediment://file_output_2"}},
                        ],
                    },
                }
            }
        }

        file_ids = _extract_image_ids(mapping)

        self.assertEqual(["file_output_1", "sed:file_output_2"], file_ids)

    def test_extract_image_ids_accepts_string_parts_from_tool_messages(self) -> None:
        mapping = {
            "node_1": {
                "message": {
                    "author": {"role": "tool"},
                    "metadata": {"async_task_type": "image_gen"},
                    "content": {
                        "content_type": "multimodal_text",
                        "parts": [
                            "generated file-service://file_output_3 for preview",
                            "fallback sediment://file_output_4",
                        ],
                    },
                }
            }
        }

        file_ids = _extract_image_ids(mapping)

        self.assertEqual(["file_output_3", "sed:file_output_4"], file_ids)

    def test_parse_sse_extracts_conversation_id_from_raw_payload(self) -> None:
        response = mock.Mock()
        response.iter_lines.return_value = [
            b'data: {"type":"message_marker","conversation_id":"conversation_from_raw","note":"partial"}',
            b"data: [DONE]",
        ]

        parsed = _parse_sse(response)

        self.assertEqual("conversation_from_raw", parsed["conversation_id"])

    def test_collect_edit_output_passes_input_ids_into_polling(self) -> None:
        parsed = {"conversation_id": "conversation_regular", "file_ids": [], "text": ""}
        session = mock.Mock()

        with mock.patch(
            "services.image_service._poll_image_ids",
            return_value=["file_output_5"],
        ) as poll_image_ids:
            actual_conversation_id, file_ids, response_text = _collect_edit_output(
                session=session,
                access_token="token",
                device_id="device",
                parsed=parsed,
                input_file_ids={"file_input"},
            )

        self.assertEqual("conversation_regular", actual_conversation_id)
        self.assertEqual(["file_output_5"], file_ids)
        self.assertEqual("", response_text)
        poll_image_ids.assert_called_once_with(
            session,
            "token",
            "device",
            "conversation_regular",
            {"file_input"},
            force_poll_past_text=False,
        )

    def test_collect_edit_output_filters_invalid_file_upload_id_before_polling(self) -> None:
        parsed = {"conversation_id": "conversation_regular", "file_ids": ["file_upload"], "text": ""}
        session = mock.Mock()

        with mock.patch(
            "services.image_service._poll_image_ids",
            return_value=["file_output_5"],
        ) as poll_image_ids:
            actual_conversation_id, file_ids, response_text = _collect_edit_output(
                session=session,
                access_token="token",
                device_id="device",
                parsed=parsed,
                input_file_ids={"file_input"},
            )

        self.assertEqual("conversation_regular", actual_conversation_id)
        self.assertEqual(["file_output_5"], file_ids)
        self.assertEqual("", response_text)
        poll_image_ids.assert_called_once_with(
            session,
            "token",
            "device",
            "conversation_regular",
            {"file_input"},
            force_poll_past_text=False,
        )

    def test_edit_think_model_uses_regular_image_pipeline(self) -> None:
        session = mock.Mock()
        regular_parsed = {"conversation_id": "conversation_regular", "file_ids": ["file_output"], "text": ""}

        with (
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
            mock.patch("services.image_service._upload_image", return_value="file_input"),
            mock.patch("services.image_service._get_image_dimensions", return_value=(1024, 1024)),
            mock.patch("services.image_service._chat_requirements", return_value=("chat-token", {})),
            mock.patch("services.image_service._conversation_init", return_value="conversation_initial"),
            mock.patch("services.image_service._poll_image_ids", return_value=[]),
            mock.patch(
                "services.image_service._run_regular_edit_mode",
                return_value=regular_parsed,
            ) as run_regular,
            mock.patch("services.image_service._run_legacy_regular_edit_mode") as run_legacy_regular,
            mock.patch("services.image_service._fetch_download_url", return_value="https://example.com/image.png"),
            mock.patch("services.image_service._fetch_image_bytes", return_value=b"fake"),
        ):
            result = edit_image_result(
                access_token="token",
                prompt="make it brighter",
                images=[(b"image-data", "reference.png", "image/png")],
                model="gpt-image-think",
            )

        self.assertEqual("regular", result["data"][0]["generation_route"])
        run_regular.assert_called_once()
        self.assertEqual("gpt-5-3", run_regular.call_args.args[7])
        run_legacy_regular.assert_not_called()
        session.close.assert_called_once()

    def test_standard_edit_uses_regular_image_pipeline(self) -> None:
        session = mock.Mock()

        with (
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
            mock.patch("services.image_service._upload_image", return_value="file_input"),
            mock.patch("services.image_service._get_image_dimensions", return_value=(1024, 1024)),
            mock.patch("services.image_service._chat_requirements", return_value=("chat-token", {})),
            mock.patch("services.image_service._conversation_init", return_value="conversation_initial"),
            mock.patch(
                "services.image_service._run_regular_edit_mode",
                return_value={"conversation_id": "conversation_regular", "file_ids": ["file_output"], "text": ""},
            ) as run_regular,
            mock.patch("services.image_service._send_edit_conversation") as legacy_send_regular,
            mock.patch("services.image_service._fetch_download_url", return_value="https://example.com/image.png"),
            mock.patch("services.image_service._fetch_image_bytes", return_value=b"fake"),
        ):
            result = edit_image_result(
                access_token="token",
                prompt="make it brighter",
                images=[(b"image-data", "reference.png", "image/png")],
                model="gpt-image-2",
            )

        self.assertEqual("regular", result["data"][0]["generation_route"])
        run_regular.assert_called_once()
        self.assertEqual("gpt-5-3", run_regular.call_args.args[7])
        legacy_send_regular.assert_not_called()
        session.close.assert_called_once()

    def test_edit_regular_pipeline_forbidden_falls_back_to_legacy_auto(self) -> None:
        session = mock.Mock()
        regular_parsed = {"conversation_id": "conversation_regular", "file_ids": ["file_output"], "text": ""}

        with (
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
            mock.patch("services.image_service._upload_image", return_value="file_input"),
            mock.patch("services.image_service._get_image_dimensions", return_value=(1024, 1024)),
            mock.patch("services.image_service._chat_requirements", return_value=("chat-token", {})),
            mock.patch("services.image_service._conversation_init", return_value="conversation_initial"),
            mock.patch("services.image_service._run_regular_edit_mode", side_effect=ImageGenerationError("f/conversation failed: 403")),
            mock.patch("services.image_service._run_legacy_regular_edit_mode", return_value=regular_parsed) as run_legacy_regular,
            mock.patch("services.image_service._poll_image_ids", return_value=[]),
            mock.patch("services.image_service._fetch_download_url", return_value="https://example.com/image.png"),
            mock.patch("services.image_service._fetch_image_bytes", return_value=b"fake"),
        ):
            result = edit_image_result(
                access_token="token",
                prompt="make it brighter",
                images=[(b"image-data", "reference.png", "image/png")],
                model="gpt-image-2",
            )

        self.assertEqual("regular", result["data"][0]["generation_route"])
        run_legacy_regular.assert_called_once()
        self.assertEqual("auto", run_legacy_regular.call_args.args[7])
        session.close.assert_called_once()

    def test_edit_with_pool_retries_transient_upstream_empty_result_once(self) -> None:
        account_service = mock.Mock()
        account_service.get_available_access_token.side_effect = ["token-1", "token-2"]
        account_service.mark_image_result.side_effect = [
            {"quota": 25, "status": "正常"},
            {"quota": 24, "status": "正常"},
        ]
        service = ChatGPTService(account_service)
        success_result = {"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]}

        with mock.patch(
            "services.chatgpt_service.edit_image_result",
            side_effect=[ImageGenerationError("no image returned from upstream"), success_result],
        ) as edit_image_result_mock:
            result = service.edit_with_pool(
                prompt="make it brighter",
                images=[(b"image-data", "reference.png", "image/png")],
                model="gpt-image-2",
                n=1,
            )

        self.assertEqual(success_result, result)
        self.assertEqual(2, edit_image_result_mock.call_count)
        self.assertEqual(
            [
                mock.call(
                    "token-1",
                    "make it brighter",
                    [(b"image-data", "reference.png", "image/png")],
                    "gpt-image-2",
                    image_options=None,
                    response_format="b64_json",
                    base_url=None,
                ),
                mock.call(
                    "token-2",
                    "make it brighter",
                    [(b"image-data", "reference.png", "image/png")],
                    "gpt-image-2",
                    image_options=None,
                    response_format="b64_json",
                    base_url=None,
                ),
            ],
            edit_image_result_mock.call_args_list,
        )

    def test_codex_generate_with_pool_uses_codex_account_selection_and_preserves_chatgpt_quota(self) -> None:
        account_service = mock.Mock()
        account_service.get_codex_image_access_token.return_value = "token-codex"
        account_service.mark_codex_image_result.return_value = {"quota": 0, "status": "限流"}
        service = ChatGPTService(account_service)
        success_result = {"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]}

        with mock.patch(
            "services.chatgpt_service.generate_image_result",
            return_value=success_result,
        ) as generate_image_result_mock:
            result = service.generate_with_pool(
                prompt="draw a cat",
                model="codex-gpt-image-2",
                n=1,
            )

        self.assertEqual(success_result, result)
        account_service.get_codex_image_access_token.assert_called_once_with()
        account_service.mark_codex_image_result.assert_called_once_with("token-codex", success=True)
        account_service.mark_image_result.assert_not_called()
        generate_image_result_mock.assert_called_once_with(
            "token-codex",
            "draw a cat",
            "codex-gpt-image-2",
            image_options=None,
            response_format="b64_json",
            base_url=None,
        )

    def test_codex_generate_with_pool_skips_rate_limited_token_and_retries_next_paid_account(self) -> None:
        account_service = mock.Mock()
        account_service.get_codex_image_access_token.side_effect = ["token-codex-1", "token-codex-2"]
        account_service.mark_codex_image_result.side_effect = [
            {"quota": 119, "status": "正常"},
            {"quota": 118, "status": "正常"},
        ]
        service = ChatGPTService(account_service)
        success_result = {"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]}

        with mock.patch(
            "services.chatgpt_service.generate_image_result",
            side_effect=[ImageGenerationError("codex responses failed: 429"), success_result],
        ) as generate_image_result_mock:
            result = service.generate_with_pool(
                prompt="draw a cat",
                model="codex-gpt-image-2",
                n=1,
            )

        self.assertEqual(success_result, result)
        self.assertEqual(2, account_service.get_codex_image_access_token.call_count)
        account_service.update_account.assert_called_once_with("token-codex-1", {"status": "限流"})
        self.assertEqual(2, account_service.mark_codex_image_result.call_count)
        self.assertEqual(2, generate_image_result_mock.call_count)

    def test_regular_edit_stream_wraps_tls_errors_as_image_generation_error(self) -> None:
        with mock.patch(
            "services.image_service._retry",
            side_effect=RuntimeError("curl: (35) TLS connect error: error:0A000438:SSL routines::tlsv1 alert internal error"),
        ):
            with self.assertRaisesRegex(
                ImageGenerationError,
                "upstream image connection failed, please retry later",
            ):
                _send_regular_edit_conversation(
                    session=mock.Mock(),
                    access_token="token",
                    device_id="device",
                    chat_token="chat-token",
                    proof_token=None,
                    parent_message_id="parent",
                    prompt="make it brighter",
                    model="gpt-5-3",
                    images=[],
                    conduit_token="conduit-token",
                )

    def test_edit_result_normalizes_tls_error_text_from_upstream(self) -> None:
        session = mock.Mock()

        with (
            mock.patch("services.image_service._new_session", return_value=(session, "fp")),
            mock.patch("services.image_service._bootstrap", return_value="device"),
            mock.patch("services.image_service._upload_image", return_value="file_input"),
            mock.patch("services.image_service._get_image_dimensions", return_value=(1024, 1024)),
            mock.patch("services.image_service._chat_requirements", return_value=("chat-token", {})),
            mock.patch("services.image_service._conversation_init", return_value="conversation_initial"),
            mock.patch("services.image_service._run_regular_edit_mode", return_value={"conversation_id": "conversation_regular"}),
            mock.patch(
                "services.image_service._collect_edit_output",
                return_value=(
                    "conversation_regular",
                    [],
                    "curl: (35) TLS connect error: error:0A000438:SSL routines::tlsv1 alert internal error",
                ),
            ),
        ):
            with self.assertRaisesRegex(
                ImageGenerationError,
                "upstream image connection failed, please retry later",
            ):
                edit_image_result(
                    access_token="token",
                    prompt="make it brighter",
                    images=[(b"image-data", "reference.png", "image/png")],
                    model="gpt-image-2",
                )

    def test_create_image_completion_passes_multiple_reference_images(self) -> None:
        service = ChatGPTService(mock.Mock())
        body = {
            "model": "gpt-image-2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "edit this"},
                        {"type": "input_image", "image_url": "data:image/png;base64,Zmlyc3Q="},
                        {"type": "input_image", "image_url": "data:image/png;base64,c2Vjb25k"},
                    ],
                }
            ],
        }

        with mock.patch.object(
            service,
            "edit_with_pool",
            return_value={"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]},
        ) as edit_with_pool:
            service.create_image_completion(body)

        images = edit_with_pool.call_args.args[1]
        self.assertEqual(
            [
                (b"first", "image_1.png", "image/png"),
                (b"second", "image_2.png", "image/png"),
            ],
            images,
        )

    def test_create_image_completion_accumulates_reference_images_from_user_turns(self) -> None:
        service = ChatGPTService(mock.Mock())
        body = {
            "model": "gpt-image-2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "old edit"},
                        {"type": "input_image", "image_url": "data:image/png;base64,b2xk"},
                    ],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "new edit"},
                        {"type": "input_image", "image_url": "data:image/png;base64,bmV3"},
                    ],
                },
            ],
        }

        with mock.patch.object(
            service,
            "edit_with_pool",
            return_value={"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]},
        ) as edit_with_pool:
            service.create_image_completion(body)

        images = edit_with_pool.call_args.args[1]
        self.assertEqual(
            [
                (b"new", "image_1.png", "image/png"),
                (b"old", "image_2.png", "image/png"),
            ],
            images,
        )

    def test_create_response_passes_multiple_reference_images(self) -> None:
        service = ChatGPTService(mock.Mock())
        body = {
            "model": "gpt-5",
            "tools": [{"type": "image_generation"}],
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "edit this"},
                        {"type": "input_image", "image_url": "data:image/png;base64,Zmlyc3Q="},
                        {"type": "input_image", "image_url": "data:image/png;base64,c2Vjb25k"},
                    ],
                }
            ],
        }

        with mock.patch.object(
            service,
            "edit_with_pool",
            return_value={"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]},
        ) as edit_with_pool:
            service.create_response(body)

        images = edit_with_pool.call_args.args[1]
        self.assertEqual(
            [
                (b"first", "image_1.png", "image/png"),
                (b"second", "image_2.png", "image/png"),
            ],
            images,
        )

    def test_create_response_uses_latest_user_turn_with_images(self) -> None:
        service = ChatGPTService(mock.Mock())
        body = {
            "model": "gpt-5",
            "tools": [{"type": "image_generation"}],
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "old edit"},
                        {"type": "input_image", "image_url": "data:image/png;base64,b2xk"},
                    ],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "new edit"},
                        {"type": "input_image", "image_url": "data:image/png;base64,bmV3"},
                    ],
                },
            ],
        }

        with mock.patch.object(
            service,
            "edit_with_pool",
            return_value={"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]},
        ) as edit_with_pool:
            service.create_response(body)

        images = edit_with_pool.call_args.args[1]
        self.assertEqual([(b"new", "image_1.png", "image/png")], images)

    def test_create_response_uses_image_model_when_requested(self) -> None:
        service = ChatGPTService(mock.Mock())
        body = {
            "model": "codex-gpt-image-2",
            "tools": [{"type": "image_generation"}],
            "input": "draw a cat",
        }

        with mock.patch.object(
            service,
            "generate_with_pool",
            return_value={"created": 123, "data": [{"b64_json": "ZmFrZQ=="}]},
        ) as generate_with_pool:
            service.create_response(body)

        self.assertEqual("codex-gpt-image-2", generate_with_pool.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
