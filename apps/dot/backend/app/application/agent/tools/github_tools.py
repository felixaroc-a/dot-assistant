"""Tools GitHub API — M6S4-A.

3 tools reales para GitHub usando API REST v3 gratuita:
  - github_search_repos: buscar repositorios por keyword o lenguaje
  - github_get_user: obtener info de un perfil de GitHub
  - github_get_issues: listar issues abiertos de un repositorio

Auth: GITHUB_TOKEN opcional (Bearer).
  - Sin token: 60 req/h (suficiente para uso casual)
  - Con token: 5000 req/h (gratis en github.com/settings/tokens)
Rate limit: respetamos 2s entre llamadas sin token, 0.5s con token.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.github")

# ──────────────────────────────────────────────
#  Helpers: rate-limit + env
# ──────────────────────────────────────────────

_last_call: dict[str, float] = {}


def _env(key: str) -> str:
    """Lee variable de entorno, sin default — si no existe, retorna ''."""
    return (os.getenv(key) or "").strip()


def _rate_limit(tool: str) -> None:
    """Espera si es necesario para respetar rate limit de GitHub.
    2s sin token (60 req/h), 0.5s con token (5000 req/h)."""
    token = _env("GITHUB_TOKEN")
    min_interval = 0.5 if token else 2.0
    now = time.time()
    last = _last_call.get(tool, 0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[tool] = time.time()


def _auth_headers() -> dict[str, str]:
    """Construye headers de autenticación para GitHub API."""
    headers: dict[str, str] = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Nordik-IA/1.0",
    }
    token = _env("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_rate_info(resp: httpx.Response) -> tuple[int, int]:
    """Extrae info de rate limit de headers de GitHub."""
    remaining = int(resp.headers.get("X-RateLimit-Remaining", "?"))
    limit = int(resp.headers.get("X-RateLimit-Limit", "?"))
    return remaining, limit


# ──────────────────────────────────────────────
#  1. github_search_repos — Buscar repositorios
# ──────────────────────────────────────────────


def github_search_repos_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca repositorios en GitHub por palabra clave, lenguaje o tópico. API gratuita ilimitada."""
    try:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(
                ok=False, output="",
                error="Falta query (término de búsqueda, ej: 'machine learning language:python').",
            )

        language = str(arguments.get("language") or "").strip()
        sort = str(arguments.get("sort") or "stars").strip()
        per_page = min(int(arguments.get("limit") or 10), 30)

        # Construir query compuesta si se especifica lenguaje
        full_query = query
        if language:
            full_query += f" language:{language}"

        _rate_limit("github_search_repos")
        url = "https://api.github.com/search/repositories"

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                params={
                    "q": full_query,
                    "sort": sort,
                    "order": "desc",
                    "per_page": per_page,
                },
                headers=_auth_headers(),
            )

            remaining, limit = _get_rate_info(resp)

            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items") or []
                total_count = data.get("total_count", 0)

                if not items:
                    return ToolResult(
                        ok=True,
                        output=f"🔍 No se encontraron repositorios para '{full_query}'.",
                    )

                lines = [
                    f"🔍 Repositorios para '{full_query}' "
                    f"({per_page} de {total_count:,} resultados, orden: {sort}):\n"
                ]

                for i, repo in enumerate(items, 1):
                    name = repo.get("full_name", "?")
                    desc = (repo.get("description") or "Sin descripción")[:150]
                    stars = repo.get("stargazers_count", 0)
                    forks = repo.get("forks_count", 0)
                    lang = repo.get("language") or "?"
                    license_name = (repo.get("license") or {}).get("spdx_id", "")
                    updated = (repo.get("updated_at") or "")[:10]
                    url_repo = repo.get("html_url", "")

                    lines.append(
                        f"{i}. {name}\n"
                        f"   ⭐ {stars:,} | 🍴 {forks:,} | 📄 {lang}"
                        + (f" | 📜 {license_name}" if license_name else "")
                        + f" | 🕐 {updated}\n"
                        f"   {desc}\n"
                        + (f"   {url_repo}" if url_repo else "")
                    )

                rate_str = f"\n\nLímites API: {remaining}/{limit} requests restantes.\nFuente: GitHub API v3"
                return ToolResult(ok=True, output="\n".join(lines) + rate_str)

            elif resp.status_code == 403 and remaining == 0:
                return ToolResult(
                    ok=False, output="",
                    error="Rate limit de GitHub API excedido. Espera unos minutos o configura GITHUB_TOKEN en Ajustes para 5000 req/h (gratis en github.com/settings/tokens).",
                )
            elif resp.status_code == 422:
                err_body = ""
                try:
                    err_data = resp.json()
                    err_body = err_data.get("message", resp.text[:300])
                except Exception:
                    err_body = resp.text[:300]
                return ToolResult(
                    ok=False, output="",
                    error=f"Búsqueda inválida: {err_body}. Verifica la sintaxis de la query. Ej: 'react language:javascript'.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al buscar repositorios ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("github_search_repos uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  2. github_get_user — Obtener info de un perfil
# ──────────────────────────────────────────────


def github_get_user_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene información de un perfil de GitHub: repos, seguidores, bio y más."""
    try:
        username = str(arguments.get("username") or "").strip()
        if not username:
            return ToolResult(
                ok=False, output="",
                error="Falta username (nombre de usuario de GitHub, ej: 'torvalds').",
            )

        _rate_limit("github_get_user")
        url = f"https://api.github.com/users/{username}"

        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())

            remaining, limit = _get_rate_info(resp)

            if resp.status_code == 200:
                data = resp.json()
                login = data.get("login", "?")
                name = data.get("name") or login
                bio = (data.get("bio") or "Sin biografía")[:200]
                company = data.get("company", "")
                blog = data.get("blog", "")
                location = data.get("location", "")
                email = data.get("email", "")
                avatar = data.get("avatar_url", "")
                repos = data.get("public_repos", 0)
                gists = data.get("public_gists", 0)
                followers = data.get("followers", 0)
                following = data.get("following", 0)
                created = (data.get("created_at") or "")[:10]

                def _fmt(n: int) -> str:
                    if n >= 1_000_000:
                        return f"{n / 1_000_000:.1f}M"
                    if n >= 1_000:
                        return f"{n / 1_000:.1f}K"
                    return str(n)

                output = (
                    f"👤 Perfil GitHub — {login}\n"
                    f"Nombre: {name}\n"
                    + (f"Bio: {bio}\n" if bio else "")
                    + (f"Avatar: {avatar}\n" if avatar else "")
                    + (f"Compañía: {company}\n" if company else "")
                    + (f"Ubicación: {location}\n" if location else "")
                    + (f"Blog: {blog}\n" if blog else "")
                    + (f"Email: {email}\n" if email else "")
                    + f"\n📊 Estadísticas:\n"
                    f"   Repos públicos: {repos}\n"
                    f"   Gists: {gists}\n"
                    f"   Seguidores: {_fmt(followers)} | Siguiendo: {_fmt(following)}\n"
                    f"   Cuenta creada: {created}\n"
                    f"\nPerfil: https://github.com/{login}"
                    + f"\n\nLímites API: {remaining}/{limit} requests restantes."
                    + f"\nFuente: GitHub API v3"
                )
                return ToolResult(ok=True, output=output)

            elif resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Usuario '{username}' no encontrado en GitHub.",
                )
            elif resp.status_code == 403 and remaining == 0:
                return ToolResult(
                    ok=False, output="",
                    error="Rate limit de GitHub API excedido. Espera unos minutos o configura GITHUB_TOKEN en Ajustes para 5000 req/h.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al consultar perfil ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("github_get_user uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  3. github_get_issues — Listar issues de un repo
# ──────────────────────────────────────────────


def github_get_issues_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista los issues abiertos de un repositorio de GitHub."""
    try:
        owner = str(arguments.get("owner") or "").strip()
        repo = str(arguments.get("repo") or "").strip()
        if not owner or not repo:
            return ToolResult(
                ok=False, output="",
                error="Falta owner y/o repo (ej: owner='facebook', repo='react').",
            )

        state = str(arguments.get("state") or "open").strip()
        if state not in ("open", "closed", "all"):
            state = "open"

        per_page = min(int(arguments.get("limit") or 10), 30)
        labels = str(arguments.get("labels") or "").strip()

        _rate_limit("github_get_issues")
        url = f"https://api.github.com/repos/{owner}/{repo}/issues"

        params: dict[str, Any] = {
            "state": state,
            "per_page": per_page,
            "sort": "updated",
            "direction": "desc",
        }
        if labels:
            params["labels"] = labels

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                params=params,
                headers=_auth_headers(),
            )

            remaining, limit = _get_rate_info(resp)

            if resp.status_code == 200:
                issues = resp.json()

                if not issues:
                    return ToolResult(
                        ok=True,
                        output=f"📝 {owner}/{repo}: sin issues {state}.",
                    )

                # Filtrar solo issues (no PRs — aunque GH API los incluye, los PRs tienen pull_request key)
                real_issues = [i for i in issues if "pull_request" not in i]

                lines = [
                    f"📝 Issues de {owner}/{repo} "
                    f"({len(real_issues)} issues {state}):\n"
                ]

                for i, issue in enumerate(real_issues[:15], 1):
                    number = issue.get("number", "?")
                    title = issue.get("title", "?")[:120]
                    user = issue.get("user", {}).get("login", "?")
                    created = (issue.get("created_at") or "")[:10]
                    comments = issue.get("comments", 0)
                    state_icon = "🔴" if issue.get("state") == "open" else "🟢"
                    issue_labels = [
                        lbl.get("name", "") for lbl in (issue.get("labels") or [])
                    ]
                    labels_str = f" [{', '.join(issue_labels[:3])}]" if issue_labels else ""

                    lines.append(
                        f"{i}. {state_icon} #{number} — {title}{labels_str}\n"
                        f"   Autor: {user} | {created} | 💬 {comments}"
                    )

                if len(real_issues) > 15:
                    lines.append(f"\n... y {len(real_issues) - 15} issues más.")

                rate_str = f"\n\nLímites API: {remaining}/{limit} requests restantes.\nFuente: GitHub API v3"
                return ToolResult(ok=True, output="\n".join(lines) + rate_str)

            elif resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Repositorio {owner}/{repo} no encontrado o es privado. Verifica el nombre.",
                )
            elif resp.status_code == 403 and remaining == 0:
                return ToolResult(
                    ok=False, output="",
                    error="Rate limit de GitHub API excedido. Espera unos minutos o configura GITHUB_TOKEN en Ajustes para 5000 req/h.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al listar issues ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("github_get_issues uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  TOOLS registry
# ──────────────────────────────────────────────

TOOLS = [
    ("github_search_repos", github_search_repos_handler),
    ("github_get_user", github_get_user_handler),
    ("github_get_issues", github_get_issues_handler),
]

# ──────────────────────────────────────────────
#  TOOL_SPECS — esquemas de parámetros
# ──────────────────────────────────────────────

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "github_search_repos": {
        "description": "Busca repositorios en GitHub por palabra clave, lenguaje o tópico. API gratuita sin límite de funcionalidad (60 req/h sin token, 5000 req/h con GITHUB_TOKEN).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Término de búsqueda (ej: 'machine learning', 'game engine'). Puede incluir calificadores como 'language:python'.",
                },
                "language": {
                    "type": "string",
                    "description": "Filtrar por lenguaje de programación (ej: 'python', 'javascript', 'rust')",
                },
                "sort": {
                    "type": "string",
                    "description": "Ordenar por: stars, forks, updated (default: stars)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de resultados (default 10, max 30)",
                },
            },
            "required": ["query"],
        },
        "category": "bizdev",
        "capability": "B",
    },
    "github_get_user": {
        "description": "Obtiene información de un perfil de GitHub: nombre, bio, repos, seguidores, empresa, ubicación y más.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "Nombre de usuario de GitHub (ej: 'torvalds', 'kentcdodds')",
                },
            },
            "required": ["username"],
        },
        "category": "bizdev",
        "capability": "B",
    },
    "github_get_issues": {
        "description": "Lista los issues (abiertos, cerrados o todos) de un repositorio de GitHub. No incluye Pull Requests.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dueño del repositorio (ej: 'facebook')",
                },
                "repo": {
                    "type": "string",
                    "description": "Nombre del repositorio (ej: 'react')",
                },
                "state": {
                    "type": "string",
                    "description": "Estado de los issues: open, closed, all (default: open)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de issues a listar (default 10, max 30)",
                },
                "labels": {
                    "type": "string",
                    "description": "Filtrar por etiqueta (ej: 'bug', 'enhancement')",
                },
            },
            "required": ["owner", "repo"],
        },
        "category": "bizdev",
        "capability": "B",
    },
}
