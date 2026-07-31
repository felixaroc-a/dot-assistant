"""Truth-check con reasoning: no afirmar WA sin tool OK."""

from app.application.agent.reasoning import apply_reasoning
from app.application.agent.truth_check import truth_check_file_mission


def test_reasoning_low_still_blocks_fake_wa(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.firebase_db.get_user_profile",
        lambda _uid: {"reasoning_enabled": True, "reasoning_level": "low"},
    )
    result = apply_reasoning(
        uid="user-1",
        channel="pc",
        user_text="envía whatsapp a 04121234567 diciendo hola",
        base_system_prompt="Eres DOT.",
    )
    assert result.effective_level == "low"
    assert "RAZONAMIENTO" in result.system_prompt

    out = truth_check_file_mission(
        user_text="envía whatsapp a 04121234567 diciendo hola",
        final_text="✅ Mensaje enviado por WhatsApp.",
        tool_trace=[],
    )
    assert "whatsapp" in out.lower() or "no pude" in out.lower()
