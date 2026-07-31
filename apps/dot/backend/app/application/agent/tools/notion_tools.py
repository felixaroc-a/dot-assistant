"""Tools Notion API — M3S3-A.

5 tools reales para Notion usando API gratuita (Internal Integration):
  - notion_search: buscar páginas y bases de datos
  - notion_create_page: crear página en una base de datos o página padre
  - notion_get_page: obtener contenido de una página por ID
  - notion_get_database: consultar registros de una base de datos
  - notion_update_page: actualizar propiedades de una página

Auth: Bearer token via NOTION_API_KEY. Headers: Notion-Version: 2022-06-28.
Sin token → "requiere configurar NOTION_API_KEY en Ajustes".
Rate limit: 3 req/seg; respetamos 0.5s entre llamadas.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.notion")

# ──────────────────────────────────────────────
#  Helpers: rate-limit + env + headers
# ──────────────────────────────────────────────

_last_call: dict[str, float] = {}


def _rate_limit(tool: str, min_interval: float = 0.5) -> None:
    """Espera si es necesario para respetar rate limit de Notion (3 req/seg)."""
    now = time.time()
    last = _last_call.get(tool, 0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[tool] = time.time()


def _env(key: str) -> str:
    """Lee variable de entorno, sin default — si no existe, retorna ''."""
    return (os.getenv(key) or "").strip()


def _check_token() -> str | None:
    """Retorna mensaje de error si NOTION_API_KEY no configurado."""
    token = _env("NOTION_API_KEY")
    if not token:
        return (
            "Notion API no configurada. Solicita al usuario que configure "
            "NOTION_API_KEY en Ajustes (gratis en notion.so/my-integrations)."
        )
    return None


def _notion_headers(token: str) -> dict[str, str]:
    """Headers estándar para Notion API."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


# ──────────────────────────────────────────────
#  1. notion_search — Buscar en Notion
# ──────────────────────────────────────────────


