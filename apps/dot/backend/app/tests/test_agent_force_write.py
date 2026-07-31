"""Tests force writeFile / web_search en Agent Runtime."""

from app.application.agent.ports import ToolResult
from app.application.agent.registry import ToolRegistry
from app.application.agent.runtime import run_agent
from app.application.agent.ports import ToolSpec


class _FakeAI:
    def __init__(self, content: str):
        self.content = content
        self.usage = {"prompt_tokens": 1, "completion_tokens": 1}
        self.model = "fake"


def test_force_write_simple_create():
    reg = ToolRegistry()
    written = {}

    def write_handler(uid, args):
        written["path"] = args.get("path")
        written["content"] = args.get("content")
        return ToolResult(ok=True, output=f"Archivo guardado en: C:/Escritorio/{args['path']}")

    reg.register(
        ToolSpec(name="writeFile", description="w", parameters_schema={}),
        write_handler,
    )

    result = run_agent(
        uid="u1",
        channel="pc",
        text="crea wa-prueba.txt en Escritorio con hola",
        system_prompt="test",
        registry=reg,
        model_fn=lambda _u, _s: _FakeAI("Claro, ya lo guardé."),
        max_steps=3,
    )
    assert any(t.get("tool") == "writeFile" and t.get("ok") for t in result.tool_trace)
    assert written.get("content") == "hola"
    assert "wa-prueba.txt" in str(written.get("path"))
    assert "guardado" in result.final_text.lower() or "✅" in result.final_text


def test_force_search_then_write():
    reg = ToolRegistry()
    calls = []

    def web_handler(uid, args):
        calls.append("web")
        return ToolResult(ok=True, output="1. Tech news\nFuente: https://example.com")

    def write_handler(uid, args):
        calls.append("write")
        return ToolResult(ok=True, output="Archivo guardado en: C:/Escritorio/resumen-tech.txt")

    reg.register(ToolSpec(name="web_search", description="s", parameters_schema={}), web_handler)
    reg.register(ToolSpec(name="writeFile", description="w", parameters_schema={}), write_handler)

    result = run_agent(
        uid="u1",
        channel="pc",
        text=(
            "busca noticias de tecnología, resume en 5 líneas "
            "y guarda el resumen en mi Escritorio como resumen-tech.txt"
        ),
        system_prompt="test",
        registry=reg,
        model_fn=lambda _u, _s: _FakeAI("Listo, ya lo guardé en el Escritorio."),
        max_steps=3,
    )
    assert "web" in calls and "write" in calls
    assert any(t.get("tool") == "writeFile" and t.get("ok") for t in result.tool_trace)
    assert "resumen-tech.txt" in result.final_text


def test_force_write_after_model_searched_but_claimed_save():
    """Modelo hizo web_search y afirmó guardar sin writeFile → forzar ambos contenidos."""
    reg = ToolRegistry()
    calls = []

    def web_handler(uid, args):
        calls.append("web")
        return ToolResult(
            ok=True,
            output="1. Chip AI\n2. Cloud\n3. Robots\nFuente: https://example.com/tech",
        )

    def write_handler(uid, args):
        calls.append("write")
        assert "Chip AI" in (args.get("content") or "")
        return ToolResult(ok=True, output="Archivo guardado en: C:/Escritorio/resumen-tech.txt")

    # Primera llamada del modelo: ya "buscó" vía tool_calls; segunda: solo texto
    responses = [
        _FakeAI(
            '{"tool_calls":[{"name":"web_search","arguments":{"query":"noticias tecnologia"}}]}'
        ),
        _FakeAI("Listo, ya lo guardé en el Escritorio."),
    ]

    def model_fn(_u, _s):
        return responses.pop(0)

    reg.register(ToolSpec(name="web_search", description="s", parameters_schema={}), web_handler)
    reg.register(ToolSpec(name="writeFile", description="w", parameters_schema={}), write_handler)

    result = run_agent(
        uid="u1",
        channel="pc",
        text=(
            "busca noticias de tecnología, resume en 5 líneas "
            "y guarda el resumen en mi Escritorio como resumen-tech.txt"
        ),
        system_prompt="test",
        registry=reg,
        model_fn=model_fn,
        max_steps=4,
    )
    assert calls.count("write") == 1
    assert any(t.get("tool") == "writeFile" and t.get("ok") for t in result.tool_trace)
    assert "resumen-tech.txt" in result.final_text


def test_force_write_ignores_pdf_url_in_history():
    """Historial con PDF no debe bloquear writeFile del mensaje nuevo."""
    reg = ToolRegistry()
    written = {}

    def write_handler(uid, args):
        written["path"] = args.get("path")
        written["content"] = args.get("content")
        return ToolResult(ok=True, output="Archivo guardado en: C:/Escritorio/wa-prueba.txt")

    reg.register(
        ToolSpec(name="writeFile", description="w", parameters_schema={}),
        write_handler,
    )

    result = run_agent(
        uid="u1",
        channel="pc",
        text="crea wa-prueba.txt en Escritorio con hola",
        history=(
            "Usuario: descarga https://ejemplo.com/informe.pdf al Escritorio\n"
            "Asistente: Listo, descargué el PDF."
        ),
        system_prompt="test",
        registry=reg,
        model_fn=lambda _u, _s: _FakeAI("Ya lo guardé."),
        max_steps=3,
    )
    assert any(t.get("tool") == "writeFile" and t.get("ok") for t in result.tool_trace)
    assert written.get("content") == "hola"
    assert "wa-prueba.txt" in str(written.get("path"))
