"""Tests de integración del agente — GAP 4.

Verifica que las piezas P0-P2 encajan: AgentResult con artifacts,
callbacks de progreso, registro de tools, document_image_service,
streaming SSE con tool_progress, health/scheduler y generate-with-images.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.application.agent import build_default_registry
from app.application.agent.ports import AgentResult, ToolResult, ToolSpec
from app.application.agent.registry import ToolRegistry
from app.application.agent.runtime import run_agent
from app.tests.conftest import seed_cliente


def _get_token(client: TestClient, db_session: Session) -> str:
    """Helper: login y retorna access_token."""
    seed_cliente(db_session)
    resp = client.post(
        "/v1/auth/login",
        json={"cedula": "1234567890", "password": "test123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _extract_sse_payloads(raw: str) -> list[dict]:
    """Extrae payloads JSON de una respuesta SSE."""
    payloads: list[dict] = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            payloads.append(json.loads(line[6:]))
        except json.JSONDecodeError:
            pass
    return payloads


# ─────────────────────────────────────────────────────────
# 1. AgentResult incluye artifacts
# ─────────────────────────────────────────────────────────


@dataclass
class _FakeAIResult:
    content: str = "ok"
    usage: dict | None = None
    model: str = "fake"


def test_agent_result_includes_artifacts() -> None:
    """Verifica que AgentResult incluya los artifacts retornados por tools."""

    reg = ToolRegistry()

    def _artifact_tool(uid: str, arguments: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            output="Documento creado.",
            artifacts=[
                {
                    "type": "document",
                    "path": "C:/Users/test/Desktop/doc.pdf",
                    "mime": "application/pdf",
                    "name": "documento.pdf",
                }
            ],
        )

    reg.register(
        ToolSpec(
            name="generate_doc",
            description="Genera un documento",
            parameters_schema={
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
        ),
        _artifact_tool,
    )

    call_count = {"n": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAIResult:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Primer turno: devolver tool_call para ejecutar generate_doc
            return _FakeAIResult(
                content='{"tool_calls":[{"name":"generate_doc","arguments":{"title":"test"}}]}'
            )
        # Turnos subsecuentes: texto plano (sin tool_calls) para terminar el loop
        return _FakeAIResult(content="Documento creado exitosamente.")

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="crea documento",
        system_prompt="Eres DOT.",
        history="",
        registry=reg,
        model_fn=model_fn,
        max_steps=5,
    )

    assert isinstance(result, AgentResult)
    assert len(result.artifacts) == 1
    assert result.artifacts[0]["type"] == "document"
    assert result.artifacts[0]["mime"] == "application/pdf"


# ─────────────────────────────────────────────────────────
# 2. Callbacks de progreso
# ─────────────────────────────────────────────────────────


def test_agent_callbacks_fire() -> None:
    """Verifica que on_step_complete y on_complete se llamen correctamente."""

    reg = ToolRegistry()

    def _echo_handler(uid: str, arguments: dict) -> ToolResult:
        return ToolResult(ok=True, output=f"echo:{arguments.get('msg', '')}")

    reg.register(
        ToolSpec(
            name="echo",
            description="eco de prueba",
            parameters_schema={
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        ),
        _echo_handler,
    )

    step_calls: list[dict] = []
    complete_calls: list[dict] = []

    def _on_step(step: int, tool_name: str, preview: str, ok: bool) -> None:
        step_calls.append({"step": step, "tool": tool_name, "preview": preview, "ok": ok})

    def _on_complete(final_text: str, artifacts: list[dict]) -> None:
        complete_calls.append({"final_text": final_text, "artifacts": artifacts})

    def model_fn(user_text: str, system_prompt: str) -> _FakeAIResult:
        return _FakeAIResult(
            content='{"tool_calls":[{"name":"echo","arguments":{"msg":"hola"}}]}'
        )

    run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="echo hola",
        system_prompt="Eres DOT.",
        history="",
        registry=reg,
        model_fn=model_fn,
        max_steps=5,
        on_step_complete=_on_step,
        on_complete=_on_complete,
    )

    assert len(step_calls) >= 1, "on_step_complete no fue llamado"
    assert step_calls[0]["tool"] == "echo"
    assert step_calls[0]["ok"] is True
    assert len(complete_calls) == 1, "on_complete no fue llamado"
    assert isinstance(complete_calls[0]["final_text"], str)


# ─────────────────────────────────────────────────────────
# 3. file_search tool registrada
# ─────────────────────────────────────────────────────────


def test_file_search_tool_registered() -> None:
    """Verifica que file_search esté en build_default_registry()."""
    reg = build_default_registry()
    specs = {s.name: s for s in reg.list_specs()}
    assert "file_search" in specs, "file_search no está registrada"
    spec = specs["file_search"]
    assert "Busca archivos" in spec.description
    assert spec.parameters_schema.get("required") == ["query"]


# ─────────────────────────────────────────────────────────
# 4. generate_document tool registrada
# ─────────────────────────────────────────────────────────


def test_generate_document_tool_registered() -> None:
    """Verifica que generate_document esté registrado en el ToolRegistry."""
    reg = build_default_registry()
    specs = {s.name: s for s in reg.list_specs()}
    assert "generate_document" in specs, "generate_document no está registrado"
    spec = specs["generate_document"]
    assert "DOCX" in spec.description or "documento" in spec.description.lower()
    required = spec.parameters_schema.get("required", [])
    assert "title" in required
    assert "content" in required


# ─────────────────────────────────────────────────────────
# 5. generate_spreadsheet (skip si no existe)
# ─────────────────────────────────────────────────────────


def test_generate_spreadsheet_tool_registered() -> None:
    """Verifica si generate_spreadsheet está registrado (opcional)."""
    reg = build_default_registry()
    specs = {s.name: s for s in reg.list_specs()}
    if "generate_spreadsheet" not in specs:
        pytest.skip("generate_spreadsheet tool no existe aún — pendiente de implementar")
    spec = specs["generate_spreadsheet"]
    assert "XLSX" in spec.description or "excel" in spec.description.lower()


# ─────────────────────────────────────────────────────────
# 6. create_docx_with_images no lanza excepciones
# ─────────────────────────────────────────────────────────


def test_document_image_service_creates_docx() -> None:
    """Verifica que create_docx_with_images no lance excepciones con mocks."""
    import tempfile
    from pathlib import Path

    mock_doc_instance = MagicMock()

    def _mock_save(filepath: str) -> None:
        """Simula doc.save() creando un archivo real para que stat() no falle."""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        Path(filepath).write_bytes(b"mock docx content")

    mock_doc_instance.save = _mock_save
    mock_document_class = MagicMock(return_value=mock_doc_instance)

    # Document y dependencias se importan dentro de la función (from docx import Document).
    # Hay que mockear a nivel del paquete docx, no del módulo document_image_service.
    with patch("docx.Document", mock_document_class):
        with patch("app.services.document_image_service._get_dot_work_dir") as mock_work_dir:
            tmp = tempfile.mkdtemp()
            mock_work_dir.return_value = Path(tmp)

            from app.services.document_image_service import create_docx_with_images

            result = create_docx_with_images(
                title="Test Document",
                content="# Título\n\nContenido de prueba.",
                image_paths=None,
                folder=None,
            )

            assert result["ok"] is True
            assert "filename" in result
            assert "path" in result
            assert result["size_bytes"] > 0


# ─────────────────────────────────────────────────────────
# 7. create_xlsx_with_charts (skip si no existe)
# ─────────────────────────────────────────────────────────


def test_excel_chart_service_creates_xlsx() -> None:
    """Verifica que create_xlsx_with_charts no lance excepciones con mocks."""
    try:
        from app.services.document_image_service import create_xlsx_with_charts
    except ImportError:
        pytest.skip("create_xlsx_with_charts no existe — pendiente de implementar")

    import tempfile
    from pathlib import Path

    mock_wb_instance = MagicMock()

    def _mock_save(filepath: str) -> None:
        """Simula wb.save() creando un archivo real para que stat() no falle."""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        Path(filepath).write_bytes(b"mock xlsx content")

    mock_wb_instance.save = _mock_save
    mock_wb = MagicMock(return_value=mock_wb_instance)

    mock_openpyxl_chart = MagicMock()
    mock_openpyxl_chart.BarChart.return_value = MagicMock()
    mock_openpyxl_chart.LineChart.return_value = MagicMock()
    mock_openpyxl_chart.PieChart.return_value = MagicMock()
    mock_openpyxl_chart.label = MagicMock()
    mock_openpyxl_chart.Reference = MagicMock()

    mock_openpyxl_styles = MagicMock()
    mock_openpyxl_styles.Font = MagicMock()
    mock_openpyxl_styles.PatternFill = MagicMock()
    mock_openpyxl_styles.Alignment = MagicMock()
    mock_openpyxl_styles.Border = MagicMock()
    mock_openpyxl_styles.Side = MagicMock()

    mock_openpyxl_utils = MagicMock()
    mock_openpyxl_utils.get_column_letter = MagicMock(return_value="A")

    # openpyxl se importa dentro de create_xlsx_with_charts; mockemos los submódulos
    with patch("openpyxl.Workbook", mock_wb):
        with patch("openpyxl.chart", mock_openpyxl_chart):
            with patch("openpyxl.styles", mock_openpyxl_styles):
                with patch("openpyxl.utils", mock_openpyxl_utils):
                    with patch("app.services.document_image_service._get_dot_work_dir") as mock_work_dir:
                        tmp = tempfile.mkdtemp()
                        mock_work_dir.return_value = Path(tmp)

                        result = create_xlsx_with_charts(
                            title="Test Excel",
                            data_sections=[
                                {
                                    "section_title": "Ventas",
                                    "headers": ["Mes", "Monto"],
                                    "rows": [["Enero", 1000], ["Febrero", 1500]],
                                    "chart_type": "bar",
                                }
                            ],
                        )

                        assert result["ok"] is True
                        assert "filename" in result
                        assert "path" in result
                        assert result["size_bytes"] > 0


# ─────────────────────────────────────────────────────────
# 8. Streaming SSE emite tool_progress y artifacts
# ─────────────────────────────────────────────────────────


def test_agent_streaming_emits_tool_progress(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Verifica que el streaming SSE incluya eventos tool_progress y artifacts."""
    token = _get_token(client, db_session)

    # Mock de run_agent para simular callbacks y artifacts sin ejecutar el loop real
    def _fake_run_agent(**kwargs) -> AgentResult:
        # Disparar callback on_step_complete si existe
        on_step = kwargs.get("on_step_complete")
        if on_step:
            on_step(1, "file_search", "Encontrado: factura.pdf", True)
        # Disparar callback on_complete si existe
        on_complete = kwargs.get("on_complete")
        if on_complete:
            on_complete(
                "Aquí tienes el archivo.",
                [{"type": "document", "path": "C:/test/factura.pdf", "mime": "application/pdf"}],
            )
        return AgentResult(
            final_text="Aquí tienes el resultado final del agente.",
            steps=1,
            artifacts=[{"type": "document", "path": "C:/test/factura.pdf", "mime": "application/pdf"}],
            model_name="deepseek-chat",
        )

    # Mock de route_chat_detailed para el texto final
    def _fake_detailed(
        text: str,
        provider_id: str | None = None,
        system_prompt: str | None = None,
        include_document_action_prompt: bool = False,
        ai_provider=None,
    ):
        class _FakeResult:
            text = "Resultado stream"
            finish_reason = "stop"
            usage = None

        return _FakeResult()

    monkeypatch.setattr(
        "app.application.agent.run_agent",
        _fake_run_agent,
    )
    monkeypatch.setattr(
        "app.services.provider_router.route_chat_detailed",
        _fake_detailed,
    )

    response = client.post(
        "/v1/chat/send/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "busca factura.pdf", "provider": "deepseek"},
    )
    assert response.status_code == 200

    payloads = _extract_sse_payloads(response.text)

    # Verificar tool_progress
    tool_events = [p for p in payloads if p.get("type") == "tool_progress"]
    assert len(tool_events) >= 1, "No se encontraron eventos tool_progress en SSE"
    assert tool_events[0]["tool"] == "file_search"
    assert tool_events[0]["ok"] is True

    # Verificar artifacts
    artifact_events = [p for p in payloads if p.get("type") == "artifacts"]
    assert len(artifact_events) >= 1, "No se encontraron eventos artifacts en SSE"
    assert len(artifact_events[0].get("items", [])) >= 1

    # Verificar done
    done_events = [p for p in payloads if p.get("done") is True]
    assert len(done_events) == 1


