from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json_file(path: Path, *, default: Any) -> Any:
    if not path.exists() or path.is_dir():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_text_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, value: object) -> None:
    write_text_atomically(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
