"""Endpoint para lectura y generacion de presentaciones PowerPoint (.pptx).

GET  /v1/documents/read-pptx?path= — lee una presentacion existente.
POST /v1/documents/generate-pptx      — genera una presentacion nueva.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.auth_deps import require_product_jwt
from app.dependencies.limiter import limiter

log = logging.getLogger("dot.pptx")

router = APIRouter(prefix="/v1/documents", tags=["pptx"])


# ─── Schemas ────────────────────────────────────────────────────────────────


class ChartSeries(BaseModel):
    name: str = Field(..., min_length=1)
    values: list[float] = Field(..., min_length=1)


class ChartData(BaseModel):
    type: str = Field(default="bar", description="Tipo: bar, line, pie")
    categories: list[str] = Field(..., min_length=1)
    series: list[ChartSeries] = Field(..., min_length=1)
    title: str | None = Field(default=None)


class SlideData(BaseModel):
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=10000)
    image_urls: list[str] = Field(default=[])
    chart_data: ChartData | None = Field(default=None)
    notes: str = Field(default="", max_length=5000)

    @field_validator("image_urls")
    @classmethod
    def _dedup_image_urls(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class GeneratePptxRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Nombre de la presentacion sin extension")
    slides: list[SlideData] = Field(..., min_length=1, max_length=100, description="Slides de la presentacion")
    template: str = Field(default="default", description="Template (default por ahora)")
    folder: str | None = Field(default=None, description="Subcarpeta opcional en DOT Trabajos")


class ReadPptxSlide(BaseModel):
    title: str
    content: str
    notes: str
    images_count: int


class ReadPptxResponse(BaseModel):
    ok: bool
    filename: str | None = None
    slide_count: int | None = None
    slides: list[ReadPptxSlide] = []
    error: str | None = None


class GeneratePptxResponse(BaseModel):
    ok: bool
    filename: str | None = None
    path: str | None = None
    size_bytes: int | None = None
    slide_count: int | None = None
    error: str | None = None


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/read-pptx", response_model=ReadPptxResponse)
@limiter.limit("20/minute")
def read_pptx_endpoint(
    request: Request,
    path: str = Query(..., description="Ruta local al archivo .pptx"),
    claims: dict = Depends(require_product_jwt),
):
    """Lee una presentacion .pptx y extrae slides con titulo, contenido y notas."""
    try:
        from app.services.pptx_service import read_pptx

        result = read_pptx(path)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Error al leer presentacion."))

        slides = [
            ReadPptxSlide(
                title=s.get("title", ""),
                content=s.get("content", ""),
                notes=s.get("notes", ""),
                images_count=s.get("images_count", 0),
            )
            for s in result.get("slides", [])
        ]

        log.info(
            "PPTX leido: %s (%d slides) por usuario %s",
            result.get("filename"),
            result.get("slide_count"),
            str(claims.get("sub", "?"))[:8],
        )

        return ReadPptxResponse(
            ok=True,
            filename=result.get("filename"),
            slide_count=result.get("slide_count"),
            slides=slides,
        )
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="python-pptx no esta instalado. No se pueden leer presentaciones PPTX.",
        )
    except HTTPException:
        raise
    except Exception:
        log.exception("Error leyendo PPTX")
        raise HTTPException(status_code=500, detail="Error al leer la presentacion.")


@router.post("/generate-pptx", response_model=GeneratePptxResponse)
@limiter.limit("10/minute")
def generate_pptx_endpoint(
    request: Request,
    body: GeneratePptxRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Genera una presentacion .pptx con texto, imagenes y graficos.

    Soporta graficos de barras, lineas y torta desde arrays de datos.
    """
    try:
        from app.services.pptx_service import generate_pptx

        slides_data = []
        for s in body.slides:
            slide_dict: dict = {
                "title": s.title,
                "content": s.content,
                "image_urls": s.image_urls,
                "notes": s.notes,
            }
            if s.chart_data:
                slide_dict["chart_data"] = {
                    "type": s.chart_data.type,
                    "categories": s.chart_data.categories,
                    "series": [{"name": sr.name, "values": sr.values} for sr in s.chart_data.series],
                    "title": s.chart_data.title,
                }
            slides_data.append(slide_dict)

        result = generate_pptx(
            title=body.title,
            slides_data=slides_data,
            template=body.template,
            folder=body.folder,
        )

        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Error al generar presentacion."))

        log.info(
            "PPTX generado: %s (%d bytes, %d slides) por usuario %s",
            result.get("filename"),
            result.get("size_bytes"),
            result.get("slide_count"),
            str(claims.get("sub", "?"))[:8],
        )

        return GeneratePptxResponse(
            ok=True,
            filename=result.get("filename"),
            path=result.get("path"),
            size_bytes=result.get("size_bytes"),
            slide_count=result.get("slide_count"),
        )
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="python-pptx no esta instalado. No se pueden generar presentaciones PPTX.",
        )
    except HTTPException:
        raise
    except Exception:
        log.exception("Error generando PPTX")
        raise HTTPException(status_code=500, detail="Error al generar la presentacion.")