# ─────────────────────────────────────────────────────────
# 9. Health scheduler endpoint
# ─────────────────────────────────────────────────────────


def test_health_scheduler_endpoint(client: TestClient) -> None:
    """GET /health/scheduler debe devolver 200 o 503 (según estado)."""
    response = client.get("/health/scheduler")
    # 200 si scheduler está ok; 503 si está degradado (normal en tests sin scheduler)
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data


# ─────────────────────────────────────────────────────────
# 10. generate-with-images endpoint
# ─────────────────────────────────────────────────────────


def test_documents_generate_with_images_endpoint(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """POST /v1/documents/generate-with-images con payload mínimo."""
    token = _get_token(client, db_session)

    import tempfile
    from pathlib import Path

    mock_doc_instance = MagicMock()

    def _mock_save(filepath: str) -> None:
        """Simula doc.save() creando un archivo real para que stat() no falle."""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        Path(filepath).write_bytes(b"mock docx content")

    mock_doc_instance.save = _mock_save
    mock_document_class = MagicMock(return_value=mock_doc_instance)

    with patch("docx.Document", mock_document_class):
        with patch("app.services.document_image_service._get_dot_work_dir") as mock_work_dir:
            tmp = tempfile.mkdtemp()
            mock_work_dir.return_value = Path(tmp)

            response = client.post(
                "/v1/documents/generate-with-images",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "title": "Documento con imágenes",
                    "content": "# Título\n\nContenido del documento.\n\n[IMAGE:0]",
                    "image_paths": [],
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert "filename" in data
            assert "path" in data
            assert "size_bytes" in data
            assert isinstance(data["size_bytes"], int)
