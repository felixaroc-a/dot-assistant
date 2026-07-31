"""Tests del bridge file_search — GAP 4.

Verifica que file_search_handler acepte parámetros correctamente
y que el tool esté registrado en build_default_registry.
"""

from __future__ import annotations

from unittest.mock import patch

from app.application.agent.ports import ToolResult
from app.application.agent.tools.file_search import file_search_handler
from app.application.agent.tools import build_default_registry


# ─────────────────────────────────────────────────────────
# 1. file_search_handler acepta query y devuelve estructura
# ─────────────────────────────────────────────────────────


def test_file_search_tool_accepts_query() -> None:
    """Llama al handler con parámetros mockeados y verifica estructura de respuesta."""

    mock_bridge_response = {
        "ok": True,
        "results": [
            {
                "name": "factura_marzo.pdf",
                "path": "C:/Users/test/Desktop/factura_marzo.pdf",
                "size": 102400,
                "modified": "2025-01-15T10:30:00Z",
                "extension": ".pdf",
            }
        ],
        "count": 1,
    }

    with patch(
        "app.application.agent.tools.file_search.execute_local_tool_via_bridge",
        return_value=mock_bridge_response,
    ):
        result = file_search_handler(
            uid="test-uid-123",
            arguments={
                "query": "factura",
                "searchRoot": "desktop",
            },
        )

        assert isinstance(result, ToolResult)
        assert result.ok is True
        assert "Búsqueda completada" in result.output
        assert "1 archivo" in result.output
        assert len(result.artifacts) >= 1
        assert result.artifacts[0]["type"] == "document"
        assert result.artifacts[0]["mime"] == "application/pdf"
        assert "factura" in result.artifacts[0]["name"]


def test_file_search_tool_rejects_empty_query() -> None:
    """file_search_handler debe rechazar query vacío."""

    result = file_search_handler(
        uid="test-uid-123",
        arguments={"query": ""},
    )

    assert result.ok is False
    assert "require query" in result.error.lower() or "query" in result.error.lower()


def test_file_search_tool_handles_bridge_error() -> None:
    """file_search_handler debe manejar errores del bridge."""

    with patch(
        "app.application.agent.tools.file_search.execute_local_tool_via_bridge",
        return_value={"ok": False, "error": "bridge_unreachable"},
    ):
        result = file_search_handler(
            uid="test-uid-123",
            arguments={"query": "archivo"},
        )

        assert result.ok is False
        assert "puente" in result.error.lower() or "bridge" in result.error.lower()


def test_file_search_tool_with_content_pattern() -> None:
    """file_search_handler con contentPattern opcional."""

    mock_response = {
        "ok": True,
        "results": [
            {
                "name": "notas.txt",
                "path": "C:/Users/test/Documents/notas.txt",
                "size": 512,
                "modified": "2025-03-10T08:00:00Z",
                "extension": ".txt",
            }
        ],
        "count": 1,
    }

    with patch(
        "app.application.agent.tools.file_search.execute_local_tool_via_bridge",
        return_value=mock_response,
    ):
        result = file_search_handler(
            uid="test-uid-123",
            arguments={
                "query": "notas",
                "contentPattern": "reunión",
                "searchRoot": "documents",
            },
        )

        assert result.ok is True
        assert result.artifacts[0]["mime"] == "text/plain"


# ─────────────────────────────────────────────────────────
# 2. Verificar registro en build_default_registry
# ─────────────────────────────────────────────────────────


def test_file_search_registry() -> None:
    """Verifica que file_search esté en build_default_registry()."""
    reg = build_default_registry()
    spec_names = {s.name for s in reg.list_specs()}
    assert "file_search" in spec_names, "file_search no encontrado en el registry"
