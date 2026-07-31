"""Routers para análisis semántico de documentos y OCR."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_deps import require_product_jwt
from app.dependencies.limiter import limiter

log = logging.getLogger("dot.documents.analysis")

router = APIRouter(prefix="/v1/documents", tags=["documents"])


# ─── Schemas ───────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Ruta local al archivo (PDF, DOCX, TXT)")
    question: str = Field(..., min_length=1, max_length=2000, description="Pregunta sobre el documento")
    model: str = Field(default="auto", description="Modelo LLM a usar: auto, deepseek, openai, anthropic")


class AnalyzeTextRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Texto del documento a analizar")
    question: str = Field(..., min_length=1, max_length=2000, description="Pregunta sobre el texto")
    model: str = Field(default="auto", description="Modelo LLM a usar")
    source: str = Field(default="text", description="Nombre descriptivo de la fuente")


class SummarizeRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Ruta local al archivo")
    max_length: int = Field(default=500, ge=100, le=3000, description="Longitud máxima del resumen")
    model: str = Field(default="auto", description="Modelo LLM a usar")


class OCRRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Ruta local al archivo de imagen o PDF")
    language: str = Field(default="spa+eng", description="Idiomas OCR (ej: spa, eng, spa+eng)")
    page_range_start: int | None = Field(default=None, description="Página inicial (1-indexed)")
    page_range_end: int | None = Field(default=None, description="Página final")


class OCRBytesRequest(BaseModel):
    """OCR desde bytes de imagen (base64)."""
    data_base64: str = Field(..., min_length=1, description="Imagen en base64")
    mime_type: str = Field(default="image/png", description="MIME type de la imagen")
    language: str = Field(default="spa+eng", description="Idiomas OCR")


class AnalyzeResponse(BaseModel):
    ok: bool
    question: str | None = None
    answer: str | None = None
    source: str | None = None
    relevant_chunks: list[str] | None = None
    confidence: float | None = None
    model: str | None = None
    tokens_used: int | None = None
    error: str | None = None


class OCRResponse(BaseModel):
    ok: bool
    text: str | None = None
    source: str | None = None
    language: str | None = None
    confidence: float | None = None
    page_count: int | None = None
    metadata: dict | None = None
    error: str | None = None
    ocr_available: bool = True


# ─── Endpoints ─────────────────────────────────────────────────────────


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("10/minute")
async def analyze_document(
    request: Request,
    body: AnalyzeRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Analiza semánticamente un documento con LLM.

    Extrae el texto del archivo (PDF, DOCX, TXT) y responde una pregunta
    sobre su contenido usando el modelo de IA configurado.

    Ejemplo: "¿Cuál es el monto total del contrato?" analizando un PDF legal.
    """
    try:
        from app.services.document_analysis_service import analyze_document

        result = await analyze_document(
            file_path=body.path,
            question=body.question,
            model=body.model,
        )

        return AnalyzeResponse(
            ok=True,
            question=result.question,
            answer=result.answer,
            source=result.source,
            relevant_chunks=result.relevant_chunks,
            confidence=result.confidence,
            model=result.model,
            tokens_used=result.tokens_used,
        )
    except FileNotFoundError as e:
        return AnalyzeResponse(ok=False, error=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ImportError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Error analizando documento")
        raise HTTPException(status_code=500, detail=f"Error al analizar documento: {e}")


@router.post("/analyze-text", response_model=AnalyzeResponse)
@limiter.limit("20/minute")
async def analyze_document_text(
    request: Request,
    body: AnalyzeTextRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Analiza semánticamente texto plano con LLM.

    Útil para analizar contenido ya extraído o pegado directamente.
    Responde preguntas basándose exclusivamente en el texto proporcionado.
    """
    try:
        from app.services.document_analysis_service import analyze_document_text

        result = await analyze_document_text(
            text=body.text,
            question=body.question,
            model=body.model,
            source=body.source,
        )

        return AnalyzeResponse(
            ok=True,
            question=result.question,
            answer=result.answer,
            source=result.source,
            relevant_chunks=result.relevant_chunks,
            confidence=result.confidence,
            model=result.model,
            tokens_used=result.tokens_used,
        )
    except Exception as e:
        log.exception("Error analizando texto")
        raise HTTPException(status_code=500, detail=f"Error al analizar texto: {e}")


@router.post("/summarize", response_model=AnalyzeResponse)
@limiter.limit("10/minute")
async def summarize_document(
    request: Request,
    body: SummarizeRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Genera un resumen ejecutivo de un documento usando LLM.

    Extrae el texto, selecciona los fragmentos más relevantes y genera
    un resumen conciso en español.
    """
    try:
        from app.services.document_analysis_service import summarize_document

        result = await summarize_document(
            file_path=body.path,
            max_length=body.max_length,
            model=body.model,
        )

        return AnalyzeResponse(
            ok=True,
            question=result.question,
            answer=result.answer,
            source=result.source,
            model=result.model,
            tokens_used=result.tokens_used,
        )
    except FileNotFoundError as e:
        return AnalyzeResponse(ok=False, error=str(e))
    except ImportError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Error resumiendo documento")
        raise HTTPException(status_code=500, detail=f"Error al resumir documento: {e}")


# ─── OCR Endpoints ──────────────────────────────────────────────────────


@router.post("/ocr", response_model=OCRResponse)
@limiter.limit("20/minute")
async def ocr_document(
    request: Request,
    body: OCRRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Extrae texto de una imagen o PDF usando OCR (Tesseract).

    Soportado: JPG, PNG, BMP, TIFF, WEBP, GIF, PDF.
    Para PDFs, convierte cada página a imagen y aplica OCR.
    """
    try:
        from app.services.ocr_service import ocr_available, ocr_from_file

        if not ocr_available():
            return OCRResponse(
                ok=False,
                error="Tesseract OCR no está instalado en el servidor. "
                      "Instala Tesseract OCR y pytesseract.",
                ocr_available=False,
            )

        page_range = None
        if body.page_range_start is not None or body.page_range_end is not None:
            page_range = (
                body.page_range_start or 1,
                body.page_range_end or 999,
            )

        result = ocr_from_file(
            file_path=body.path,
            language=body.language,
            page_range=page_range,
        )

        return OCRResponse(
            ok=not bool(result.error),
            text=result.text,
            source=result.source,
            language=result.language,
            confidence=result.confidence,
            page_count=result.page_count,
            metadata=result.metadata,
            error=result.error,
            ocr_available=True,
        )
    except ImportError as e:
        return OCRResponse(
            ok=False,
            error=str(e),
            ocr_available=False,
        )
    except RuntimeError as e:
        return OCRResponse(
            ok=False,
            error=str(e),
            ocr_available=False,
        )
    except Exception as e:
        log.exception("Error OCR desde archivo")
        raise HTTPException(status_code=500, detail=f"Error OCR: {e}")


@router.post("/ocr-bytes", response_model=OCRResponse)
@limiter.limit("20/minute")
async def ocr_from_bytes_endpoint(
    request: Request,
    body: OCRBytesRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Extrae texto de una imagen enviada como base64 usando OCR."""
    import base64

    try:
        from app.services.ocr_service import ocr_available, ocr_from_bytes

        if not ocr_available():
            return OCRResponse(
                ok=False,
                error="Tesseract OCR no está instalado en el servidor.",
                ocr_available=False,
            )

        data = base64.b64decode(body.data_base64)

        result = ocr_from_bytes(
            data=data,
            mime_type=body.mime_type,
            language=body.language,
        )

        return OCRResponse(
            ok=not bool(result.error),
            text=result.text,
            source=result.source,
            language=result.language,
            confidence=result.confidence,
            page_count=result.page_count,
            metadata=result.metadata,
            error=result.error,
            ocr_available=True,
        )
    except ImportError as e:
        return OCRResponse(ok=False, error=str(e), ocr_available=False)
    except Exception as e:
        log.exception("Error OCR desde bytes")
        raise HTTPException(status_code=500, detail=f"Error OCR: {e}")


@router.get("/ocr/status", response_model=OCRResponse)
async def ocr_status():
    """Verifica si Tesseract OCR está disponible en el servidor."""
    try:
        from app.services.ocr_service import ocr_available

        available = ocr_available()
        return OCRResponse(
            ok=available,
            ocr_available=available,
            metadata={"detail": "Tesseract OCR disponible" if available else "Tesseract OCR no instalado"},
        )
    except Exception:
        return OCRResponse(ok=False, ocr_available=False, metadata={"detail": "Error verificando Tesseract"})
