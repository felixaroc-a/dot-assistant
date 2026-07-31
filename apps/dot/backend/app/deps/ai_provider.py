"""Dependency injection provider for AIProvider."""
from __future__ import annotations

from fastapi import Request

from app.services.ai_provider import AIProvider


async def get_ai_provider(request: Request) -> AIProvider:
    """Return an AIProvider instance, possibly cached on the app state."""
    provider: AIProvider | None = getattr(request.app.state, "ai_provider", None)
    if provider is None:
        provider = AIProvider()
        request.app.state.ai_provider = provider
    return provider
