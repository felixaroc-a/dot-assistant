"""Servicio de resumen: texto libre, URLs y PDFs remotos con chunking."""
from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urlparse

import httpx


class SummarizerService:
    def __init__(
        self,
        max_chunk_chars: int = 8_000,
        overlap_chars: int = 2_000,
        timeout_seconds: int = 20,
    ) -> None:
        self.max_chunk_chars = max(1_000, max_chunk_chars)
        self.overlap_chars = max(0, min(overlap_chars, self.max_chunk_chars - 1))
        self.timeout_seconds = max(5, timeout_seconds)

    def summarize(
        self,
        text_or_url: str,
        summarize_fn: Callable[[str], str],
    ) -> dict[str, str | int]:
        source = (text_or_url or "").strip()
        if not source:
            raise ValueError("Debes proporcionar texto, URL o PDF para resumir.")

        source_type, extracted_text = self._resolve_source(source)
        normalized = self._normalize_whitespace(extracted_text)
        if not normalized:
            raise RuntimeError("No se pudo extraer contenido útil para resumir.")

        chunks = self._chunk_text(normalized)
        partials: list[str] = []
        total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            prompt = self._build_chunk_prompt(chunk, idx, total)
            summary = (summarize_fn(prompt) or "").strip()
            if not summary:
                raise RuntimeError("El proveedor IA devolvió un resumen vacío para un bloque.")
            partials.append(summary)

        final_summary = partials[0]
        if total > 1:
            merge_prompt = self._build_merge_prompt(partials)
            merged = (summarize_fn(merge_prompt) or "").strip()
            if not merged:
                raise RuntimeError("El proveedor IA devolvió un resumen final vacío.")
            final_summary = merged

        return {
            "summary": final_summary,
            "source_type": source_type,
            "chunks": total,
        }

    def _resolve_source(self, source: str) -> tuple[str, str]:
        if not self._looks_like_url(source):
            return "text", source

        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(source)
            response.raise_for_status()

        content_type = (response.headers.get("content-type") or "").lower()
        parsed = urlparse(source)
        is_pdf = "application/pdf" in content_type or parsed.path.lower().endswith(".pdf")
        if is_pdf:
            return "pdf_url", self._extract_pdf_text(response.content)

        return "url", self._extract_html_text(response.text)

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _extract_html_text(html: str) -> str:
        try:
            from bs4 import BeautifulSoup  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Falta dependencia beautifulsoup4 para resumir URLs HTML."
            ) from exc

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return text

    @staticmethod
    def _extract_pdf_text(pdf_bytes: bytes) -> str:
        try:
            import fitz  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Falta dependencia PyMuPDF para resumir PDFs.") from exc

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            chunks: list[str] = []
            for page in doc:
                content = (page.get_text() or "").strip()
                if content:
                    chunks.append(content)
            return "\n".join(chunks)
        finally:
            doc.close()

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _chunk_text(self, text: str) -> list[str]:
        if len(text) <= self.max_chunk_chars:
            return [text]

        chunks: list[str] = []
        step = self.max_chunk_chars - self.overlap_chars
        if step <= 0:
            step = self.max_chunk_chars

        start = 0
        while start < len(text):
            end = min(start + self.max_chunk_chars, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start += step
        return chunks or [text]

    @staticmethod
    def _build_chunk_prompt(chunk: str, idx: int, total: int) -> str:
        return (
            "Resume el siguiente contenido en español claro. "
            "Incluye ideas principales y datos accionables.\n"
            f"Bloque {idx} de {total}:\n\n{chunk}"
        )

    @staticmethod
    def _build_merge_prompt(partials: list[str]) -> str:
        merged = "\n\n".join(f"Resumen parcial {idx}:\n{text}" for idx, text in enumerate(partials, start=1))
        return (
            "Unifica estos resúmenes parciales en un único resumen ejecutivo en español. "
            "Evita repeticiones y conserva puntos críticos:\n\n"
            f"{merged}"
        )
