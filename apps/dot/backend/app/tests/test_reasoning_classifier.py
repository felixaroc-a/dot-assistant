"""Tests del clasificador Auto de modos de razonamiento."""

from app.application.agent.reasoning import (
    classify_auto,
    is_trivial_message,
    resolve_effective_level,
)


def test_trivial_greeting_is_off_even_if_high_pref() -> None:
    assert is_trivial_message("hola")
    effective = resolve_effective_level(True, "high", "hola", "pc")
    assert effective == "off"


def test_auto_pipeline_text_is_high() -> None:
    text = "crea un pipeline que busque trabajo y mande resumen por whatsapp"
    assert classify_auto(text, "pipeline") == "high"


def test_auto_whatsapp_action_is_medium() -> None:
    text = "envía un whatsapp a 04121234567 con el resumen"
    assert classify_auto(text, "pc") == "medium"


def test_auto_simple_chat_is_low() -> None:
    text = "explícame qué es la fotosíntesis en pocas palabras"
    assert classify_auto(text, "pc") == "low"


def test_disabled_reasoning_is_off() -> None:
    text = "envía whatsapp a Juan con la factura"
    assert resolve_effective_level(False, "high", text, "pc") == "off"
