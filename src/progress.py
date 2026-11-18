from __future__ import annotations

import datetime as dt
import os
import threading
import time
from pathlib import Path


_log_path: Path | None = None
_log_lock = threading.Lock()


def enabled() -> bool:
    return os.getenv("CODEDEMO_PROGRESS", "1") != "0"


def log(message: str) -> None:
    now = dt.datetime.now().astimezone().isoformat(timespec="milliseconds")
    line = f"[{now}] {message}"
    if enabled():
        print(line, flush=True)
    if _log_path is not None:
        with _log_lock:
            _log_path.parent.mkdir(parents=True, exist_ok=True)
            with _log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())


def set_log_path(path: Path | None) -> None:
    global _log_path
    _log_path = path


def timer() -> float:
    return time.perf_counter()


def elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.1f}s"
