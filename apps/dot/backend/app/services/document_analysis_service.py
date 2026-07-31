"""Servicio de análisis semántico de documentos con LLM.

Toma un documento (PDF, DOCX, TXT), extrae su texto, y permite
hacer preguntas sobre el contenido usando el LLM.

Usa PyMuPDF (fitz) para PDF, python-docx para DOCX.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.settings import settings

log = logging.getLogger("dot.doc_analysis")

# ─── Configs ──────────────────────────────────────────────────────────

MAX_CHUNK_CHARS = 12000  # Caracteres por chunk enviado al LLM
MAX_CHUNKS = 10           # Máximo de chunks a procesar
ANALYSIS_SYSTEM_PROMPT = (
    "Eres un asistente experto en análisis documental. "
    "Tu tarea es analizar el contenido de un documento y responder preguntas "
    "sobre él con precisión. "
    "Responde siempre en español, de forma clara y concisa. "
    "Si la respuesta no está en el documento, indícalo explícitamente. "
    "Solo responde basándote en el contenido del documento proporcionado."
)


@dataclass
class DocumentContent:
    """Contenido extraído de un documento."""
    text: str
    file_type: str
    filename: str
    pages: int = 0
    chunks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Resultado de un análisis semántico."""
    question: str
    answer: str
    source: str
    relevant_chunks: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model: str = ""
    tokens_used: int = 0


# ─── Extracción ───────────────────────────────────────────────────────


def extract_text_from_file(file_path: str | Path) -> DocumentContent:
    """Extrae texto de un archivo según su extensión.

    Soportado: .pdf (PyMuPDF), .docx (python-docx), .txt, .md
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

    suffix = path.suffix.lower()
    filename = path.name

    if suffix == ".pdf":
        return _extract_pdf(path, filename)
    elif suffix == ".docx":
        return _extract_docx(path, filename)
    elif suffix in (".txt", ".md", ".csv", ".log"):
        return _extract_text(path, filename)
    else:
        raise ValueError(f"Tipo de archivo no soportado: {suffix}")


def _extract_pdf(path: Path, filename: str) -> DocumentContent:
    """Extrae texto de PDF usando PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError(
            "PyMuPDF no instalado. Ejecuta: pip install PyMuPDF"
        )

    doc = fitz.open(str(path))
    pages = []
    metadata = {}

    try:
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "page_count": doc.page_count,
        }

        for page_num in range(min(doc.page_count, 200)):
            page = doc[page_num]
            text = page.get_text("text")
            if text.strip():
                pages.append(text)

        text = "\n\n".join(pages)

        chunks = _chunk_text(text, MAX_CHUNK_CHARS)

        return DocumentContent(
            text=text,
            file_type="pdf",
            filename=filename,
            pages=len(pages),
            chunks=chunks,
            metadata=metadata,
        )
    finally:
        doc.close()


def _extract_docx(path: Path, filename: str) -> DocumentContent:
    """Extrae texto de DOCX usando python-docx."""
    try:
        from docx import Document
    except ImportError:
        raise ImportError(
            "python-docx no instalado. Ejecuta: pip install python-docx"
        )

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n\n".join(paragraphs)

    chunks = _chunk_text(text, MAX_CHUNK_CHARS)

    return DocumentContent(
        text=text,
        file_type="docx",
        filename=filename,
        pages=0,
        chunks=chunks,
        metadata={"paragraph_count": len(paragraphs)},
    )


