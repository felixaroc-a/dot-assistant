"""Tests de heurísticas de image_generation_service."""
from __future__ import annotations

import pytest

from app.services import image_generation_service
from app.settings import settings


@pytest.fixture(autouse=True)
def _reset_image_gen_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "image_gen_max_images_per_request", 4, raising=False)
    monkeypatch.setattr(settings, "image_gen_default_resolution", "1024x1024", raising=False)
    monkeypatch.setattr(settings, "image_gen_enable_1080p", False, raising=False)


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Un gato astronauta", 1),
        ("3 imágenes de gatos en la luna", 3),
        ("generate 2 images of a sunset", 2),
        ("varias imágenes de flores", 2),
        ("generate images of mountains", 2),
    ],
)
def test_parse_image_count(prompt: str, expected: int) -> None:
    assert image_generation_service.parse_image_count(prompt) == expected


def test_parse_image_count_respects_explicit_and_max(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "image_gen_max_images_per_request", 2, raising=False)
    assert image_generation_service.parse_image_count("anything", explicit_count=5) == 2
    assert image_generation_service.parse_image_count("anything", explicit_count=0) == 1


def test_strip_intent_prefix_es_en() -> None:
    assert image_generation_service.strip_intent_prefix("genera una imagen de un perro") == "un perro"
    assert image_generation_service.strip_intent_prefix("draw a picture of a castle") == "a castle"


def test_validate_prompt_rejects_empty_or_too_long() -> None:
    with pytest.raises(ValueError, match="invalid_prompt"):
        image_generation_service.validate_prompt("   ")
    with pytest.raises(ValueError, match="invalid_prompt"):
        image_generation_service.validate_prompt("x" * 4001)


def test_resolve_resolution_defaults_to_1024() -> None:
    width, height, aspect = image_generation_service.resolve_resolution()
    assert (width, height, aspect) == (1024, 1024, "1:1")
