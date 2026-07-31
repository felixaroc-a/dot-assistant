"""Heurísticas de generación de imágenes (conteo, prompt, resolución)."""
from __future__ import annotations

import re

from app.settings import settings

IMAGE_GENERATION_UNAVAILABLE_MESSAGE = (
    "La generación de imágenes no está disponible ahora."
)

_PROMPT_MIN_LEN = 1
_PROMPT_MAX_LEN = 4000

_NUMBER_PATTERNS = (
    re.compile(r"\b(\d{1,2})\s+(?:im[aá]genes?|images?|fotos?|photos?|variantes?|variants?)\b", re.I),
    re.compile(r"\b(?:genera(?:r)?|create|generate|make|draw)\s+(\d{1,2})\b", re.I),
)

_PLURAL_HINT = re.compile(
    r"\b(?:im[aá]genes?|images?|fotos?|photos?|variantes?|variants?|versiones?|versions?)\b",
    re.I,
)

_INTENT_PREFIX = re.compile(
    r"^\s*(?:"
    r"genera(?:r)?(?:\s+una)?\s+im[aá]gen(?:\s+de)?|"
    r"dibuja(?:\s+una)?(?:\s+im[aá]gen(?:\s+de)?)?|"
    r"crea(?:r)?(?:\s+una)?\s+im[aá]gen(?:\s+de)?|"
    r"hazme(?:\s+una)?\s+foto(?:\s+de)?|"
    r"ilustra(?:\s+una)?(?:\s+im[aá]gen(?:\s+de)?)?|"
    r"generate(?:\s+an)?\s+image(?:\s+of)?|"
    r"draw(?:\s+a)?\s+picture(?:\s+of)?|"
    r"create(?:\s+an)?\s+image(?:\s+of)?|"
    r"make(?:\s+a)?\s+photo(?:\s+of)?"
    r")\s*[:,-]?\s*",
    re.I,
)


def validate_prompt(prompt: str) -> str:
    cleaned = (prompt or "").strip()
    if len(cleaned) < _PROMPT_MIN_LEN:
        raise ValueError("invalid_prompt")
    if len(cleaned) > _PROMPT_MAX_LEN:
        raise ValueError("invalid_prompt")
    return cleaned


def strip_intent_prefix(prompt: str) -> str:
    text = (prompt or "").strip()
    previous = None
    while text and text != previous:
        previous = text
        text = _INTENT_PREFIX.sub("", text, count=1).strip()
    return text or (prompt or "").strip()


def parse_image_count(prompt: str, explicit_count: int | None = None) -> int:
    max_images = max(1, int(settings.image_gen_max_images_per_request))
    if explicit_count is not None:
        return max(1, min(int(explicit_count), max_images))

    text = (prompt or "").strip()
    for pattern in _NUMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            return max(1, min(int(match.group(1)), max_images))

    if _PLURAL_HINT.search(text):
        return min(2, max_images)

    return 1


def resolve_resolution(resolution: str | None = None) -> tuple[int, int, str]:
    if settings.image_gen_enable_1080p:
        target = (resolution or "1920x1080").strip().lower()
        if target in {"1920x1080", "1080p", "1080x1920"}:
            return 1920, 1080, "16:9"

    target = (resolution or settings.image_gen_default_resolution or "1024x1024").strip().lower()
    if target in {"1024x1024", "1:1"}:
        return 1024, 1024, "1:1"
    return 1024, 1024, "1:1"
