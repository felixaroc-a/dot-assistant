"""Tests truth_check — no afirmar archivo sin tool OK."""

from app.application.agent.truth_check import truth_check_file_mission


def test_truth_check_passes_when_write_ok():
    out = truth_check_file_mission(
        user_text="crea resumen.txt en Escritorio",
        final_text="Guardé el resumen en tu Escritorio.",
        tool_trace=[{"tool": "writeFile", "ok": True, "ms": 10}],
    )
    assert "Guardé" in out


def test_truth_check_passes_generate_document():
    """Informe técnico con generate_document OK no debe reemplazarse por el mensaje de nota.txt."""
    text = (
        "Analicé Nordik-IA y generé el informe técnico en DOCX. "
        "Documento creado con hallazgos y mejoras."
    )
    out = truth_check_file_mission(
        user_text=(
            "accede a C:\\Users\\Usuario\\OneDrive\\Escritorio\\Nordik-IA "
            "analízalo y hazme un informe técnico profundo"
        ),
        final_text=text,
        tool_trace=[
            {"tool": "listFiles", "ok": True},
            {"tool": "generate_document", "ok": True},
        ],
    )
    assert out == text
    assert "nota.txt" not in out.lower()


def test_truth_check_path_escritorio_alone_is_not_save_intent():
    """Una ruta bajo Escritorio no cuenta como pedido de 'guardar en Escritorio'."""
    text = "La carpeta tiene apps/, docs/ y packages/. Resumen preliminar listo."
    out = truth_check_file_mission(
        user_text="analiza C:\\Users\\X\\Escritorio\\Nordik-IA",
        final_text=text,
        tool_trace=[{"tool": "listFiles", "ok": True}],
    )
    assert out == text


def test_truth_check_blocks_hallucinated_success():
    out = truth_check_file_mission(
        user_text="crea resumen.txt en Escritorio",
        final_text="Listo, guardé el archivo en tu Escritorio.",
        tool_trace=[],
    )
    assert "no pude" in out.lower() or "Todavía" in out
    assert "Escritorio" in out or "PC" in out


def test_truth_check_blocks_fake_search():
    out = truth_check_file_mission(
        user_text="busca en la web IA y dame referencias",
        final_text="✅ Archivo guardado en tu Escritorio (resumen.txt).",
        tool_trace=[],
    )
    assert "búsqueda" in out.lower() or "buscar" in out.lower() or "web" in out.lower()


def test_truth_check_ignores_plain_chat():
    text = "Hola, ¿en qué te ayudo?"
    assert (
        truth_check_file_mission(user_text="hola", final_text=text, tool_trace=[])
        == text
    )


def test_truth_check_blocks_fake_pdf_via_writefile():
    out = truth_check_file_mission(
        user_text="descarga https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf al Escritorio",
        final_text="✅ Archivo guardado en tu Escritorio (dummy.pdf).",
        tool_trace=[{"tool": "writeFile", "ok": True, "ms": 10}],
    )
    assert "download_url_to_desktop" in out or "descarga real" in out.lower()
    assert "PDF falso" in out or "No completé" in out


def test_truth_check_passes_notify_whatsapp_owner():
    out = truth_check_file_mission(
        user_text="mándamelo por WhatsApp",
        final_text="✅ Te envié el resumen por WhatsApp.",
        tool_trace=[{"tool": "notify_whatsapp_owner", "ok": True, "ms": 20}],
    )
    assert "WhatsApp" in out


def test_truth_check_blocks_fake_read_summary():
    out = truth_check_file_mission(
        user_text="Lee el PDF del Escritorio, resúmelo en 5 bullets",
        final_text="Aquí van 5 bullets del documento: ...",
        tool_trace=[],
    )
    assert "no leí" in out.lower() or "Todavía" in out


def test_truth_check_passes_real_download():
    out = truth_check_file_mission(
        user_text="descarga https://example.com/a.pdf al Escritorio",
        final_text="Descarga lista en el Escritorio.",
        tool_trace=[{"tool": "download_url_to_desktop", "ok": True, "ms": 50}],
    )
    assert "Descarga lista" in out
