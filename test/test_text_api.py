from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fastapi.testclient import TestClient

from services import api as api_module
from services import chatgpt_service as chatgpt_service_module
from services.text_thread_service import TextThreadService


class _FakeThread:
    def join(self, timeout: float | None = None) -> None:
        return None


class _FakeTextBackend:
    calls: list[dict[str, object]] = []
    stream_calls: list[dict[str, object]] = []
    complete_text = "backend reply"
    complete_conversation_id = "conv-initial"
    complete_parent_message_id = "msg-initial"
    stream_texts = ["hello", "hello world"]
    invalid_complete_tokens: set[str] = set()
    invalid_stream_tokens: set[str] = set()

    def __init__(self, access_token: str):
        self.access_token = access_token

    def complete(self, prompt: str, model: str = "auto", **kwargs: object) -> dict[str, object]:
        type(self).calls.append(
            {
                "access_token": self.access_token,
                "prompt": prompt,
                "model": model,
                "conversation_id": kwargs.get("conversation_id", ""),
                "parent_message_id": kwargs.get("parent_message_id", ""),
                "allow_conversation_fallback": kwargs.get("allow_conversation_fallback", True),
            }
        )
        if self.access_token in type(self).invalid_complete_tokens:
            raise chatgpt_service_module.TextBackendError("authentication token has been invalidated")
        return {
            "created": 123,
            "model": model,
            "text": type(self).complete_text,
            "conversation_id": kwargs.get("conversation_id") or type(self).complete_conversation_id,
            "parent_message_id": type(self).complete_parent_message_id,
        }

    def stream(self, prompt: str, model: str = "auto", **kwargs: object):
        type(self).stream_calls.append(
            {
                "access_token": self.access_token,
                "prompt": prompt,
                "model": model,
                "conversation_id": kwargs.get("conversation_id", ""),
                "parent_message_id": kwargs.get("parent_message_id", ""),
            }
        )
        if self.access_token in type(self).invalid_stream_tokens:
            raise chatgpt_service_module.TextBackendError("authentication token has been invalidated")

        def generate():
            for text in type(self).stream_texts:
                yield {
                    "created": 123,
                    "model": model,
                    "text": text,
                    "conversation_id": kwargs.get("conversation_id") or type(self).complete_conversation_id,
                    "parent_message_id": type(self).complete_parent_message_id,
                }

        return generate()


class _FakeConfig:
    def __init__(self, images_dir: Path) -> None:
        self.base_url = ""
        self.images_dir = images_dir
        self.refresh_account_interval_minute = 60
        self.remote_account_sync_interval_minute = 60
        self.session_signing_secret = "test-session-secret"
        self.sensitive_word_filter_enabled = False
        self.sensitive_words: list[str] = []

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


class _FakeAccountService:
    def __init__(self) -> None:
        self.accounts: list[dict[str, object]] = [
            {
                "access_token": "plus-token",
                "type": "Plus",
                "status": "正常",
            }
        ]

    def list_accounts(self) -> list[dict[str, object]]:
        return [dict(item) for item in self.accounts]

    def list_tokens(self) -> list[str]:
        return [str(item.get("access_token") or "") for item in self.accounts if str(item.get("access_token") or "").strip()]

    def update_account(self, access_token: str, updates: dict[str, object]) -> dict[str, object] | None:
        for index, account in enumerate(self.accounts):
            if account.get("access_token") != access_token:
                continue
            next_account = {**account, **updates}
            self.accounts[index] = next_account
            return dict(next_account)
        return None

    def remove_token(self, access_token: str) -> bool:
        before = len(self.accounts)
        self.accounts = [item for item in self.accounts if item.get("access_token") != access_token]
        return len(self.accounts) != before


class TextApiTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeTextBackend.calls = []
        _FakeTextBackend.stream_calls = []
        _FakeTextBackend.complete_text = "backend reply"
        _FakeTextBackend.complete_conversation_id = "conv-initial"
        _FakeTextBackend.complete_parent_message_id = "msg-initial"
        _FakeTextBackend.stream_texts = ["hello", "hello world"]
        _FakeTextBackend.invalid_complete_tokens = set()
        _FakeTextBackend.invalid_stream_tokens = set()
        self.auth_header = {"Authorization": "Bearer test-auth"}
        self.auth_service = _FakeAuthService()
        self.account_service = _FakeAccountService()
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.fake_config = _FakeConfig(Path(self.temp_dir.name) / "images")
        self.thread_service = TextThreadService(Path(self.temp_dir.name) / "text_threads.json")
        self.admin_identity = {"id": "admin", "role": "admin", "name": "管理员"}
        self.patches = [
            mock.patch.object(api_module, "auth_service", self.auth_service),
            mock.patch.object(api_module, "account_service", self.account_service),
            mock.patch.object(api_module, "config", self.fake_config),
            mock.patch.object(api_module, "start_limited_account_watcher", lambda _stop_event: _FakeThread()),
            mock.patch.object(api_module, "start_remote_account_sync_watcher", lambda _stop_event: _FakeThread()),
            mock.patch.object(chatgpt_service_module, "config", self.fake_config),
            mock.patch.object(chatgpt_service_module, "TextBackend", _FakeTextBackend),
            mock.patch.object(chatgpt_service_module, "text_thread_service", self.thread_service),
        ]
        for patcher in self.patches:
            patcher.start()
        self.addCleanup(self._cleanup_patches)
        self.client = TestClient(api_module.create_app())
        self.addCleanup(self.client.close)

    def _cleanup_patches(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_non_image_chat_completions_use_text_backend_without_image_quota(self) -> None:
        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello text path"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["choices"][0]["message"]["content"], "backend reply")
        self.assertEqual(_FakeTextBackend.calls[-1]["prompt"], "hello text path")
        self.assertEqual(_FakeTextBackend.calls[-1]["access_token"], "plus-token")
        self.assertEqual(self.auth_service.reserved, [])
        self.assertEqual(self.auth_service.settled, [])

    def test_non_image_chat_completions_retry_next_token_when_first_token_invalidated(self) -> None:
        self.account_service.accounts = [
            {"access_token": "bad-plus-token", "type": "Plus", "status": "正常"},
            {"access_token": "good-free-token", "type": "Free", "status": "正常"},
        ]
        _FakeTextBackend.invalid_complete_tokens = {"bad-plus-token"}

        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello text path"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [call["access_token"] for call in _FakeTextBackend.calls[-2:]],
            ["bad-plus-token", "good-free-token"],
        )
        self.assertEqual(self.account_service.accounts[0]["status"], "异常")

    def test_non_image_chat_completions_stream_use_text_backend_without_image_quota(self) -> None:
        with self.client.stream(
            "POST",
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello text path"}],
                "stream": True,
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
            lines = [line for line in response.iter_lines() if line]

        payloads: list[dict[str, object]] = []
        done_seen = False
        for line in lines:
            self.assertTrue(line.startswith("data: "))
            payload = line[6:]
            if payload == "[DONE]":
                done_seen = True
                continue
            payloads.append(json.loads(payload))

        self.assertTrue(done_seen)
        self.assertEqual(payloads[0]["choices"][0]["delta"]["role"], "assistant")
        streamed_text = "".join(
            payload["choices"][0]["delta"].get("content", "")
            for payload in payloads
            if isinstance(payload, dict)
        )
        self.assertEqual(streamed_text, "hello world")
        self.assertEqual(payloads[-1]["choices"][0]["finish_reason"], "stop")
        self.assertEqual(_FakeTextBackend.stream_calls[-1]["prompt"], "hello text path")
        self.assertEqual(_FakeTextBackend.stream_calls[-1]["access_token"], "plus-token")
        self.assertEqual(self.auth_service.reserved, [])
        self.assertEqual(self.auth_service.settled, [])

    def test_non_image_chat_completions_stream_retry_next_token_when_first_token_invalidated(self) -> None:
        self.account_service.accounts = [
            {"access_token": "bad-plus-token", "type": "Plus", "status": "正常"},
            {"access_token": "good-free-token", "type": "Free", "status": "正常"},
        ]
        _FakeTextBackend.invalid_stream_tokens = {"bad-plus-token"}

        with self.client.stream(
            "POST",
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello text path"}],
                "stream": True,
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            lines = [line for line in response.iter_lines() if line]

        self.assertTrue(any(line == "data: [DONE]" for line in lines))
        self.assertEqual(
            [call["access_token"] for call in _FakeTextBackend.stream_calls[-2:]],
            ["bad-plus-token", "good-free-token"],
        )
        self.assertEqual(self.account_service.accounts[0]["status"], "异常")

    def test_non_image_chat_completions_strip_repeated_assistant_history_from_backend_text(self) -> None:
        _FakeTextBackend.complete_text = "history replyhistory replynew answer"

        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [
                    {"role": "assistant", "content": "history reply"},
                    {"role": "user", "content": "history replynew question"},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["choices"][0]["message"]["content"], "new answer")

    def test_non_image_chat_completions_stream_skip_replayed_assistant_history(self) -> None:
        _FakeTextBackend.stream_texts = [
            "history reply",
            "history replyhistory reply",
            "history replyhistory replynew answer",
        ]

        with self.client.stream(
            "POST",
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [
                    {"role": "assistant", "content": "history reply"},
                    {"role": "user", "content": "history replynew question"},
                ],
                "stream": True,
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            lines = [line for line in response.iter_lines() if line]

        payloads = [json.loads(line[6:]) for line in lines if line.startswith("data: {")]
        streamed_text = "".join(
            payload["choices"][0]["delta"].get("content", "")
            for payload in payloads
        )
        self.assertEqual(streamed_text, "new answer")

    def test_non_image_responses_use_text_backend_without_image_quota(self) -> None:
        response = self.client.post(
            "/v1/responses",
            headers=self.auth_header,
            json={
                "model": "gpt-5",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hello response path"}],
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["output"][0]["type"], "message")
        self.assertEqual(payload["output"][0]["content"][0]["text"], "backend reply")
        self.assertEqual(_FakeTextBackend.calls[-1]["prompt"], "hello response path")
        self.assertEqual(self.auth_service.reserved, [])
        self.assertEqual(self.auth_service.settled, [])

    def test_non_image_chat_completions_block_sensitive_words_before_backend_call(self) -> None:
        self.fake_config.sensitive_word_filter_enabled = True
        self.fake_config.sensitive_words = ["nsfw"]

        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "make it NSFW please"}],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual("prompt contains blocked word: nsfw", response.json()["detail"]["error"])
        self.assertEqual([], _FakeTextBackend.calls)

    def test_threaded_chat_completions_create_and_reuse_thread(self) -> None:
        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "start thread"}],
                "threaded": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        thread_id = payload["thread_id"]
        self.assertTrue(thread_id)
        stored_thread = self.thread_service.get_thread(self.admin_identity, thread_id)
        self.assertIsNotNone(stored_thread)
        self.assertEqual("conv-initial", stored_thread["conversation_id"])
        self.assertEqual("msg-initial", stored_thread["parent_message_id"])
        self.assertEqual("", _FakeTextBackend.calls[-1]["conversation_id"])
        self.assertEqual("", _FakeTextBackend.calls[-1]["parent_message_id"])

        _FakeTextBackend.complete_text = "thread reply 2"
        _FakeTextBackend.complete_parent_message_id = "msg-second"
        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "continue thread"}],
                "thread_id": thread_id,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(thread_id, payload["thread_id"])
        self.assertEqual("thread reply 2", payload["choices"][0]["message"]["content"])
        self.assertEqual("conv-initial", _FakeTextBackend.calls[-1]["conversation_id"])
        self.assertEqual("msg-initial", _FakeTextBackend.calls[-1]["parent_message_id"])
        stored_thread = self.thread_service.get_thread(self.admin_identity, thread_id)
        self.assertEqual("msg-second", stored_thread["parent_message_id"])

    def test_threaded_chat_completions_reject_unknown_thread(self) -> None:
        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "continue thread"}],
                "thread_id": "missing-thread",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual("thread not found", response.json()["detail"]["error"])
        self.assertEqual([], _FakeTextBackend.calls)

    def test_threaded_chat_completions_block_sensitive_output_and_keep_thread_state_in_sync(self) -> None:
        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "start thread"}],
                "threaded": True,
            },
        )
        thread_id = response.json()["thread_id"]

        self.fake_config.sensitive_word_filter_enabled = True
        self.fake_config.sensitive_words = ["nsfw"]
        _FakeTextBackend.complete_text = "contains NSFW output"
        _FakeTextBackend.complete_parent_message_id = "msg-blocked"

        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "continue thread"}],
                "thread_id": thread_id,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual("response contains blocked word: nsfw", response.json()["detail"]["error"])
        stored_thread = self.thread_service.get_thread(self.admin_identity, thread_id)
        self.assertEqual("msg-blocked", stored_thread["parent_message_id"])
        self.assertEqual("response contains blocked word: nsfw", stored_thread["last_error"])

    def test_threaded_chat_completions_stream_create_and_reuse_thread(self) -> None:
        with self.client.stream(
            "POST",
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello"}],
                "threaded": True,
                "stream": True,
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            lines = [line for line in response.iter_lines() if line]

        payloads = [json.loads(line[6:]) for line in lines if line.startswith("data: {")]
        thread_id = next(str(payload.get("thread_id") or "") for payload in payloads if payload.get("thread_id"))
        self.assertTrue(thread_id)
        streamed_text = "".join(
            payload["choices"][0]["delta"].get("content", "")
            for payload in payloads
            if isinstance(payload, dict)
        )
        self.assertEqual(streamed_text, "hello world")
        self.assertEqual(payloads[-1]["choices"][0]["finish_reason"], "stop")
        stored_thread = self.thread_service.get_thread(self.admin_identity, thread_id)
        self.assertIsNotNone(stored_thread)
        self.assertEqual("conv-initial", stored_thread["conversation_id"])
        self.assertEqual("msg-initial", stored_thread["parent_message_id"])
        self.assertEqual("", _FakeTextBackend.stream_calls[-1]["conversation_id"])
        self.assertEqual("", _FakeTextBackend.stream_calls[-1]["parent_message_id"])

        _FakeTextBackend.stream_texts = ["again", "again reply"]
        _FakeTextBackend.complete_parent_message_id = "msg-stream-second"
        with self.client.stream(
            "POST",
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "continue"}],
                "thread_id": thread_id,
                "stream": True,
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            lines = [line for line in response.iter_lines() if line]

        payloads = [json.loads(line[6:]) for line in lines if line.startswith("data: {")]
        streamed_text = "".join(
            payload["choices"][0]["delta"].get("content", "")
            for payload in payloads
            if isinstance(payload, dict)
        )
        self.assertEqual(streamed_text, "again reply")
        self.assertEqual("conv-initial", _FakeTextBackend.stream_calls[-1]["conversation_id"])
        self.assertEqual("msg-initial", _FakeTextBackend.stream_calls[-1]["parent_message_id"])
        stored_thread = self.thread_service.get_thread(self.admin_identity, thread_id)
        self.assertEqual("msg-stream-second", stored_thread["parent_message_id"])

    def test_threaded_chat_completions_stream_content_filter_truncates_unsafe_suffix(self) -> None:
        self.fake_config.sensitive_word_filter_enabled = True
        self.fake_config.sensitive_words = ["nsfw"]
        _FakeTextBackend.stream_texts = ["safe", "safe ns", "safe nsfw content"]
        _FakeTextBackend.complete_parent_message_id = "msg-stream-blocked"

        with self.client.stream(
            "POST",
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello"}],
                "threaded": True,
                "stream": True,
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            lines = [line for line in response.iter_lines() if line]

        payloads = [json.loads(line[6:]) for line in lines if line.startswith("data: {")]
        streamed_text = "".join(
            payload["choices"][0]["delta"].get("content", "")
            for payload in payloads
            if isinstance(payload, dict)
        )
        self.assertEqual(streamed_text, "safe ")
        self.assertEqual(payloads[-1]["choices"][0]["finish_reason"], "content_filter")
        self.assertEqual(payloads[-1]["moderation_error"], "response contains blocked word: nsfw")
        self.assertNotIn("nsfw", streamed_text.casefold())
        thread_id = next(str(payload.get("thread_id") or "") for payload in payloads if payload.get("thread_id"))
        self.assertTrue(thread_id)
        stored_thread = self.thread_service.get_thread(self.admin_identity, thread_id)
        self.assertEqual("msg-stream-blocked", stored_thread["parent_message_id"])
        self.assertEqual("response contains blocked word: nsfw", stored_thread["last_error"])

    def test_anthropic_messages_use_text_backend_without_image_quota(self) -> None:
        response = self.client.post(
            "/v1/messages",
            headers={
                "x-api-key": "test-auth",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4",
                "system": "be concise",
                "messages": [{"role": "user", "content": "hello anthropic"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["type"], "message")
        self.assertEqual(payload["content"][0]["type"], "text")
        self.assertEqual(payload["content"][0]["text"], "backend reply")
        self.assertEqual(_FakeTextBackend.calls[-1]["prompt"], "be concise\n\nhello anthropic")
        self.assertEqual(self.auth_service.reserved, [])
        self.assertEqual(self.auth_service.settled, [])

    def test_anthropic_messages_block_sensitive_words_before_backend_call(self) -> None:
        self.fake_config.sensitive_word_filter_enabled = True
        self.fake_config.sensitive_words = ["violence"]

        response = self.client.post(
            "/v1/messages",
            headers={
                "x-api-key": "test-auth",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4",
                "messages": [{"role": "user", "content": "please add Violence details"}],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual("prompt contains blocked word: violence", response.json()["detail"]["error"])
        self.assertEqual([], _FakeTextBackend.calls)

    def test_threaded_anthropic_messages_return_thread_id(self) -> None:
        response = self.client.post(
            "/v1/messages",
            headers={
                "x-api-key": "test-auth",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4",
                "messages": [{"role": "user", "content": "hello anthropic"}],
                "threaded": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["thread_id"])
        stored_thread = self.thread_service.get_thread(self.admin_identity, payload["thread_id"])
        self.assertIsNotNone(stored_thread)

    def test_anthropic_messages_stream_use_text_backend_without_image_quota(self) -> None:
        with self.client.stream(
            "POST",
            "/v1/messages",
            headers={
                "x-api-key": "test-auth",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4",
                "messages": [{"role": "user", "content": "hello anthropic"}],
                "stream": True,
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
            lines = [line for line in response.iter_lines() if line]

        events: list[tuple[str, dict[str, object]]] = []
        current_event = ""
        for line in lines:
            if line.startswith("event: "):
                current_event = line[7:]
                continue
            self.assertTrue(line.startswith("data: "))
            events.append((current_event, json.loads(line[6:])))

        self.assertEqual([event for event, _payload in events[:2]], ["message_start", "content_block_start"])
        delta_text = "".join(
            payload["delta"]["text"]
            for event, payload in events
            if event == "content_block_delta"
        )
        self.assertEqual(delta_text, "hello world")
        self.assertEqual(events[-2][0], "message_delta")
        self.assertEqual(events[-1][0], "message_stop")
        self.assertEqual(_FakeTextBackend.stream_calls[-1]["prompt"], "hello anthropic")
        self.assertEqual(self.auth_service.reserved, [])
        self.assertEqual(self.auth_service.settled, [])

    def test_anthropic_messages_convert_tool_markup_to_tool_use_blocks(self) -> None:
        _FakeTextBackend.complete_text = (
            'Need to inspect repo\n'
            '<tool_calls><tool_call><tool_name>read_file</tool_name>'
            '<parameters>{"path":"README.md"}</parameters></tool_call></tool_calls>'
        )

        response = self.client.post(
            "/v1/messages",
            headers={
                "x-api-key": "test-auth",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4",
                "messages": [{"role": "user", "content": "inspect repo"}],
                "tools": [{"name": "read_file", "input_schema": {"type": "object"}}],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["stop_reason"], "tool_use")
        self.assertEqual(payload["content"][0]["type"], "text")
        self.assertEqual(payload["content"][0]["text"], "Need to inspect repo")
        self.assertEqual(payload["content"][1]["type"], "tool_use")
        self.assertEqual(payload["content"][1]["name"], "read_file")
        self.assertEqual(payload["content"][1]["input"], {"path": "README.md"})

    def test_anthropic_message_stream_emits_tool_use_blocks_without_leaking_markup(self) -> None:
        _FakeTextBackend.stream_texts = [
            "Need to inspect repo",
            (
                'Need to inspect repo\n'
                '<tool_calls><tool_call><tool_name>read_file</tool_name>'
                '<parameters>{"path":"README.md"}</parameters></tool_call></tool_calls>'
            ),
        ]

        with self.client.stream(
            "POST",
            "/v1/messages",
            headers={
                "x-api-key": "test-auth",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4",
                "messages": [{"role": "user", "content": "inspect repo"}],
                "tools": [{"name": "read_file", "input_schema": {"type": "object"}}],
                "stream": True,
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            lines = [line for line in response.iter_lines() if line]

        events: list[tuple[str, dict[str, object]]] = []
        current_event = ""
        for line in lines:
            if line.startswith("event: "):
                current_event = line[7:]
                continue
            events.append((current_event, json.loads(line[6:])))

        text_deltas = [
            payload["delta"]["text"]
            for event, payload in events
            if event == "content_block_delta" and payload["delta"]["type"] == "text_delta"
        ]
        tool_deltas = [
            payload["delta"]["partial_json"]
            for event, payload in events
            if event == "content_block_delta" and payload["delta"]["type"] == "input_json_delta"
        ]
        self.assertEqual("".join(text_deltas), "Need to inspect repo")
        self.assertEqual(tool_deltas, ['{"path": "README.md"}'])
        self.assertEqual(events[-2][1]["delta"]["stop_reason"], "tool_use")

    def test_anthropic_messages_stream_skip_replayed_assistant_history(self) -> None:
        _FakeTextBackend.stream_texts = [
            "history reply",
            "history replyhistory reply",
            "history replyhistory replynew answer",
        ]

        with self.client.stream(
            "POST",
            "/v1/messages",
            headers={
                "x-api-key": "test-auth",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4",
                "messages": [
                    {"role": "assistant", "content": "history reply"},
                    {"role": "user", "content": "history replynew question"},
                ],
                "stream": True,
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            lines = [line for line in response.iter_lines() if line]

        events: list[tuple[str, dict[str, object]]] = []
        current_event = ""
        for line in lines:
            if line.startswith("event: "):
                current_event = line[7:]
                continue
            events.append((current_event, json.loads(line[6:])))

        text_deltas = [
            payload["delta"]["text"]
            for event, payload in events
            if event == "content_block_delta" and payload["delta"]["type"] == "text_delta"
        ]
        self.assertEqual("".join(text_deltas), "new answer")

    def test_text_chat_path_strips_assistant_history_prefix_before_backend_call(self) -> None:
        response = self.client.post(
            "/v1/chat/completions",
            headers=self.auth_header,
            json={
                "model": "gpt-4.1",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "history reply"}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "output_text", "text": "history reply"},
                            {"type": "text", "text": "new text prompt"},
                        ],
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_FakeTextBackend.calls[-1]["prompt"], "new text prompt")


if __name__ == "__main__":
    unittest.main()