def notion_search_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca páginas y bases de datos en Notion por texto o filtro."""
    try:
        query = str(arguments.get("query") or "").strip()
        filter_type = str(arguments.get("filter") or "").strip()  # "page" o "database"
        page_size = min(int(arguments.get("limit") or 10), 100)

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("NOTION_API_KEY")

        _rate_limit("notion_search")

        body: dict[str, Any] = {"page_size": page_size}
        if query:
            body["query"] = query
        if filter_type in ("page", "database"):
            body["filter"] = {"value": filter_type, "property": "object"}

        with httpx.Client(timeout=20) as client:
            resp = client.post(
                "https://api.notion.com/v1/search",
                json=body,
                headers=_notion_headers(token),
            )

            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results") or []

                if not results:
                    return ToolResult(
                        ok=True,
                        output="🔍 Notion: sin resultados" + (f" para '{query}'." if query else "."),
                    )

                pages = [r for r in results if r.get("object") == "page"]
                databases = [r for r in results if r.get("object") == "database"]

                lines = [f"🔍 Notion — {len(results)} resultados" + (f" para '{query}'" if query else "") + ":\n"]

                if databases:
                    lines.append(f"📊 Bases de datos ({len(databases)}):")
                    for i, db in enumerate(databases, 1):
                        title_parts = db.get("title", [])
                        db_title = "".join(t.get("plain_text", "") for t in title_parts) or "Sin título"
                        db_id = db.get("id", "?")
                        url = db.get("url", "")
                        lines.append(f"  {i}. 📊 {db_title}\n     ID: {db_id}" + (f"\n     {url}" if url else ""))

                if pages:
                    lines.append(f"\n📄 Páginas ({len(pages)}):")
                    for i, page in enumerate(pages, 1):
                        props = page.get("properties", {})
                        title_prop = props.get("title") or props.get("Name") or props.get("Título") or {}
                        title_parts = title_prop.get("title", [])
                        page_title = "".join(t.get("plain_text", "") for t in title_parts) or "Sin título"
                        page_id = page.get("id", "?")
                        url = page.get("url", "")
                        lines.append(f"  {i}. 📄 {page_title}\n     ID: {page_id}" + (f"\n     {url}" if url else ""))

                return ToolResult(
                    ok=True,
                    output="\n".join(lines) + "\n\nFuente: Notion API",
                )

            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="NOTION_API_KEY inválida. Verifica en notion.so/my-integrations.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al buscar en Notion ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("notion_search uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  2. notion_create_page — Crear página
# ──────────────────────────────────────────────


def notion_create_page_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Crea una página nueva en Notion dentro de una base de datos o como subpágina."""
    try:
        parent_db = str(arguments.get("parent_db") or "").strip()
        parent_page = str(arguments.get("parent_page") or "").strip()
        title = str(arguments.get("title") or "").strip()
        content = str(arguments.get("content") or "").strip()

        if not parent_db and not parent_page:
            return ToolResult(
                ok=False, output="",
                error="Falta parent_db (ID de la base de datos) o parent_page (ID de la página padre).",
            )
        if not title:
            return ToolResult(ok=False, output="", error="Falta title (título de la página).")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("NOTION_API_KEY")

        _rate_limit("notion_create_page")

        # Construir parent
        if parent_db:
            parent: dict[str, Any] = {"type": "database_id", "database_id": parent_db}
        else:
            parent = {"type": "page_id", "page_id": parent_page}

        # Construir propiedades
        # Intentar inferir el nombre de la propiedad "title" o usar "Name" por defecto
        properties: dict[str, Any] = {
            "Name": {
                "title": [
                    {"text": {"content": title}}
                ]
            }
        }

        # Construir children (bloques de contenido) si hay contenido
        children = []
        if content:
            for paragraph in content.split("\n"):
                paragraph = paragraph.strip()
                if paragraph:
                    children.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": paragraph}}
                            ]
                        },
                    })

        body: dict[str, Any] = {
            "parent": parent,
            "properties": properties,
        }
        if children:
            body["children"] = children

        with httpx.Client(timeout=20) as client:
            resp = client.post(
                "https://api.notion.com/v1/pages",
                json=body,
                headers=_notion_headers(token),
            )

            if resp.status_code == 200:
                data = resp.json()
                page_id = data.get("id", "?")
                url = data.get("url", "")

                return ToolResult(
                    ok=True,
                    output=(
                        f"📄 Página creada en Notion.\n"
                        f"Título: {title}\n"
                        f"ID: {page_id}\n"
                        + (f"URL: {url}\n" if url else "")
                        + (f"Bloques de contenido: {len(children)}\n" if children else "")
                        + f"Parent: {'DB ' + parent_db[:12] + '...' if parent_db else 'Página ' + (parent_page[:12] or '?') + '...'}\n"
                        + "Fuente: Notion API"
                    ),
                )
            elif resp.status_code == 400:
                err_body = ""
                try:
                    err_data = resp.json()
                    err_body = err_data.get("message", resp.text[:300])
                except Exception:
                    err_body = resp.text[:300]
                return ToolResult(
                    ok=False, output="",
                    error=f"Notion rechazó la creación (400): {err_body}. "
                          f"Verifica que la integración tenga acceso a la base de datos/página padre "
                          f"(en Notion: Share → Invitar → seleccionar la integración).",
                )
            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="NOTION_API_KEY inválida. Verifica en notion.so/my-integrations.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al crear página ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("notion_create_page uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  3. notion_get_page — Leer página
# ──────────────────────────────────────────────


