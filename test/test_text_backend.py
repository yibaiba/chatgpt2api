from __future__ import annotations

import unittest
from unittest import mock

from services.text_backend import TextBackend, TextBackendError


class TextBackendModelFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = mock.Mock()
        self.patches = [
            mock.patch("services.text_backend._new_session", return_value=(self.session, object())),
            mock.patch("services.text_backend._bootstrap", return_value="device-id"),
            mock.patch("services.text_backend._chat_requirements", return_value=("chat-token", {"required": False})),
            mock.patch("services.text_backend._conversation_init", return_value="conv-initial"),
        ]
        for patcher in self.patches:
            patcher.start()
        self.addCleanup(self._cleanup_patches)

    def _cleanup_patches(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_complete_retries_with_auto_when_requested_model_is_forbidden(self) -> None:
        send_conversation = mock.Mock(
            side_effect=[
                TextBackendError("conversation failed: 403"),
                mock.sentinel.response_auto,
            ]
        )
        iter_events = mock.Mock(
            return_value=iter(
                [
                    {
                        "conversation_id": "conv-initial",
                        "parent_message_id": "msg-final",
                        "text": "hello reply",
                    }
                ]
            )
        )

        with mock.patch("services.text_backend._send_text_conversation", send_conversation), mock.patch(
            "services.text_backend._iter_text_sse_events", iter_events
        ):
            result = TextBackend("token").complete("hello", "gpt-5")

        self.assertEqual("auto", result["model"])
        self.assertEqual("hello reply", result["text"])
        self.assertEqual("gpt-5", send_conversation.call_args_list[0].args[7])
        self.assertEqual("auto", send_conversation.call_args_list[1].args[7])

    def test_stream_retries_with_auto_when_requested_model_is_forbidden(self) -> None:
        send_conversation = mock.Mock(
            side_effect=[
                TextBackendError("conversation failed: 403"),
                mock.sentinel.response_auto,
            ]
        )
        iter_events = mock.Mock(
            return_value=iter(
                [
                    {
                        "conversation_id": "conv-initial",
                        "parent_message_id": "msg-final",
                        "text": "hello reply",
                    }
                ]
            )
        )

        with mock.patch("services.text_backend._send_text_conversation", send_conversation), mock.patch(
            "services.text_backend._iter_text_sse_events", iter_events
        ):
            events = list(TextBackend("token").stream("hello", "gpt-5"))

        self.assertEqual(1, len(events))
        self.assertEqual("auto", events[0]["model"])
        self.assertEqual("gpt-5", send_conversation.call_args_list[0].args[7])
        self.assertEqual("auto", send_conversation.call_args_list[1].args[7])


if __name__ == "__main__":
    unittest.main()
