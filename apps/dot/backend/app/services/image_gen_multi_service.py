"""Enhanced Image Generation — DALL-E 3, Stable Diffusion, Vertex Imagen.

Proveedores:
  - vertex: Vertex AI Imagen (existente, vía google cloud)
  - dalle: DALL-E 3 vía OpenAI API (OPENAI_API_KEY)
  - stable_diffusion: Stable Diffusion vía Replicate API (REPLICATE_API_KEY)

Modos adicionales:
  - image_to_image: modificar imágenes existentes
  - inpainting: rellenar/remover partes de imágenes
  - upscale: mejorar resolución

Autoselección:
  auto → DALL-E 3 > Vertex Imagen > Stable Diffusion
"""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from typing import ClassVar

import httpx
from fastapi import HTTPException

from app.settings import settings

log = logging.getLogger("dot.image_gen.multi")

MAX_PROMPT_CHARS = 4000
IMAGE_GEN_COST_USD = 0.04  # costo base


# ─── Proveedores ────────────────────────────────────────────────────────


class ImageProvider:
    """Proveedor base de generación de imágenes."""

    name: ClassVar[str] = "base"

    async def generate(
        self, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        """Genera imágenes desde texto. Retorna lista de {"mime_type", "data_base64"}."""
        raise NotImplementedError

    async def image_to_image(
        self, image_base64: str, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        """Modifica una imagen existente según el prompt."""
        raise NotImplementedError

    async def inpaint(
        self, image_base64: str, mask_base64: str, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        """Rellena/remueve partes de una imagen usando una máscara."""
        raise NotImplementedError

    async def upscale(
        self, image_base64: str, scale: int = 2, **kwargs
    ) -> dict:
        """Mejora la resolución de una imagen."""
        raise NotImplementedError

    def available(self) -> bool:
        return True

    def supports_image_to_image(self) -> bool:
        return False

    def supports_inpainting(self) -> bool:
        return False

    def supports_upscale(self) -> bool:
        return False


class DalleProvider(ImageProvider):
    """DALL-E 3 vía OpenAI API."""

    name: ClassVar[str] = "dalle"
    OPENAI_URL: ClassVar[str] = "https://api.openai.com/v1"

    def available(self) -> bool:
        return bool((settings.openai_api_key or "").strip())

    def supports_image_to_image(self) -> bool:
        return True

    def supports_inpainting(self) -> bool:
        return True

    async def generate(
        self, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        api_key = (settings.openai_api_key or "").strip()
        if not api_key:
            raise HTTPException(503, detail="OPENAI_API_KEY no configurada")

        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        count = max(1, min(count, 4))
        resolved_size = _resolve_dalle_size(size)

        async with httpx.AsyncClient(timeout=120) as client:
            results = []
            for _ in range(count):
                resp = await client.post(
                    f"{self.OPENAI_URL}/images/generations",
                    json={
                        "model": "dall-e-3",
                        "prompt": sanitized,
                        "n": 1,
                        "size": resolved_size,
                        "response_format": "b64_json",
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 401:
                    raise HTTPException(503, detail="OPENAI_API_KEY inválida")
                if resp.status_code == 429:
                    raise HTTPException(429, detail="Cuota OpenAI agotada")
                if resp.status_code != 200:
                    detail = resp.text[:400]
                    log.error("dalle generate http=%s detail=%s", resp.status_code, detail)
                    raise HTTPException(502, detail="Error en DALL-E 3")

                data = resp.json()
                for img_data in data.get("data", []):
                    b64 = img_data.get("b64_json", "")
                    if b64:
                        results.append({
                            "mime_type": "image/png",
                            "data_base64": b64,
                        })
            if not results:
                raise HTTPException(502, detail="DALL-E no devolvió imágenes")
            return results

    async def image_to_image(
        self, image_base64: str, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        api_key = (settings.openai_api_key or "").strip()
        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        count = max(1, min(count, 4))
        resolved_size = _resolve_dalle_size(size)

        async with httpx.AsyncClient(timeout=120) as client:
            results = []
            for _ in range(count):
                resp = await client.post(
                    f"{self.OPENAI_URL}/images/edits",
                    json={
                        "model": "dall-e-2",
                        "image": image_base64,
                        "prompt": sanitized,
                        "n": 1,
                        "size": resolved_size,
                        "response_format": "b64_json",
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code != 200:
                    detail = resp.text[:400]
                    log.error("dalle image_to_image http=%s detail=%s", resp.status_code, detail)
                    raise HTTPException(502, detail="Error en DALL-E img2img")

                data = resp.json()
                for img_data in data.get("data", []):
                    b64 = img_data.get("b64_json", "")
                    if b64:
                        results.append({
                            "mime_type": "image/png",
                            "data_base64": b64,
                        })
            if not results:
                raise HTTPException(502, detail="DALL-E no devolvió imágenes editadas")
            return results

    async def inpaint(
        self, image_base64: str, mask_base64: str, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        api_key = (settings.openai_api_key or "").strip()
        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        count = max(1, min(count, 4))
        resolved_size = _resolve_dalle_size(size)

        async with httpx.AsyncClient(timeout=120) as client:
            results = []
            for _ in range(count):
                resp = await client.post(
                    f"{self.OPENAI_URL}/images/edits",
                    json={
                        "model": "dall-e-2",
                        "image": image_base64,
                        "mask": mask_base64,
                        "prompt": sanitized,
                        "n": 1,
                        "size": resolved_size,
                        "response_format": "b64_json",
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code != 200:
                    detail = resp.text[:400]
                    log.error("dalle inpaint http=%s detail=%s", resp.status_code, detail)
                    raise HTTPException(502, detail="Error en DALL-E inpainting")

                data = resp.json()
                for img_data in data.get("data", []):
                    b64 = img_data.get("b64_json", "")
                    if b64:
                        results.append({
                            "mime_type": "image/png",
                            "data_base64": b64,
                        })
            return results


class StableDiffusionProvider(ImageProvider):
    """Stable Diffusion vía Replicate API."""

    name: ClassVar[str] = "stable_diffusion"
    REPLICATE_URL: ClassVar[str] = "https://api.replicate.com/v1"

    def available(self) -> bool:
        return bool((settings.replicate_api_key or "").strip())

    def supports_image_to_image(self) -> bool:
        return True

    def supports_inpainting(self) -> bool:
        return True

    def supports_upscale(self) -> bool:
        return True

    async def _poll_replicate(self, client: httpx.AsyncClient, prediction_id: str, api_key: str) -> str:
        """Espera hasta que la predicción de Replicate esté completa y retorna la URL."""
        import asyncio
        for _poll in range(20):
            await asyncio.sleep(2)
            poll_resp = await client.get(
                f"{self.REPLICATE_URL}/predictions/{prediction_id}",
                headers={"Authorization": f"Token {api_key}"},
            )
            if poll_resp.status_code != 200:
                continue
            data = poll_resp.json()
            status = data.get("status", "")
            if status == "succeeded":
                output = data.get("output", [])
                if isinstance(output, list) and output:
                    return output[0] if isinstance(output[0], str) else str(output[0])
                if isinstance(output, str):
                    return output
                return ""
            elif status == "failed":
                log.error("replicate prediction failed: %s", data.get("error", ""))
                return ""
        return ""

    async def _download_image(self, client: httpx.AsyncClient, url: str) -> dict:
        """Descarga imagen y retorna como base64."""
        resp = await client.get(url)
        if resp.status_code != 200:
            raise HTTPException(502, detail="Error descargando imagen de Replicate")
        content_type = resp.headers.get("content-type", "image/png")
        return {
            "mime_type": content_type,
            "data_base64": base64.b64encode(resp.content).decode("ascii"),
        }

    async def generate(
        self, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        api_key = (settings.replicate_api_key or "").strip()
        if not api_key:
            raise HTTPException(503, detail="REPLICATE_API_KEY no configurada")

        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        count = max(1, min(count, 4))
        w, h = _parse_size(size)

        async with httpx.AsyncClient(timeout=300) as client:
            results = []
            for _ in range(count):
                resp = await client.post(
                    f"{self.REPLICATE_URL}/predictions",
                    json={
                        "version": "ac732df83cea7fff18b8472768c88ad041fa750ff7682a21affe81863cbe77e4",
                        "input": {
                            "prompt": sanitized,
                            "width": w,
                            "height": h,
                            "num_outputs": 1,
                            "negative_prompt": kwargs.get("negative_prompt", ""),
                        },
                    },
                    headers={
                        "Authorization": f"Token {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 401:
                    raise HTTPException(503, detail="REPLICATE_API_KEY inválida")
                if resp.status_code == 429:
                    raise HTTPException(429, detail="Cuota Replicate agotada")
                if resp.status_code != 201:
                    detail = resp.text[:400]
                    log.error("replicate generate http=%s detail=%s", resp.status_code, detail)
                    raise HTTPException(502, detail="Error en Replicate")

                data = resp.json()
                pred_id = data.get("id", "")
                if not pred_id:
                    continue

                output_url = await self._poll_replicate(client, pred_id, api_key)
                if output_url:
                    img = await self._download_image(client, output_url)
                    results.append(img)

            if not results:
                raise HTTPException(502, detail="Stable Diffusion no devolvió imágenes")
            return results

    async def image_to_image(
        self, image_base64: str, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        api_key = (settings.replicate_api_key or "").strip()
        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        w, h = _parse_size(size)

        async with httpx.AsyncClient(timeout=300) as client:
            results = []
            for _ in range(count):
                resp = await client.post(
                    f"{self.REPLICATE_URL}/predictions",
                    json={
                        "version": "d21b7a58e8db5b823118093e9f06e38bcefe511e7526e2a4fd9eb8d3961809e1",
                        "input": {
                            "image": f"data:image/png;base64,{image_base64}",
                            "prompt": sanitized,
                            "width": w,
                            "height": h,
                            "num_outputs": 1,
                        },
                    },
                    headers={
                        "Authorization": f"Token {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code != 201:
                    detail = resp.text[:400]
                    log.error("replicate img2img http=%s detail=%s", resp.status_code, detail)
                    raise HTTPException(502, detail="Error en Replicate img2img")

                data = resp.json()
                pred_id = data.get("id", "")
                if not pred_id:
                    continue

                output_url = await self._poll_replicate(client, pred_id, api_key)
                if output_url:
                    img = await self._download_image(client, output_url)
                    results.append(img)

            if not results:
                raise HTTPException(502, detail="Stable Diffusion no devolvió imágenes")
            return results

    async def inpaint(
        self, image_base64: str, mask_base64: str, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        api_key = (settings.replicate_api_key or "").strip()
        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        w, h = _parse_size(size)

        async with httpx.AsyncClient(timeout=300) as client:
            results = []
            for _ in range(count):
                resp = await client.post(
                    f"{self.REPLICATE_URL}/predictions",
                    json={
                        "version": "c11bac58203367d97a3b72c75badcc38257c34de4f60a27acae857dbaba52803",
                        "input": {
                            "image": f"data:image/png;base64,{image_base64}",
                            "mask": f"data:image/png;base64,{mask_base64}",
                            "prompt": sanitized,
                            "width": w,
                            "height": h,
                            "num_outputs": 1,
                        },
                    },
                    headers={
                        "Authorization": f"Token {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code != 201:
                    detail = resp.text[:400]
                    log.error("replicate inpaint http=%s detail=%s", resp.status_code, detail)
                    raise HTTPException(502, detail="Error en Replicate inpainting")

                data = resp.json()
                pred_id = data.get("id", "")
                if not pred_id:
                    continue

                output_url = await self._poll_replicate(client, pred_id, api_key)
                if output_url:
                    img = await self._download_image(client, output_url)
                    results.append(img)

            return results

    async def upscale(
        self, image_base64: str, scale: int = 2, **kwargs
    ) -> dict:
        api_key = (settings.replicate_api_key or "").strip()
        scale = max(2, min(scale, 8))

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.REPLICATE_URL}/predictions",
                json={
                    "version": "42fed1c4974146d4d2414e2be2c5277c7fcf05fcc3a73abf41610695738dd1cb",
                    "input": {
                        "image": f"data:image/png;base64,{image_base64}",
                        "scale": scale,
                    },
                },
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code != 201:
                detail = resp.text[:400]
                log.error("replicate upscale http=%s detail=%s", resp.status_code, detail)
                raise HTTPException(502, detail="Error en Replicate upscale")

            data = resp.json()
            pred_id = data.get("id", "")
            if not pred_id:
                raise HTTPException(502, detail="Replicate no devolvió prediction_id")

            output_url = await self._poll_replicate(client, pred_id, api_key)
            if not output_url:
                raise HTTPException(502, detail="Replicate no completó upscale")

            img = await self._download_image(client, output_url)
            img["scale"] = scale
            return img


class VertexImagenProvider(ImageProvider):
    """Vertex AI Imagen — delega al servicio existente."""

    name: ClassVar[str] = "vertex"

    def available(self) -> bool:
        return bool((settings.google_cloud_project or "").strip())

    async def generate(
        self, prompt: str, count: int, size: str, **kwargs
    ) -> list[dict]:
        from app.services.image_gen_vertex_service import generate_images

        w, h = _parse_size(size)
        aspect_ratio = kwargs.get("aspect_ratio", "1:1")

        images = generate_images(
            prompt,
            count=count,
            aspect_ratio=aspect_ratio,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            model_name=settings.imagen_vertex_model,
            width=w,
            height=h,
        )
        return [
            {"mime_type": img.mime_type, "data_base64": img.data_base64}
            for img in images
        ]


# ─── Utilidades ─────────────────────────────────────────────────────────


def _resolve_dalle_size(size: str) -> str:
    """Resuelve tamaño para DALL-E."""
    mapping = {
        "1024x1024": "1024x1024",
        "1:1": "1024x1024",
        "1792x1024": "1792x1024",
        "16:9": "1792x1024",
        "1024x1792": "1024x1792",
        "9:16": "1024x1792",
    }
    return mapping.get(size.strip().lower() if size else "", "1024x1024")


def _parse_size(size: str) -> tuple[int, int]:
    """Parsea tamaño a (width, height)."""
    s = (size or "1024x1024").strip().lower()
    mapping = {
        "1024x1024": (1024, 1024),
        "1:1": (1024, 1024),
        "512x512": (512, 512),
        "768x768": (768, 768),
        "1792x1024": (1792, 1024),
        "16:9": (1792, 1024),
        "1024x1792": (1024, 1792),
        "9:16": (1024, 1792),
    }
    return mapping.get(s, (1024, 1024))


# ─── Registro de proveedores ─────────────────────────────────────────────


def _get_image_providers() -> list[ImageProvider]:
    """Devuelve proveedores ordenados: DALL-E 3 > Vertex Imagen > Stable Diffusion."""
    providers: list[ImageProvider] = []
    if settings.openai_api_key:
        providers.append(DalleProvider())
    if settings.google_cloud_project:
        providers.append(VertexImagenProvider())
    if settings.replicate_api_key:
        providers.append(StableDiffusionProvider())
    return providers


def image_providers_configured() -> bool:
    """True si al menos un proveedor de imágenes está disponible."""
    return len(_get_image_providers()) > 0


def get_available_image_providers() -> list[dict[str, object]]:
    """Devuelve lista de proveedores con capacidades."""
    result: list[dict[str, object]] = []
    for p in _get_image_providers():
        result.append({
            "name": p.name,
            "available": p.available(),
            "img2img": p.supports_image_to_image(),
            "inpainting": p.supports_inpainting(),
            "upscale": p.supports_upscale(),
        })
    return result


def _resolve_image_provider(provider: str) -> ImageProvider:
    """Resuelve un proveedor por nombre o auto-selecciona."""
    all_providers = _get_image_providers()

    if provider != "auto":
        selected = next((p for p in all_providers if p.name == provider), None)
        if not selected:
            raise HTTPException(400, detail=f"Proveedor '{provider}' no disponible")
        if not selected.available():
            raise HTTPException(503, detail=f"Proveedor '{provider}' no configurado")
        return selected

    available = [p for p in all_providers if p.available()]
    if not available:
        raise HTTPException(
            503,
            detail="Ningún proveedor de imágenes configurado. Configura OPENAI_API_KEY, GOOGLE_CLOUD_PROJECT o REPLICATE_API_KEY.",
        )
    return available[0]


async def generate_images_multi(
    prompt: str,
    count: int = 1,
    size: str = "1024x1024",
    provider: str = "auto",
    **kwargs,
) -> dict:
    """Genera imágenes con el proveedor seleccionado.

    Returns:
        dict con {"images": [...], "count", "provider", "prompt_used"}
    """
    selected = _resolve_image_provider(provider)
    count = max(1, min(count, 4))

    log.info(
        "image generate provider=%s count=%s size=%s",
        selected.name, count, size,
    )

    images = await selected.generate(prompt, count, size, **kwargs)

    return {
        "images": images,
        "count": len(images),
        "provider": selected.name,
        "prompt_used": prompt,
    }


async def generate_image_to_image(
    image_base64: str,
    prompt: str,
    count: int = 1,
    size: str = "1024x1024",
    provider: str = "auto",
    **kwargs,
) -> dict:
    """Modifica una imagen existente según el prompt."""
    selected = _resolve_image_provider(provider)
    if not selected.supports_image_to_image():
        raise HTTPException(400, detail=f"El proveedor '{selected.name}' no soporta image-to-image")

    count = max(1, min(count, 4))

    images = await selected.image_to_image(image_base64, prompt, count, size, **kwargs)

    return {
        "images": images,
        "count": len(images),
        "provider": selected.name,
        "prompt_used": prompt,
    }


async def generate_inpaint(
    image_base64: str,
    mask_base64: str,
    prompt: str,
    count: int = 1,
    size: str = "1024x1024",
    provider: str = "auto",
    **kwargs,
) -> dict:
    """Rellena/remueve partes de una imagen usando máscara."""
    selected = _resolve_image_provider(provider)
    if not selected.supports_inpainting():
        raise HTTPException(400, detail=f"El proveedor '{selected.name}' no soporta inpainting")

    count = max(1, min(count, 4))

    images = await selected.inpaint(image_base64, mask_base64, prompt, count, size, **kwargs)

    return {
        "images": images,
        "count": len(images),
        "provider": selected.name,
        "prompt_used": prompt,
    }


async def generate_upscale(
    image_base64: str,
    scale: int = 2,
    provider: str = "auto",
    **kwargs,
) -> dict:
    """Mejora la resolución de una imagen."""
    selected = _resolve_image_provider(provider)
    if not selected.supports_upscale():
        raise HTTPException(400, detail=f"El proveedor '{selected.name}' no soporta upscale")

    scale = max(2, min(scale, 8))

    result = await selected.upscale(image_base64, scale, **kwargs)

    return {
        "image": result,
        "scale": scale,
        "provider": selected.name,
    }