def _extract_text(path: Path, filename: str) -> DocumentContent:
    """Extrae texto de archivos de texto plano."""
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = _chunk_text(text, MAX_CHUNK_CHARS)

    return DocumentContent(
        text=text,
        file_type=filename.rsplit(".", 1)[-1] if "." in filename else "txt",
        filename=filename,
        pages=0,
        chunks=chunks,
        metadata={"size_bytes": path.stat().st_size},
    )


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Divide texto en chunks respetando párrafos."""
    if len(text) <= max_chars:
        return [text]

    paragraphs = text.split("\n\n")
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            current = para

    if current:
        chunks.append(current)

    return chunks[:MAX_CHUNKS]


# ─── Análisis LLM ─────────────────────────────────────────────────────


async def analyze_document(
    file_path: str,
    question: str,
    *,
    model: str = "auto",
) -> AnalysisResult:
    """Analiza un documento con LLM respondiendo una pregunta.

    Args:
        file_path: Ruta al archivo a analizar.
        question: Pregunta sobre el documento.
        model: Modelo LLM a usar ("auto", "deepseek", "openai", "anthropic").

    Returns:
        AnalysisResult con la respuesta y metadatos.
    """
    doc = extract_text_from_file(file_path)

    if not doc.text.strip():
        return AnalysisResult(
            question=question,
            answer="El documento está vacío o no se pudo extraer texto.",
            source=doc.filename,
        )

    if not question.strip():
        return AnalysisResult(
            question="",
            answer="No se proporcionó una pregunta para analizar.",
            source=doc.filename,
        )

    # Seleccionar chunks relevantes (los más relevantes primero)
    relevant = _select_relevant_chunks(doc.chunks, question)

    if not relevant:
        relevant = doc.chunks[:1]  # Fallback: usar primer chunk

    answer, model_used, tokens = await _ask_llm(
        document_text="\n\n".join(relevant),
        question=question,
        model=model,
    )

    return AnalysisResult(
        question=question,
        answer=answer,
        source=doc.filename,
        relevant_chunks=relevant,
        confidence=0.85,
        model=model_used,
        tokens_used=tokens,
    )


async def analyze_document_text(
    text: str,
    question: str,
    *,
    model: str = "auto",
    source: str = "text",
) -> AnalysisResult:
    """Analiza texto plano con LLM respondiendo una pregunta."""
    if not text.strip():
        return AnalysisResult(
            question=question,
            answer="El texto proporcionado está vacío.",
            source=source,
        )

    chunks = _chunk_text(text, MAX_CHUNK_CHARS)
    relevant = _select_relevant_chunks(chunks, question) or chunks[:1]

    answer, model_used, tokens = await _ask_llm(
        document_text="\n\n".join(relevant),
        question=question,
        model=model,
    )

    return AnalysisResult(
        question=question,
        answer=answer,
        source=source,
        relevant_chunks=relevant,
        confidence=0.85,
        model=model_used,
        tokens_used=tokens,
    )


def _select_relevant_chunks(chunks: list[str], question: str) -> list[str]:
    """Selecciona los chunks más relevantes para la pregunta usando heurística simple."""
    if not chunks:
        return []

    question_lower = question.lower()
    keywords = [w for w in question_lower.split() if len(w) > 2]

    if not keywords or len(chunks) <= 2:
        return chunks[:3]

    scored = []
    for chunk in chunks:
        chunk_lower = chunk.lower()
        score = sum(1 for kw in keywords if kw in chunk_lower)
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:3]]


async def _ask_llm(
    document_text: str,
    question: str,
    model: str = "auto",
) -> tuple[str, str, int]:
    """Envía pregunta + contexto al LLM y devuelve respuesta.

    Returns:
        (respuesta, nombre_modelo, tokens_usados)
    """
    user_message = (
        f"DOCUMENTO:\n\n{document_text[:25000]}\n\n"
        f"PREGUNTA: {question}\n\n"
        f"Responde basándote exclusivamente en el contenido del documento. "
        f"Si la información no está en el documento, di: 'No encontré esa información en el documento.'"
    )

    # Intentar con el modelo preferido o auto-detectar
    model_used = "deepseek"
    tokens_used = 0

    try:
        # Usar DeepSeek como default (OpenAI-compatible)
        deepseek_key = (settings.deepseek_api_key or "").strip()
        if deepseek_key:
            result = await _call_deepseek(
                system=ANALYSIS_SYSTEM_PROMPT,
                user=user_message,
                api_key=deepseek_key,
            )
            if result:
                return result[0], model_used, result[1]
    except Exception as e:
        log.warning("DeepSeek analysis falló: %s", e)

    try:
        openai_key = (settings.openai_api_key or "").strip()
        if openai_key:
            result = await _call_openai(
                system=ANALYSIS_SYSTEM_PROMPT,
                user=user_message,
                api_key=openai_key,
            )
            if result:
                return result[0], "openai", result[1]
    except Exception as e:
        log.warning("OpenAI analysis falló: %s", e)

    try:
        anthropic_key = (settings.anthropic_api_key or "").strip()
        if anthropic_key:
            result = await _call_anthropic(
                system=ANALYSIS_SYSTEM_PROMPT,
                user=user_message,
                api_key=anthropic_key,
            )
            if result:
                return result[0], "anthropic", result[1]
    except Exception as e:
        log.warning("Anthropic analysis falló: %s", e)

    # Si nada funciona, devolver error claro
    raise RuntimeError(
        "No se pudo analizar el documento. Configure al menos una API key de IA "
        "(DEEPSEEK_API_KEY, OPENAI_API_KEY, o ANTHROPIC_API_KEY)."
    )


async def _call_deepseek(system: str, user: str, api_key: str) -> tuple[str, int] | None:
    """Llama a DeepSeek API (OpenAI-compatible)."""
    url = (settings.deepseek_api_base or "https://api.deepseek.com/v1").rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.deepseek_chat_model or "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"].strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return answer, tokens


async def _call_openai(system: str, user: str, api_key: str) -> tuple[str, int] | None:
    """Llama a OpenAI API."""
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"].strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return answer, tokens


async def _call_anthropic(system: str, user: str, api_key: str) -> tuple[str, int] | None:
    """Llama a Anthropic Claude API."""
    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": "claude-3-haiku-20240307",
        "max_tokens": 2048,
        "system": system,
        "messages": [
            {"role": "user", "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["content"][0]["text"].strip()
        tokens = data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0)
        return answer, tokens


# ─── Summarize ─────────────────────────────────────────────────────────


async def summarize_document(
    file_path: str,
    *,
    max_length: int = 500,
    model: str = "auto",
) -> AnalysisResult:
    """Genera un resumen ejecutivo de un documento."""
    doc = extract_text_from_file(file_path)

    if not doc.text.strip():
        return AnalysisResult(
            question="Resumen del documento",
            answer="El documento está vacío.",
            source=doc.filename,
        )

    # Usar primeros chunks para resumen
    summary_chunks = doc.chunks[:3]
    summary_text = "\n\n".join(summary_chunks)

    question = (
        f"Genera un resumen ejecutivo en español de máximo {max_length} caracteres. "
        f"Incluye los puntos más importantes, datos clave y conclusiones si las hay."
    )

    answer, model_used, tokens = await _ask_llm(
        document_text=summary_text,
        question=question,
        model=model,
    )

    return AnalysisResult(
        question="Resumen del documento",
        answer=answer,
        source=doc.filename,
        model=model_used,
        tokens_used=tokens,
    )
