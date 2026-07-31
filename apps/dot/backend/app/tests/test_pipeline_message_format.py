"""Tests: mensajes de pipeline/WhatsApp sin JSON crudo."""
from __future__ import annotations

from app.services.pipeline_message_format import (
    build_whatsapp_user_message,
    humanize_step_output,
)


def test_humanize_create_document_json() -> None:
    raw = (
        '{"action":"create_document","type":"docx","title":"Carta_Resumen",'
        '"content":"Estimado, resumen del escritorio."}'
    )
    out = humanize_step_output(raw)
    assert "{" not in out
    assert "Carta_Resumen" in out
    assert "Estimado" in out


def test_humanize_read_file_missing() -> None:
    raw = (
        '{"action":"read_file","path":"~/Desktop/archivo.txt",'
        '"content":"No se encontró el archivo especificado en el Escritorio."}'
    )
    out = humanize_step_output(raw)
    assert "action" not in out
    assert "No se pudo leer" in out or "No se encontró" in out


def test_whatsapp_body_is_human() -> None:
    prior = [
        '{"action":"create_document","type":"txt","title":"automatizacion","content":"Hecho."}',
        '{"action":"read_file","path":"~/Desktop/x.txt","content":"No se encontró el archivo."}',
    ]
    msg = build_whatsapp_user_message(
        title="Enviar por WhatsApp: resumen de escritorio",
        prior_outputs=prior,
    )
    assert '"action"' not in msg
    assert "{" not in msg
    assert "resumen de escritorio" in msg.lower()
    assert "Resumen:" in msg
    assert "automatizacion" in msg.lower() or "Documento" in msg