def notion_get_page_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene el contenido (propiedades y bloques) de una página de Notion por ID."""
    try:
        page_id = str(arguments.get("page_id") or "").strip()
        if not page_id:
            return ToolResult(ok=False, output="", error="Falta page_id (ID de la página de Notion).")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("NOTION_API_KEY")

        # Paso 1: Obtener propiedades de la página
        _rate_limit("notion_get_page_props")
        with httpx.Client(timeout=15) as client:
            headers = _notion_headers(token)

            props_resp = client.get(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=headers,
            )

            if props_resp.status_code != 200:
                if props_resp.status_code == 404:
                    return ToolResult(
                        ok=False, output="",
                        error=f"Página {page_id} no encontrada. Verifica el ID y que la integración tenga acceso.",
                    )
                err_body = ""
                try:
                    err_body = props_resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al obtener página ({props_resp.status_code}): {err_body}",
                )

            page_data = props_resp.json()

            # Extraer título y propiedades
            properties = page_data.get("properties", {})
            title_prop = properties.get("title") or properties.get("Name") or properties.get("Título") or {}
            title_parts = title_prop.get("title", [])
            page_title = "".join(t.get("plain_text", "") for t in title_parts) or "Sin título"

            # Extraer otras propiedades relevantes
            prop_lines: list[str] = []
            for prop_name, prop_data in properties.items():
                if prop_name in ("title", "Name", "Título"):
                    continue
                prop_type = prop_data.get("type", "")
                if prop_type == "rich_text":
                    texts = prop_data.get("rich_text", [])
                    val = "".join(t.get("plain_text", "") for t in texts)
                    if val:
                        prop_lines.append(f"  {prop_name}: {val[:200]}")
                elif prop_type == "select":
                    sel = prop_data.get("select")
                    if sel:
                        prop_lines.append(f"  {prop_name}: {sel.get('name', '?')}")
                elif prop_type == "multi_select":
                    items = prop_data.get("multi_select", [])
                    if items:
                        names = ", ".join(i.get("name", "?") for i in items)
                        prop_lines.append(f"  {prop_name}: {names}")
                elif prop_type == "date":
                    d = prop_data.get("date", {})
                    if d:
                        start = d.get("start", "")
                        end = d.get("end", "")
                        val = start + (f" → {end}" if end else "")
                        prop_lines.append(f"  {prop_name}: {val}")
                elif prop_type == "number":
                    num = prop_data.get("number")
                    if num is not None:
                        prop_lines.append(f"  {prop_name}: {num}")
                elif prop_type == "url":
                    url = prop_data.get("url", "")
                    if url:
                        prop_lines.append(f"  {prop_name}: {url}")
                elif prop_type == "status":
                    s = prop_data.get("status", {})
                    if s:
                        prop_lines.append(f"  {prop_name}: {s.get('name', '?')}")
                elif prop_type == "checkbox":
                    val = "✓" if prop_data.get("checkbox") else "✗"
                    prop_lines.append(f"  {prop_name}: {val}")

            # Paso 2: Obtener bloques de contenido (children)
            _rate_limit("notion_get_page_blocks")
            blocks_resp = client.get(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                params={"page_size": 50},
                headers=headers,
            )

            content_lines: list[str] = []
            if blocks_resp.status_code == 200:
                blocks = blocks_resp.json().get("results") or []
                for block in blocks[:50]:
                    block_type = block.get("type", "")
                    if block_type in ("paragraph", "heading_1", "heading_2", "heading_3",
                                      "bulleted_list_item", "numbered_list_item", "to_do", "quote", "callout"):
                        block_data = block.get(block_type, {})
                        rich_text = block_data.get("rich_text", [])
                        text = "".join(t.get("plain_text", "") for t in rich_text)
                        if text:
                            prefix = {
                                "heading_1": "# ",
                                "heading_2": "## ",
                                "heading_3": "### ",
                                "bulleted_list_item": "• ",
                                "numbered_list_item": "◦ ",
                                "to_do": "☐ ",
                                "quote": "▎",
                                "callout": "💡 ",
                            }.get(block_type, "")
                            content_lines.append(f"{prefix}{text[:500]}")
                    elif block_type == "image":
                        img = block.get("image", {})
                        url = img.get("file", {}).get("url") or img.get("external", {}).get("url", "")
                        if url:
                            content_lines.append(f"🖼 [Imagen: {url[:120]}]")
                    elif block_type == "divider":
                        content_lines.append("---")

            url = page_data.get("url", "")

            output = f"📄 {page_title}\n"
            if url:
                output += f"URL: {url}\n"
            if prop_lines:
                output += "\nPropiedades:\n" + "\n".join(prop_lines) + "\n"
            if content_lines:
                output += f"\nContenido ({len(content_lines)} bloques):\n" + "\n".join(content_lines) + "\n"

            output += "\nFuente: Notion API"

            return ToolResult(ok=True, output=output)

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("notion_get_page uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  4. notion_get_database — Consultar BD
# ──────────────────────────────────────────────


def notion_get_database_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Consulta los registros de una base de datos de Notion con filtros y orden opcionales."""
    try:
        db_id = str(arguments.get("db_id") or "").strip()
        if not db_id:
            return ToolResult(ok=False, output="", error="Falta db_id (ID de la base de datos de Notion).")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("NOTION_API_KEY")
        page_size = min(int(arguments.get("limit") or 10), 100)

        _rate_limit("notion_get_database")

        body: dict[str, Any] = {"page_size": page_size}

        # Soporte para filtros simples: propiedad + valor
        filter_prop = str(arguments.get("filter_property") or "").strip()
        filter_value = str(arguments.get("filter_value") or "").strip()
        if filter_prop and filter_value:
            body["filter"] = {
                "property": filter_prop,
                "rich_text": {"contains": filter_value},
            }

        # Soporte para orden
        sort_prop = str(arguments.get("sort_property") or "").strip()
        if sort_prop:
            sort_dir = str(arguments.get("sort_direction") or "descending").strip()
            body["sorts"] = [{"property": sort_prop, "direction": sort_dir}]

        with httpx.Client(timeout=20) as client:
            headers = _notion_headers(token)

            resp = client.post(
                f"https://api.notion.com/v1/databases/{db_id}/query",
                json=body,
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results") or []

                if not results:
                    return ToolResult(
                        ok=True,
                        output=f"📊 Base de datos {db_id[:12]}...: sin registros encontrados.",
                    )

                lines = [f"📊 Base de datos ({len(results)} registros):\n"]

                for i, page in enumerate(results[:25], 1):
                    props = page.get("properties", {})
                    # Buscar la propiedad "title" o "Name"
                    title_val = "Sin título"
                    for key, prop in props.items():
                        if prop.get("type") == "title":
                            texts = prop.get("title", [])
                            title_val = "".join(t.get("plain_text", "") for t in texts) or "Sin título"
                            break

                    page_id = page.get("id", "?")
                    url = page.get("url", "")

                    # Extraer algunas propiedades relevantes
                    extra = []
                    for key, prop in props.items():
                        ptype = prop.get("type", "")
                        if ptype == "select":
                            sel = prop.get("select")
                            if sel:
                                extra.append(f"{key}: {sel.get('name', '?')}")
                        elif ptype == "status":
                            s = prop.get("status", {})
                            if s:
                                extra.append(f"{key}: {s.get('name', '?')}")
                        elif ptype == "date":
                            d = prop.get("date", {})
                            if d:
                                extra.append(f"{key}: {d.get('start', '?')}")

                    extra_str = " | ".join(extra[:3])
                    lines.append(
                        f"{i}. {title_val}\n"
                        f"   ID: {page_id}"
                        + (f" | {extra_str}" if extra_str else "")
                    )

                if len(results) > 25:
                    lines.append(f"\n... y {len(results) - 25} registros más.")

                return ToolResult(
                    ok=True,
                    output="\n".join(lines) + "\n\nFuente: Notion API",
                )

            elif resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Base de datos {db_id} no encontrada. Verifica el ID y que la integración tenga acceso compartido.",
                )
            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="NOTION_API_KEY inválida. Verifica en notion.so/my-integrations.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al consultar BD ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("notion_get_database uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  5. notion_update_page — Actualizar página
