"""Tests de anclaje a evidencia (grounding) para informes técnicos."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.agent.grounding import (
    extract_claimed_paths,
    looks_ungrounded_final,
    repair_saved_path_claim,
    ungrounded_paths,
)
from app.application.agent.ports import ToolResult, ToolSpec
from app.application.agent.registry import ToolRegistry
from app.application.agent.runtime import run_agent
from app.application.agent.truth_check import truth_check_file_mission


@dataclass
class _FakeAI:
    content: str
    usage: dict | None = None
    model: str = "fake"


def test_extract_claimed_paths_from_report():
    text = (
        "Archivo `services/src/config/index.ts` y también "
        "apps/dot/backend/app/main.py tienen problemas."
    )
    paths = extract_claimed_paths(text)
    assert any("services/src/config/index.ts" in p for p in paths)
    assert any("apps/dot/backend/app/main.py" in p for p in paths)


def test_ungrounded_when_paths_not_in_evidence():
    claimed = ["services/src/config/index.ts", "frontend/src/app/page.tsx", "infra/terraform/main.tf"]
    evidence = "path=C:/x/Nordik-IA\n[dir] apps\n[dir] docs\n[file] AGENTS.md"
    bad = ungrounded_paths(claimed, evidence)
    assert len(bad) == 3


def test_looks_ungrounded_hallucinated_report():
    user = "analiza C:\\Users\\X\\Nordik-IA y hazme un informe tecnico profundo"
    final = (
        "Leí `services/src/config/index.ts`, `services/src/services/agentService.ts`, "
        "`frontend/src/app/page.tsx` y `infra/terraform/main.tf`. "
        "El JWT secret está hardcodeado. Informe en "
        "C:\\Users\\X\\Escritorio\\Nordik-IA\\informe_tecnico_nordik_ia.docx"
    )
    trace = [
        {
            "tool": "listFiles",
            "ok": True,
            "preview": "path=C:/Users/X/Nordik-IA\n[dir] apps\n[dir] docs\n[file] AGENTS.md",
        }
    ]
    assert looks_ungrounded_final(user_text=user, final_text=final, tool_trace=trace) is True


def test_truth_check_flags_fake_docx_on_analysis():
    user = "analiza la carpeta y hazme un informe tecnico"
    text = (
        "Informe listo en C:\\Users\\X\\Escritorio\\Nordik-IA\\informe_tecnico_nordik_ia.docx "
        "con hallazgos sobre JWT."
    )
    out = truth_check_file_mission(user_text=user, final_text=text, tool_trace=[])
    assert "no se generó" in out.lower() or "nota dot" in out.lower()


def test_repair_saved_path_replaces_fake_docx():
    text = "Documento en C:\\Users\\X\\fake\\informe.docx"
    trace = [
        {
            "tool": "generate_document",
            "ok": True,
            "preview": "Documento creado: informe.docx\nRuta: C:\\Users\\X\\Documents\\DOT\\Trabajos\\informe.docx\n",
        }
    ]
    out = repair_saved_path_claim(text, trace)
    assert "Documents\\DOT\\Trabajos\\informe.docx" in out or "DOT\\Trabajos" in out
    assert "fake\\informe.docx" not in out


def test_runtime_nudges_ungrounded_then_accepts_grounded():
    reg = ToolRegistry()

    def list_handler(uid: str, arguments: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            output=(
                "path=C:/Nordik-IA\n"
                "directorios:\n  [dir] apps\n  [dir] docs\n"
                "archivos:\n  [file] AGENTS.md\n"
            ),
        )

    def read_handler(uid: str, arguments: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            output="path=C:/Nordik-IA/AGENTS.md\n# Contexto del proyecto Nordik-IA\nElectron + FastAPI\n",
        )

    reg.register(ToolSpec(name="listFiles", description="list"), list_handler)
    reg.register(ToolSpec(name="readFile", description="read"), read_handler)

    turns = [
        _FakeAI(content='{"tool_calls":[{"name":"listFiles","arguments":{"path":"C:/Nordik-IA"}}]}'),
        _FakeAI(
            content=(
                "Analicé `services/src/config/index.ts`, `frontend/src/app/page.tsx` "
                "e `infra/terraform/main.tf`. JWT hardcodeado. "
                "Guardé en C:\\fake\\informe.docx"
            )
        ),
        _FakeAI(content='{"tool_calls":[{"name":"readFile","arguments":{"path":"C:/Nordik-IA/AGENTS.md"}}]}'),
        _FakeAI(
            content=(
                "Según `AGENTS.md` leído, Nordik-IA es Electron + FastAPI. "
                "Mejoras: reforzar truth_check y grounding. No hay DOCX en esta pasada."
            )
        ),
    ]
    idx = {"i": 0}
    saw_ground = {"ok": False}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        if "sin anclar" in user_text.lower() or "ANCLAJE" in user_text or "evidencia" in user_text.lower():
            saw_ground["ok"] = True
        out = turns[idx["i"]]
        idx["i"] += 1
        return out

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="analiza C:\\Nordik-IA y hazme un informe tecnico profundo con mejoras",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=8,
    )
    assert saw_ground["ok"] is True
    assert "AGENTS.md" in result.final_text or "FastAPI" in result.final_text
    assert "services/src/config/index.ts" not in result.final_text
