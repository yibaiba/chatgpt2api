from __future__ import annotations

import unittest

from services.utils import extract_chat_prompt, extract_prompt_from_message_content, extract_response_prompt


class TextPromptNormalizationTests(unittest.TestCase):
    def test_extract_prompt_from_message_content_accepts_output_text(self) -> None:
        self.assertEqual(
            extract_prompt_from_message_content(
                [
                    {"type": "output_text", "text": "history reply"},
                    {"type": "input_text", "text": "new image prompt"},
                ]
            ),
            "history reply\nnew image prompt",
        )

    def test_extract_response_prompt_strips_assistant_history_prefix(self) -> None:
        self.assertEqual(
            extract_response_prompt(
                [
                    {"role": "assistant", "content": [{"type": "output_text", "text": "history reply"}]},
                    {
                        "role": "user",
                        "content": [
                            {"type": "output_text", "text": "history reply"},
                            {"type": "input_text", "text": "new image prompt"},
                        ],
                    },
                ]
            ),
            "new image prompt",
        )

    def test_extract_response_prompt_strips_roleless_output_history_prefix(self) -> None:
        self.assertEqual(
            extract_response_prompt(
                [
                    {"type": "output_text", "text": "history reply"},
                    {"type": "input_text", "text": "new image prompt"},
                ]
            ),
            "new image prompt",
        )

    def test_extract_chat_prompt_strips_assistant_history_prefix(self) -> None:
        self.assertEqual(
            extract_chat_prompt(
                {
                    "messages": [
                        {"role": "assistant", "content": [{"type": "output_text", "text": "history reply"}]},
                        {
                            "role": "user",
                            "content": [
                                {"type": "output_text", "text": "history reply"},
                                {"type": "text", "text": "new image prompt"},
                            ],
                        },
                    ]
                }
            ),
            "new image prompt",
        )


if __name__ == "__main__":
    unittest.main()
