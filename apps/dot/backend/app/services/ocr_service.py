"""Servicio de OCR (Optical Character Recognition) para DOT.

Usa Tesseract OCR (vía pytesseract) para extraer texto de imágenes.
Soporta JPG, PNG, BMP, TIFF, y PDFs basados en imágenes.

Instalación de Tesseract:
  Windows: descargar de https://github.com/UB-Mannheim/tesseract/wiki
  Linux:   apt-get install tesseract-ocr tesseract-ocr-spa
  macOS:   brew install tesseract tesseract-lang

Requisitos Python: pip install pytesseract Pillow
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("dot.ocr")

# MIME types soportados
SUPPORTED_IMAGE_TYPES = frozenset({
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/bmp",
    "image/tiff",
    "image/webp",
    "image/gif",
    "application/pdf",
})

SUPPORTED_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif",
    ".webp", ".gif", ".pdf",
})


@dataclass
class OCRResult:
    """Resultado de extracción OCR."""
    text: str
    source: str
    language: str
    confidence: float = 0.0
    page_count: int = 1
    metadata: dict[str, Any] | None = None
    error: str | None = None


def ocr_available() -> bool:
    """Verifica si Tesseract está instalado y disponible."""
    try:
        import pytesseract
        version = pytesseract.get_tesseract_version()
        log.debug("Tesseract disponible: v%s", version)
        return True
    except Exception:
        return False


def _get_tesseract_path() -> str | None:
    """Intenta detectar la ruta de Tesseract en Windows."""
    import sys
    if sys.platform != "win32":
        return None

    candidates = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        Path.home() / r"AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _ensure_tesseract() -> None:
    """Configura y verifica Tesseract."""
    try:
        import pytesseract

        tesseract_path = _get_tesseract_path()
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        pytesseract.get_tesseract_version()
    except ImportError:
        raise ImportError(
            "pytesseract no instalado. Ejecuta: pip install pytesseract Pillow\n"
            "Y asegúrate de tener Tesseract OCR instalado en tu sistema."
        )
    except Exception as e:
        raise RuntimeError(
            f"Tesseract OCR no encontrado o no funcional: {e}\n"
            "Instala Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki"
        )


def ocr_from_file(
    file_path: str | Path,
    *,
    language: str = "spa+eng",
    page_range: tuple[int, int] | None = None,
) -> OCRResult:
    """Extrae texto de una imagen o PDF usando OCR.

    Args:
        file_path: Ruta al archivo de imagen o PDF.
        language: Idioma(s) para OCR (default: "spa+eng").
        page_range: Rango de páginas a procesar (para PDFs).

    Returns:
        OCRResult con el texto extraído.
    """
    _ensure_tesseract()
    import pytesseract

    path = Path(file_path)
    if not path.exists():
        return OCRResult(
            text="",
            source=str(path),
            language=language,
            error=f"Archivo no encontrado: {file_path}",
        )

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return OCRResult(
            text="",
            source=str(path),
            language=language,
            error=f"Formato no soportado: {suffix}. Soportados: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    if suffix == ".pdf":
        return _ocr_pdf(path, language=language, page_range=page_range)
    else:
        return _ocr_image(path, language=language)


def ocr_from_bytes(
    data: bytes,
    mime_type: str = "image/png",
    *,
    language: str = "spa+eng",
    source_name: str = "image",
) -> OCRResult:
    """Extrae texto de bytes de imagen usando OCR.

    Args:
        data: Bytes de la imagen.
        mime_type: MIME type de la imagen.
        language: Idioma(s) para OCR.
        source_name: Nombre descriptivo de la fuente.

    Returns:
        OCRResult con el texto extraído.
    """
    _ensure_tesseract()
    import pytesseract
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
        text = pytesseract.image_to_string(image, lang=language)

        confidence = _estimate_confidence(text)

        return OCRResult(
            text=text.strip(),
            source=source_name,
            language=language,
            confidence=confidence,
            page_count=1,
            metadata={
                "size": image.size,
                "mode": image.mode,
                "format": image.format or mime_type,
            },
        )
    except Exception as e:
        log.exception("Error OCR desde bytes")
        return OCRResult(
            text="",
            source=source_name,
            language=language,
            error=str(e),
        )


def _ocr_image(path: Path, language: str) -> OCRResult:
    """OCR de un archivo de imagen."""
    import pytesseract
    from PIL import Image

    try:
        image = Image.open(path)
        text = pytesseract.image_to_string(image, lang=language)

        confidence = _estimate_confidence(text)

        return OCRResult(
            text=text.strip(),
            source=str(path),
            language=language,
            confidence=confidence,
            page_count=1,
            metadata={
                "size": image.size,
                "mode": image.mode,
                "format": image.format,
                "file_size": path.stat().st_size,
            },
        )
    except Exception as e:
        log.exception("Error OCR desde archivo: %s", path)
        return OCRResult(
            text="",
            source=str(path),
            language=language,
            error=str(e),
        )


def _ocr_pdf(
    path: Path,
    language: str,
    page_range: tuple[int, int] | None = None,
) -> OCRResult:
    """OCR de un PDF, página por página (convierte cada página a imagen)."""
    import pytesseract
    from PIL import Image

    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError(
            "PyMuPDF requerido para OCR de PDFs. Ejecuta: pip install PyMuPDF"
        )

    doc = fitz.open(str(path))
    all_text = []
    page_count = 0

    try:
        start_page, end_page = 0, doc.page_count
        if page_range:
            start_page = max(0, page_range[0] - 1)
            end_page = min(doc.page_count, page_range[1])

        for page_num in range(start_page, end_page):
            page = doc[page_num]

            # Renderizar página a imagen (DPI 200 para buen OCR)
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")

            image = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(image, lang=language)

            if text.strip():
                all_text.append(text)

            page_count += 1

        combined_text = "\n\n--- Página {} ---\n\n".join(
            [
                all_text[i]
                for i in range(len(all_text))
            ]
        ) if all_text else ""
        # Fix: use actual page numbers in separator
        if all_text:
            page_texts = []
            for i, t in enumerate(all_text):
                page_texts.append(f"--- Página {i + 1} ---\n\n{t}")
            combined_text = "\n\n".join(page_texts)
        else:
            combined_text = ""

        confidence = _estimate_confidence(combined_text)

        return OCRResult(
            text=combined_text.strip(),
            source=str(path),
            language=language,
            confidence=confidence,
            page_count=page_count,
            metadata={
                "total_pages": doc.page_count,
                "ocr_pages": page_count,
                "file_size": path.stat().st_size,
            },
        )
    finally:
        doc.close()


def _estimate_confidence(text: str) -> float:
    """Estima la confianza del OCR basado en caracteres reconocibles."""
    if not text.strip():
        return 0.0

    total = len(text)
    if total == 0:
        return 0.0

    # Contar caracteres alfanuméricos y signos comunes
    valid_chars = sum(1 for c in text if c.isalnum() or c in " .,;:!?-\n()[]{}/@#&%$€")
    ratio = valid_chars / total

    # Penalizar si hay muchos caracteres extraños
    if ratio < 0.7:
        return 0.3
    elif ratio < 0.85:
        return 0.6
    else:
        return min(0.95, ratio)
