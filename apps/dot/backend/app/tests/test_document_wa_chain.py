"""Encadenamiento leer documento → resumir → notify_whatsapp_owner."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.agent.runtime import run_agent
from app.application.agent.tools import build_default_registry


@dataclass
class _FakeAI:
    content: str
    usage: dict | None = None
    model: str = "fake"


def test_force_wa_notify_after_read_document(monkeypatch):
    """Si leyó PDF pero no envió WA, runtime fuerza notify_whatsapp_owner."""
    notified: dict = {}

    def fake_read(uid, arguments):
        from app.application.agent.ports import ToolResult

        return ToolResult(
            ok=True,
            output="Contenido de informe.pdf:\n\nTexto del documento sobre ventas Q1.",
        )

    from types import SimpleNamespace

    async def fake_wa_send(phone: str, message: str):
        notified["message"] = message
        return True, None

    monkeypatch.setattr(
        "app.application.agent.tools.read_document.read_document_handler",
        fake_read,
    )
    monkeypatch.setattr(
        "app.services.whatsapp_link.get_channel_state",
        lambda uid: SimpleNamespace(linked=True, phone_number="+584121234567"),
    )
    monkeypatch.setattr(
        "app.services.whatsapp_client.send_whatsapp_message",
        fake_wa_send,
    )

    def fake_file_search(uid, arguments):
        from app.application.agent.ports import ToolResult

        return ToolResult(ok=True, output="informe.pdf en Escritorio")

    monkeypatch.setattr(
        "app.application.agent.tools.file_search.file_search_handler",
        fake_file_search,
    )

    reg = build_default_registry(include_web_search=False)
    turns = [
        _FakeAI(
            content='{"tool_calls":[{"name":"read_document","arguments":{"path":"~/Desktop/informe.pdf"}}]}'
        ),
        _FakeAI(
            content=(
                "Resumen en 5 bullets:\n"
                "• Ventas Q1 subieron\n"
                "• Margen estable\n"
                "• Costes controlados\n"
                "• Proyección positiva\n"
                "• Acción: revisar inventario\n"
                "Fin del resumen."
            )
        ),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        if idx["i"] < len(turns):
            out = turns[idx["i"]]
            idx["i"] += 1
            return out
        return _FakeAI(content="Listo, enviado.")

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="Lee el PDF del Escritorio, resúmelo en 5 bullets y mándamelo por WhatsApp",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=8,
        local_tools=False,
    )

    wa_tools = [t for t in result.tool_trace if t.get("tool") == "notify_whatsapp_owner"]
    assert wa_tools, f"Esperado notify_whatsapp_owner forzado. Trace: {result.tool_trace}"
    assert wa_tools[-1].get("ok") is True
    assert notified.get("message")
    assert "WhatsApp" in result.final_text or "envié" in result.final_text.lower()


def test_force_desktop_pdf_search_at_start(monkeypatch):
    """PDF del Escritorio sin ruta → file_search forzado al inicio."""
    searches: list[dict] = []

    def fake_search(uid, arguments):
        from app.application.agent.ports import ToolResult

        searches.append(dict(arguments))
        return ToolResult(
            ok=True,
            output="Encontrado: C:\\Users\\X\\Desktop\\informe.pdf",
        )

    monkeypatch.setattr(
        "app.application.agent.tools.file_search.file_search_handler",
        fake_search,
    )

    reg = build_default_registry(include_web_search=False)
    turns = [
        _FakeAI(content="Necesito la ruta exacta del PDF."),
    ]

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        return turns[0]

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="Lee el PDF del Escritorio y dime de qué trata",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=2,
        local_tools=False,
    )

    assert searches, "Esperado file_search forzado"
    assert searches[0].get("searchRoot") == "desktop"
    assert any(t.get("tool") == "file_search" and t.get("ok") for t in result.tool_trace)


def test_force_wa_document_after_generate(monkeypatch, tmp_path):
    """Si generó DOCX pero no envió WA, runtime fuerza send_whatsapp_document."""
    doc_path = tmp_path / "Informe - 24-07-2026.docx"
    doc_path.write_bytes(b"fake-docx")

    sent: dict = {}

    def fake_generate(uid, arguments):
        from app.application.agent.ports import ToolResult
        from app.services.document_output_service import build_document_confirmation

        return ToolResult(
            ok=True,
            output=build_document_confirmation(
                kind="docx",
                filename=doc_path.name,
                path=str(doc_path),
            ),
        )

    async def fake_wa_media(to: str, path: str, *, media_type: str, caption: str = ""):
        sent["to"] = to
        sent["path"] = path
        sent["media_type"] = media_type
        return True, None

    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.application.agent.tools.generate_document.generate_document_handler",
        fake_generate,
    )
    monkeypatch.setattr(
        "app.services.whatsapp_link.get_channel_state",
        lambda uid: SimpleNamespace(linked=True, phone_number="+584121234567"),
    )
    monkeypatch.setattr(
        "app.services.whatsapp_client.send_whatsapp_media",
        fake_wa_media,
    )

    reg = build_default_registry(include_web_search=False)
    turns = [
        _FakeAI(
            content=(
                '{"tool_calls":[{"name":"generate_document","arguments":'
                '{"title":"Informe Ventas","content":"# Resumen\\n- Punto 1"}}]}'
            )
        ),
        _FakeAI(
            content=(
                "Listo, generé el informe de ventas en tu Escritorio.\n"
                f"Ruta: {doc_path}"
            )
        ),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        if idx["i"] < len(turns):
            out = turns[idx["i"]]
            idx["i"] += 1
            return out
        return _FakeAI(content="Enviado.")

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="Genera un informe de ventas y mándamelo por WhatsApp",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=8,
        local_tools=False,
    )

    wa_tools = [t for t in result.tool_trace if t.get("tool") == "send_whatsapp_document"]
    assert wa_tools, f"Esperado send_whatsapp_document forzado. Trace: {result.tool_trace}"
    assert wa_tools[-1].get("ok") is True
    assert sent.get("path") == str(doc_path.resolve())
    assert sent.get("media_type") == "document"
    assert "WhatsApp" in result.final_text or "envié" in result.final_text.lower()
