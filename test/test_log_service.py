from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.log_service import (
    LOG_LEVEL_ERROR,
    LOG_LEVEL_INFO,
    LOG_LEVEL_SUCCESS,
    LOG_SOURCE_ALL,
    LOG_SOURCE_REGISTER,
    LOG_SOURCE_SERVER,
    LogService,
)


class LogServiceTests(unittest.TestCase):
    def test_lists_recent_server_lines_with_inferred_levels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "uvicorn.log"
            log_path.write_text(
                "\n".join(
                    [
                        "first line",
                        "[account-refresh] ok token:abc quota=25",
                        "[account-refresh] fail token:def /backend-api/me failed: HTTP 401",
                    ]
                ),
                encoding="utf-8",
            )
            service = LogService(log_path, lambda: {"logs": []})

            items = service.list(source=LOG_SOURCE_SERVER, limit=10)

            self.assertEqual(3, len(items))
            self.assertEqual(LOG_LEVEL_ERROR, items[0]["level"])
            self.assertEqual(LOG_LEVEL_SUCCESS, items[1]["level"])
            self.assertEqual(LOG_LEVEL_INFO, items[2]["level"])

    def test_filters_register_logs_by_query_and_level(self) -> None:
        service = LogService(
            Path("/tmp/missing.log"),
            lambda: {
                "logs": [
                    {"time": "2026-04-28T12:00:00+08:00", "text": "runner started", "level": "info"},
                    {"time": "2026-04-28T12:00:10+08:00", "text": "signup failed: timeout", "level": "danger"},
                ]
            },
        )

        items = service.list(source=LOG_SOURCE_REGISTER, query="timeout", level="error", limit=10)

        self.assertEqual(1, len(items))
        self.assertEqual("signup failed: timeout", items[0]["message"])
        self.assertEqual(LOG_LEVEL_ERROR, items[0]["level"])

    def test_combines_sources_for_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "uvicorn.log"
            log_path.write_text("2026-04-28 12:00:00 startup ok\n", encoding="utf-8")
            service = LogService(
                log_path,
                lambda: {
                    "logs": [
                        {"time": "2026-04-28T12:00:10+08:00", "text": "runner started", "level": "info"},
                    ]
                },
            )

            items = service.list(source=LOG_SOURCE_ALL, limit=10)

            self.assertEqual(2, len(items))
            self.assertEqual(LOG_SOURCE_REGISTER, items[0]["source"])
            self.assertEqual(LOG_SOURCE_SERVER, items[1]["source"])


if __name__ == "__main__":
    unittest.main()
