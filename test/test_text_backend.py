from __future__ import annotations

import unittest
from unittest import mock

from services.text_backend import (
    CLIENT_CREATED_ROOT,
    NO_CONDUIT_TOKEN,
    TextBackend,
    TextBackendError,
    _iter_text_sse_events,
    _prepare_text_transport,
    _send_text_conversation,
)


class TextBackendModelFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = mock.Mock()
        self.patches = [
            mock.patch("services.text_backend._new_session", return_value=(self.session, object())),
            mock.patch("services.text_backend._bootstrap", return_value="device-id"),
            mock.patch(
                "services.text_backend._prepare_text_transport",
                return_value={
                    "chat_token": "chat-token",
                    "proof_token": "proof-token",
                    "conduit_token": "conduit-token",
                },
            ),
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


class _FakeSseResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    def iter_lines(self):
        for line in self._lines:
            yield line


class TextBackendSseParserTests(unittest.TestCase):
    def test_iter_text_sse_events_parses_f_conversation_delta_chunks(self) -> None:
        response = _FakeSseResponse(
            [
                'event: delta_encoding',
                'data: "v1"',
                'data: {"type":"resume_conversation_token","conversation_id":"conv-1","token":"resume-token"}',
                'event: delta',
                'data: {"v":{"message":{"id":"assistant-msg","author":{"role":"assistant"},"content":{"content_type":"text","parts":[""]}},"conversation_id":"conv-1"}}',
                'data: {"type":"message_marker","conversation_id":"conv-1","message_id":"assistant-msg","marker":"user_visible_token"}',
                'event: delta',
                'data: {"p":"/message/content/parts/0","o":"append","v":"hello"}',
                'event: delta',
                'data: {"v":" world"}',
                'event: delta',
                'data: {"p":"","o":"patch","v":[{"p":"/message/content/parts/0","o":"append","v":"!"}]}',
                'data: {"type":"message_stream_complete","conversation_id":"conv-1"}',
                'data: [DONE]',
            ]
        )

        events = list(_iter_text_sse_events(response))

        self.assertEqual(["hello", "hello world", "hello world!"], [event["text"] for event in events])
        self.assertEqual("conv-1", events[-1]["conversation_id"])
        self.assertEqual("assistant-msg", events[-1]["parent_message_id"])

    def test_iter_text_sse_events_keeps_legacy_snapshot_behavior(self) -> None:
        response = _FakeSseResponse(
            [
                'data: {"conversation_id":"conv-legacy","message":{"id":"msg-legacy","author":{"role":"assistant"},"content":{"content_type":"text","parts":["legacy reply"]}}}',
                'data: [DONE]',
            ]
        )

        events = list(_iter_text_sse_events(response))

        self.assertEqual(1, len(events))
        self.assertEqual("legacy reply", events[0]["text"])
        self.assertEqual("msg-legacy", events[0]["parent_message_id"])


class TextBackendTransportTests(unittest.TestCase):
    def test_prepare_text_transport_uses_partial_query_for_new_conversation(self) -> None:
        session = mock.Mock()
        response = mock.Mock()
        response.ok = True
        response.json.return_value = {"conduit_token": "conduit-token"}
        session.post.return_value = response

        with mock.patch(
            "services.text_backend._chat_requirements",
            return_value=("chat-token", {"required": False}),
        ), mock.patch("services.text_backend._generate_proof_token", return_value="proof-token"):
            result = _prepare_text_transport(session, "token", "device-id", "hello", "auto")

        self.assertEqual(
            {
                "chat_token": "chat-token",
                "proof_token": "",
                "conduit_token": "conduit-token",
            },
            result,
        )
        self.assertEqual(1, session.post.call_count)
        self.assertEqual(
            "https://chatgpt.com/backend-api/f/conversation/prepare",
            session.post.call_args.args[0],
        )
        headers = session.post.call_args.kwargs["headers"]
        body = session.post.call_args.kwargs["json"]
        self.assertEqual(NO_CONDUIT_TOKEN, headers["x-conduit-token"])
        self.assertEqual(CLIENT_CREATED_ROOT, body["parent_message_id"])
        self.assertNotIn("conversation_id", body)
        self.assertEqual(["hello"], body["partial_query"]["content"]["parts"])

    def test_prepare_text_transport_reuses_conversation_without_partial_query(self) -> None:
        session = mock.Mock()
        response = mock.Mock()
        response.ok = True
        response.json.return_value = {"conduit_token": "resume-conduit"}
        session.post.return_value = response

        with mock.patch(
            "services.text_backend._chat_requirements",
            return_value=("chat-token", {"required": True, "seed": "seed", "difficulty": "0fffff"}),
        ), mock.patch("services.text_backend._generate_proof_token", return_value="proof-token"):
            result = _prepare_text_transport(
                session,
                "token",
                "device-id",
                "hello again",
                "auto",
                conversation_id="conv-1",
                parent_message_id="msg-1",
                resume_conduit_token="resume-token",
            )

        self.assertEqual("chat-token", result["chat_token"])
        self.assertEqual("proof-token", result["proof_token"])
        self.assertEqual("resume-conduit", result["conduit_token"])
        headers = session.post.call_args.kwargs["headers"]
        body = session.post.call_args.kwargs["json"]
        self.assertEqual("resume-token", headers["x-conduit-token"])
        self.assertEqual("conv-1", body["conversation_id"])
        self.assertEqual("msg-1", body["parent_message_id"])
        self.assertNotIn("partial_query", body)

    def test_send_text_conversation_targets_f_conversation(self) -> None:
        session = mock.Mock()
        response = mock.Mock()
        response.ok = True
        session.post.return_value = response

        returned = _send_text_conversation(
            session,
            "token",
            "device-id",
            "chat-token",
            "proof-token",
            CLIENT_CREATED_ROOT,
            "hello",
            "auto",
            conduit_token="conduit-token",
        )

        self.assertIs(response, returned)
        self.assertEqual("https://chatgpt.com/backend-api/f/conversation", session.post.call_args.args[0])
        headers = session.post.call_args.kwargs["headers"]
        body = session.post.call_args.kwargs["json"]
        self.assertEqual("chat-token", headers["openai-sentinel-chat-requirements-token"])
        self.assertEqual("proof-token", headers["openai-sentinel-proof-token"])
        self.assertEqual("conduit-token", headers["x-conduit-token"])
        self.assertEqual([], body["system_hints"])
        self.assertNotIn("conversation_id", body)


if __name__ == "__main__":
    unittest.main()
