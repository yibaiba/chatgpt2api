from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.image_service import (
    EditInputImage,
    ImageGenerationError,
    _build_edit_input_payload,
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
    edit_image_result,
    generate_image_result,
)
from services.chatgpt_service import ChatGPTService


class ImageModelRoutingTests(unittest.TestCase):
    def _download_response(self, status_code: int, content: bytes = b"", text: str = ""):
        response = mock.Mock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 400
        response.content = content
        response.text = text
        return response

    def test_standard_model_uses_regular_picture_pipeline_slug(self) -> None:
        with mock.patch("services.image_service.account_service.get_account", return_value={"type": "Pro"}):
            upstream_model, use_thinking = _resolve_upstream_model("token", "gpt-image-2")

        self.assertEqual("gpt-5-3", upstream_model)
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

    def test_edit_models_follow_upstream_picture_pipeline_slug(self) -> None:
        self.assertEqual("gpt-5-3", _resolve_upstream_edit_model("gpt-image-2"))
        self.assertEqual("gpt-5-3", _resolve_upstream_edit_model("gpt-image-think"))
        self.assertEqual("gpt-5-3", _resolve_upstream_edit_model("gpt-image-1"))

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
            mock.patch("services.image_service._download_as_base64", return_value="ZmFrZQ=="),
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
            mock.patch("services.image_service._download_as_base64", return_value="ZmFrZQ=="),
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
            mock.patch("services.image_service._download_as_base64", return_value="ZmFrZQ=="),
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
            mock.patch("services.image_service._download_as_base64", return_value="ZmFrZQ=="),
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
            mock.patch("services.image_service._download_as_base64", return_value="ZmFrZQ=="),
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
                mock.call("token-1", "make it brighter", [(b"image-data", "reference.png", "image/png")], "gpt-image-2", "b64_json", None),
                mock.call("token-2", "make it brighter", [(b"image-data", "reference.png", "image/png")], "gpt-image-2", "b64_json", None),
            ],
            edit_image_result_mock.call_args_list,
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


if __name__ == "__main__":
    unittest.main()