# ──────────────────────────────────────────────


def notion_update_page_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Actualiza las propiedades de una página de Notion (título, select, status, texto, etc.)."""
    try:
        page_id = str(arguments.get("page_id") or "").strip()
        if not page_id:
            return ToolResult(ok=False, output="", error="Falta page_id (ID de la página a actualizar).")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("NOTION_API_KEY")

        # Recoger propiedades a actualizar
        new_title = str(arguments.get("title") or "").strip()
        new_status = str(arguments.get("status") or "").strip()
        new_select = str(arguments.get("select") or "").strip()
        new_text = str(arguments.get("text") or "").strip()

        if not any([new_title, new_status, new_select, new_text]):
            return ToolResult(
                ok=False, output="",
                error="Falta al menos un campo a actualizar: title, status, select o text.",
            )

        _rate_limit("notion_update_page")

        # Primero obtener la página actual para saber los nombres de las propiedades
        with httpx.Client(timeout=20) as client:
            headers = _notion_headers(token)

            get_resp = client.get(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=headers,
            )

            if get_resp.status_code != 200:
                if get_resp.status_code == 404:
                    return ToolResult(
                        ok=False, output="",
                        error=f"Página {page_id} no encontrada o sin acceso.",
                    )
                err_body = ""
                try:
                    err_body = get_resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al obtener página para actualizar ({get_resp.status_code}): {err_body}",
                )

            existing_props = get_resp.json().get("properties", {})

            # Construir propiedades a actualizar
            properties: dict[str, Any] = {}

            # Detectar propiedad "title" existente
            title_key = None
            for key, prop in existing_props.items():
                if prop.get("type") == "title":
                    title_key = key
                    break
            title_key = title_key or "Name"

            if new_title:
                properties[title_key] = {
                    "title": [{"text": {"content": new_title}}]
                }

            # Status: buscar propiedad tipo "status" existente
            if new_status:
                status_key = None
                for key, prop in existing_props.items():
                    if prop.get("type") == "status":
                        status_key = key
                        break
                if status_key:
                    properties[status_key] = {
                        "status": {"name": new_status}
                    }

            # Select: buscar propiedad tipo "select" existente
            if new_select:
                select_key = None
                for key, prop in existing_props.items():
                    if prop.get("type") == "select":
                        select_key = key
                        break
                if select_key:
                    properties[select_key] = {
                        "select": {"name": new_select}
                    }

            # Texto: buscar propiedad tipo "rich_text" existente que no sea title
            if new_text:
                text_key = None
                for key, prop in existing_props.items():
                    if prop.get("type") == "rich_text" and prop.get("type") != "title" and key != title_key:
                        text_key = key
                        break
                if text_key:
                    properties[text_key] = {
                        "rich_text": [{"text": {"content": new_text}}]
                    }
                else:
                    # Si no hay propiedad rich_text, añadir texto como bloque nuevo
                    _rate_limit("notion_append_blocks", min_interval=0.5)
                    append_body = {
                        "children": [
                            {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [
                                        {"type": "text", "text": {"content": new_text}}
                                    ]
                                },
                            }
                        ]
                    }
                    client.patch(
                        f"https://api.notion.com/v1/blocks/{page_id}/children",
                        json=append_body,
                        headers=headers,
                    )

            if not properties:
                return ToolResult(
                    ok=True,
                    output=(
                        f"📝 Página {page_id[:12]}... actualizada.\n"
                        f"Se añadió texto como bloque nuevo.\n"
                        f"Fuente: Notion API"
                    ),
                )

            # Actualizar propiedades
            update_body: dict[str, Any] = {"properties": properties}
            update_resp = client.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                json=update_body,
                headers=headers,
            )

            if update_resp.status_code == 200:
                cambios = []
                if new_title:
                    cambios.append(f"título → '{new_title}'")
                if new_status:
                    cambios.append(f"status → '{new_status}'")
                if new_select:
                    cambios.append(f"select → '{new_select}'")
                if new_text and text_key:
                    cambios.append(f"texto → '{new_text[:50]}...'")

                return ToolResult(
                    ok=True,
                    output=(
                        f"📝 Página actualizada en Notion.\n"
                        f"ID: {page_id}\n"
                        f"Cambios: {', '.join(cambios) if cambios else 'texto añadido como bloque'}\n"
                        f"Fuente: Notion API"
                    ),
                )
            else:
                err_body = ""
                try:
                    err_body = update_resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al actualizar página ({update_resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("notion_update_page uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  TOOLS registry
# ──────────────────────────────────────────────

TOOLS = [
    ("notion_search", notion_search_handler),
    ("notion_create_page", notion_create_page_handler),
    ("notion_get_page", notion_get_page_handler),
    ("notion_get_database", notion_get_database_handler),
    ("notion_update_page", notion_update_page_handler),
]

# ──────────────────────────────────────────────
#  TOOL_SPECS — esquemas de parámetros
# ──────────────────────────────────────────────

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "notion_search": {
        "description": "Busca páginas y bases de datos en Notion por texto. Requiere NOTION_API_KEY.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto a buscar en títulos y contenido de Notion",
                },
                "filter": {
                    "type": "string",
                    "enum": ["page", "database"],
                    "description": "Filtrar solo páginas o solo bases de datos (opcional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de resultados (default 10, max 100)",
                },
            },
        },
        "category": "productivity",
        "capability": "B",
    },
    "notion_create_page": {
        "description": "Crea una página nueva en una base de datos de Notion o como subpágina. Requiere NOTION_API_KEY y que la integración tenga acceso compartido.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "parent_db": {
                    "type": "string",
                    "description": "ID de la base de datos padre (ej: 'abc123...')",
                },
                "parent_page": {
                    "type": "string",
                    "description": "ID de la página padre para crear subpágina (alternativa a parent_db)",
                },
                "title": {
                    "type": "string",
                    "description": "Título de la nueva página",
                },
                "content": {
                    "type": "string",
                    "description": "Contenido de texto para la página (cada línea será un párrafo)",
                },
            },
            "required": ["title"],
        },
        "category": "productivity",
        "capability": "B",
    },
    "notion_get_page": {
        "description": "Obtiene el contenido completo de una página de Notion: propiedades, bloques de texto, imágenes y más. Requiere NOTION_API_KEY.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "ID de la página de Notion a leer (se encuentra en la URL o con notion_search)",
                },
            },
            "required": ["page_id"],
        },
        "category": "productivity",
        "capability": "B",
    },
    "notion_get_database": {
        "description": "Consulta los registros de una base de datos de Notion con filtros y orden. Requiere NOTION_API_KEY.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "db_id": {
                    "type": "string",
                    "description": "ID de la base de datos a consultar (ej: 'abc123...')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de registros (default 10, max 100)",
                },
                "filter_property": {
                    "type": "string",
                    "description": "Nombre de la propiedad para filtrar (ej: 'Status', 'Categoría')",
                },
                "filter_value": {
                    "type": "string",
                    "description": "Valor del filtro (contiene, case-sensitive)",
                },
                "sort_property": {
                    "type": "string",
                    "description": "Propiedad por la cual ordenar (ej: 'Created time', 'Fecha')",
                },
                "sort_direction": {
                    "type": "string",
                    "enum": ["ascending", "descending"],
                    "description": "Dirección del orden (default: descending)",
                },
            },
            "required": ["db_id"],
        },
        "category": "productivity",
        "capability": "B",
    },
    "notion_update_page": {
        "description": "Actualiza propiedades de una página de Notion: título, status, select, texto. Requiere NOTION_API_KEY.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "ID de la página a actualizar",
                },
                "title": {
                    "type": "string",
                    "description": "Nuevo título de la página",
                },
                "status": {
                    "type": "string",
                    "description": "Nuevo valor para la propiedad de tipo Status",
                },
                "select": {
                    "type": "string",
                    "description": "Nuevo valor para la propiedad de tipo Select",
                },
                "text": {
                    "type": "string",
                    "description": "Texto a añadir (si hay propiedad rich_text se actualiza, sino se agrega como bloque)",
                },
            },
            "required": ["page_id"],
        },
        "category": "productivity",
        "capability": "B",
    },
}
