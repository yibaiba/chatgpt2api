from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable

from services.register_service import register_service

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SERVER_LOG_PATH = BASE_DIR / "logs" / "uvicorn.log"

LOG_SOURCE_ALL = "all"
LOG_SOURCE_SERVER = "server"
LOG_SOURCE_REGISTER = "register"
LOG_SOURCES = {LOG_SOURCE_ALL, LOG_SOURCE_SERVER, LOG_SOURCE_REGISTER}

LOG_LEVEL_ALL = "all"
LOG_LEVEL_INFO = "info"
LOG_LEVEL_WARNING = "warning"
LOG_LEVEL_ERROR = "error"
LOG_LEVEL_SUCCESS = "success"
LOG_LEVELS = {LOG_LEVEL_ALL, LOG_LEVEL_INFO, LOG_LEVEL_WARNING, LOG_LEVEL_ERROR, LOG_LEVEL_SUCCESS}

_TIME_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?)")


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_level(level: object) -> str:
    text = _clean_text(level).lower()
    if text in {"danger", "failed"}:
        return LOG_LEVEL_ERROR
    if text == "warn":
        return LOG_LEVEL_WARNING
    if text in LOG_LEVELS:
        return text
    return LOG_LEVEL_INFO


def _infer_level_from_line(line: str) -> str:
    text = line.lower()
    if "traceback" in text or "exception" in text or " failed" in text or " error" in text:
        return LOG_LEVEL_ERROR
    if "warning" in text or " retry " in text or " remove " in text:
        return LOG_LEVEL_WARNING
    if " success" in text or " ok " in text:
        return LOG_LEVEL_SUCCESS
    return LOG_LEVEL_INFO


def _extract_time(line: str) -> str | None:
    matched = _TIME_PREFIX_RE.match(line)
    return matched.group(1) if matched else None


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


@dataclass(slots=True)
class LogService:
    server_log_path: Path
    register_state_getter: Callable[[], dict[str, Any]]

    def list(self, *, source: str = LOG_SOURCE_ALL, query: str = "", level: str = LOG_LEVEL_ALL, limit: int = 200) -> list[dict[str, Any]]:
        normalized_source = _clean_text(source).lower() or LOG_SOURCE_ALL
        if normalized_source not in LOG_SOURCES:
            normalized_source = LOG_SOURCE_ALL
        raw_level = _clean_text(level).lower()
        normalized_level = LOG_LEVEL_ALL if raw_level in {"", LOG_LEVEL_ALL} else _normalize_level(raw_level)
        normalized_query = _clean_text(query).lower()
        safe_limit = max(1, min(500, int(limit or 200)))

        items: list[dict[str, Any]] = []
        if normalized_source in {LOG_SOURCE_ALL, LOG_SOURCE_SERVER}:
            items.extend(self._read_server_logs(query=normalized_query, level=normalized_level, limit=safe_limit))
        if normalized_source in {LOG_SOURCE_ALL, LOG_SOURCE_REGISTER}:
            items.extend(self._read_register_logs(query=normalized_query, level=normalized_level, limit=safe_limit))

        if normalized_source == LOG_SOURCE_ALL:
            items.sort(
                key=lambda item: (
                    1 if _clean_text(item.get("time")) else 0,
                    _clean_text(item.get("time")),
                    _clean_text(item.get("id")),
                ),
                reverse=True,
            )
        return items[:safe_limit]

    def _read_server_logs(self, *, query: str, level: str, limit: int) -> list[dict[str, Any]]:
        if not self.server_log_path.exists():
            return []
        try:
            lines = self.server_log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return []

        items: list[dict[str, Any]] = []
        start_index = max(0, len(lines) - limit * 5)
        for line_number, line in reversed(list(enumerate(lines[start_index:], start=start_index + 1))):
            message = line.rstrip()
            if not message:
                continue
            inferred_level = _infer_level_from_line(message)
            if level != LOG_LEVEL_ALL and inferred_level != level:
                continue
            if query and query not in message.lower():
                continue
            items.append(
                {
                    "id": f"server-{line_number}",
                    "source": LOG_SOURCE_SERVER,
                    "level": inferred_level,
                    "time": _extract_time(message),
                    "summary": message,
                    "message": message,
                    "detail": {
                        "line_number": line_number,
                        "path": _display_path(self.server_log_path),
                    },
                }
            )
            if len(items) >= limit:
                break
        return items

    def _read_register_logs(self, *, query: str, level: str, limit: int) -> list[dict[str, Any]]:
        try:
            state = self.register_state_getter()
        except Exception:
            return []
        raw_items = state.get("logs") if isinstance(state, dict) else []
        if not isinstance(raw_items, list):
            return []

        items: list[dict[str, Any]] = []
        for index, entry in enumerate(reversed(raw_items), start=1):
            if not isinstance(entry, dict):
                continue
            message = _clean_text(entry.get("text"))
            if not message:
                continue
            normalized_level = _normalize_level(entry.get("level"))
            if level != LOG_LEVEL_ALL and normalized_level != level:
                continue
            if query and query not in message.lower():
                continue
            items.append(
                {
                    "id": f"register-{index}-{_clean_text(entry.get('time'))}",
                    "source": LOG_SOURCE_REGISTER,
                    "level": normalized_level,
                    "time": _clean_text(entry.get("time")) or None,
                    "summary": message,
                    "message": message,
                    "detail": {
                        "path": "data/register.json",
                    },
                }
            )
            if len(items) >= limit:
                break
        return items


log_service = LogService(DEFAULT_SERVER_LOG_PATH, register_service.get)
