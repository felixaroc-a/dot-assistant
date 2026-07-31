"""Esquemas Pydantic para POST /v1/images/generate."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    count: int | None = Field(default=None, ge=1, le=8)
    aspect_ratio: str | None = "1:1"
    resolution: str | None = "1024x1024"


class GeneratedImageResponse(BaseModel):
    mime_type: str
    data_base64: str
    width: int
    height: int


class ImageGenerateUsageResponse(BaseModel):
    cost_usd: float
    model: str


class ImageGenerateResponse(BaseModel):
    images: list[GeneratedImageResponse]
    prompt_used: str
    count: int
    usage: ImageGenerateUsageResponse
