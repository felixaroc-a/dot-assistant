"""Tests de inyección de plan en system prompt."""

from app.application.agent.reasoning import PlanArtifact, inject_plan_into_system_prompt


def test_inject_plan_appends_structured_block() -> None:
    plan = PlanArtifact(
        intent="Enviar mensaje por WhatsApp",
        steps=["Validar número", "Usar send_whatsapp_message"],
        tools_needed=["send_whatsapp_message"],
        success_criteria="Tool WA retorna ok=true",
        user_visible_summary="Enviaré el mensaje por WhatsApp tras confirmar el número.",
        level="medium",
    )
    out = inject_plan_into_system_prompt("Base prompt.", plan)
    assert "Base prompt." in out
    assert "Enviar mensaje por WhatsApp" in out
    assert "send_whatsapp_message" in out
    assert "Criterio de éxito" in out
    assert "NO te detengas" in out or "completa TODOS" in out
