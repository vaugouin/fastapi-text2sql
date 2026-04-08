"""Hot-reload watcher for files in the ./data/ folder.

Modules register a filename and a callback. The callback is invoked once
synchronously at registration time (so the value is available immediately)
and then again every time the file's mtime changes on disk. A single daemon
background thread polls all registered files every WATCH_INTERVAL seconds.

Usage:
    import data_watcher

    def _on_change(content: str) -> None:
        global my_template
        my_template = content

    data_watcher.register("text_to_sql.md", _on_change)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable

import logs

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
WATCH_INTERVAL = 5  # seconds

OnChange = Callable[[str], None]

_registry: dict[str, OnChange] = {}
_mtimes: dict[str, float] = {}
_lock = threading.Lock()
_thread: threading.Thread | None = None


def _full_path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


def _read(filename: str) -> str:
    with open(_full_path(filename), "r", encoding="utf-8") as f:
        return f.read()


def register(filename: str, on_change: OnChange) -> None:
    """Register a data/ file for hot-reload.

    The callback is invoked synchronously now with the current file content,
    then again whenever the file's mtime changes on disk.
    """
    path = _full_path(filename)
    content = _read(filename)
    mtime = os.path.getmtime(path)

    with _lock:
        _registry[filename] = on_change
        _mtimes[filename] = mtime

    # Initial synchronous load so the caller can rely on the value immediately.
    on_change(content)
    print(f"[data-watcher] Registered '{filename}' for hot-reload")

    _ensure_thread_started()


def _scan_once() -> None:
    with _lock:
        items = list(_registry.items())

    for filename, callback in items:
        path = _full_path(filename)
        try:
            mtime = os.path.getmtime(path)
        except OSError as e:
            print(f"[data-watcher] Cannot stat {filename}: {e}")
            continue

        with _lock:
            cached = _mtimes.get(filename)
        if cached is not None and cached == mtime:
            continue

        try:
            content = _read(filename)
        except Exception as e:
            print(f"[data-watcher] Failed to read {filename}: {e}")
            continue

        with _lock:
            _mtimes[filename] = mtime

        try:
            callback(content)
            logs.log_hot_reload(filename)
            print(f"[data-watcher] Reloaded '{filename}'")
        except Exception as e:
            print(f"[data-watcher] Callback for {filename} raised: {e}")


def _loop() -> None:
    while True:
        time.sleep(WATCH_INTERVAL)
        try:
            _scan_once()
        except Exception as e:
            print(f"[data-watcher] Scan error: {e}")


def _ensure_thread_started() -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, name="data-folder-watcher", daemon=True)
        _thread.start()
    print(f"[data-watcher] Started watching '{DATA_DIR}' every {WATCH_INTERVAL}s")
