"""Búsqueda web para DOT usando DuckDuckGo."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx

log = logging.getLogger("dot.web_search")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DOT/1.0"
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
TIMEOUT_SECONDS = 15.0


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = "web"


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult]
    total: int = 0
    error: str | None = None


async def search_web(query: str, max_results: int = 5) -> SearchResponse:
    """
    Busca en la web usando DuckDuckGo Lite API (sin API key requerida).

    Args:
        query: Término de búsqueda
        max_results: Número máximo de resultados (default 5)

    Returns:
        SearchResponse con resultados
    """
    if not query or not query.strip():
        return SearchResponse(query=query, results=[], error="Consulta vacía")

    try:
        url = f"{DDG_LITE_URL}?q={quote_plus(query.strip())}"

        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()

        results = _parse_ddg_lite(resp.text, max_results)

        return SearchResponse(
            query=query,
            results=results,
            total=len(results),
        )

    except httpx.TimeoutException:
        log.warning("Timeout en búsqueda web para: %s", query)
        return SearchResponse(query=query, results=[], error="La búsqueda tardó demasiado. Intenta de nuevo.")
    except httpx.HTTPStatusError as e:
        log.warning("Error HTTP en búsqueda web: %d", e.response.status_code)
        return SearchResponse(query=query, results=[], error=f"Error del servidor de búsqueda ({e.response.status_code}).")
    except Exception as e:
        log.exception("Error inesperado en búsqueda web")
        return SearchResponse(query=query, results=[], error=str(e))


def _parse_ddg_lite(html: str, max_results: int) -> list[SearchResult]:
    """
    Parsea el HTML de DuckDuckGo Lite.

    DDG Lite usa comillas simples o dobles y orden variable de atributos:
    <a href='...' class='result-link'>title</a>
    <td class='result-snippet'>snippet</td>  (a veces <p>)
    """
    results: list[SearchResult] = []

    # href + class=result-link en cualquier orden; ' o "
    link_pattern = re.compile(
        r"<a\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*result-link[^'\"]*['\"])"
        r"[^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    snippet_pattern = re.compile(
        r"<(?:p|td)\b[^>]*\bclass\s*=\s*['\"][^'\"]*result-snippet[^'\"]*['\"][^>]*>(.*?)</(?:p|td)>",
        re.IGNORECASE | re.DOTALL,
    )

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title) in enumerate(links[:max_results]):
        snippet = snippets[i] if i < len(snippets) else ""
        # Limpiar HTML entities / tags residuales
        title = re.sub(r"<[^>]+>", "", title)
        snippet = re.sub(r"<[^>]+>", "", snippet)
        snippet = (
            snippet.replace("&#39;", "'")
            .replace("&quot;", '"')
            .replace("&amp;", "&")
            .replace("&nbsp;", " ")
        )
        href = (url or "").strip()
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://duckduckgo.com" + href
        if not href.startswith("http"):
            continue
        results.append(
            SearchResult(
                title=title.strip(),
                url=href,
                snippet=snippet.strip(),
            )
        )

    return results


def format_search_results(response: SearchResponse) -> str:
    """Formatea resultados de búsqueda para el chat."""
    if response.error:
        return f"Error al buscar: {response.error}"

    if not response.results:
        return f"No encontré resultados para '{response.query}'."

    lines = [
        f"Resultados de búsqueda para «{response.query}»:",
        "---",
    ]

    for i, r in enumerate(response.results, 1):
        lines.append(f"{i}. {r.title}")
        lines.append(f"   {r.snippet}")
        lines.append(f"   Fuente: {r.url}")
        lines.append("")

    return "\n".join(lines)


async def search_and_format(query: str) -> str:
    """Busca y formatea resultados en un solo paso."""
    response = await search_web(query)
    return format_search_results(response)


def search_web_sync(query: str, max_results: int = 5) -> SearchResponse:
    """
    Versión síncrona de search_web para endpoints síncronos.

    Args:
        query: Término de búsqueda
        max_results: Número máximo de resultados (default 5)

    Returns:
        SearchResponse con resultados
    """
    if not query or not query.strip():
        return SearchResponse(query=query, results=[], error="Consulta vacía")

    try:
        url = f"{DDG_LITE_URL}?q={quote_plus(query.strip())}"

        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()

        results = _parse_ddg_lite(resp.text, max_results)

        return SearchResponse(
            query=query,
            results=results,
            total=len(results),
        )

    except httpx.TimeoutException:
        log.warning("Timeout en búsqueda web para: %s", query)
        return SearchResponse(query=query, results=[], error="La búsqueda tardó demasiado. Intenta de nuevo.")
    except httpx.HTTPStatusError as e:
        log.warning("Error HTTP en búsqueda web: %d", e.response.status_code)
        return SearchResponse(query=query, results=[], error=f"Error del servidor de búsqueda ({e.response.status_code}).")
    except Exception as e:
        log.exception("Error inesperado en búsqueda web")
        return SearchResponse(query=query, results=[], error=str(e))


def search_and_format_sync(query: str) -> str:
    """Versión síncrona de search_and_format para endpoints síncronos."""
    response = search_web_sync(query)
    return format_search_results(response)
