"""Contexto de uid para tools de browser (bridge CDP)."""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_browser_tool_uid: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "browser_tool_uid",
    default=None,
)


def get_browser_tool_uid() -> str | None:
    """Uid del usuario cuya tool se está ejecutando (si hay scope activo)."""
    return _browser_tool_uid.get()


@contextmanager
def browser_tool_uid_scope(uid: str) -> Iterator[None]:
    """Propaga uid a _bridge_browser durante la ejecución de una tool."""
    token = _browser_tool_uid.set(uid)
    try:
        yield
    finally:
        _browser_tool_uid.reset(token)
