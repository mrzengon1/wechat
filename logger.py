"""统一日志：GUI 与 CLI 共用。"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, List

_handlers: List[Callable[[str], None]] = []


def subscribe(handler: Callable[[str], None]) -> None:
    if handler not in _handlers:
        _handlers.append(handler)


def unsubscribe(handler: Callable[[str], None]) -> None:
    if handler in _handlers:
        _handlers.remove(handler)


def log(message: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {message}"
    for h in list(_handlers):
        try:
            h(line)
        except Exception:
            pass
