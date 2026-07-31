"""Tools Twitter/X API v2 — M2S2-B.

5 tools reales para Twitter usando API v2 gratuita:
  - twitter_post: publicar tweet (OAuth 1.0a)
  - twitter_search: buscar tweets por keyword (Bearer token)
  - twitter_timeline: leer timeline del usuario autenticado (Bearer token)
  - twitter_user_info: obtener info de un perfil (Bearer token)
  - twitter_trends: trending topics (API elevada o fallback trends24.in)

Rate limit: 1 req/seg. Sin API keys → mensaje claro, no alucina.

Variables de entorno:
  TWITTER_BEARER_TOKEN → lectura (search, timeline, user_info, trends)
  TWITTER_API_KEY + TWITTER_API_SECRET → OAuth 1.0a consumer
  TWITTER_ACCESS_TOKEN + TWITTER_ACCESS_SECRET → OAuth 1.0a access (post)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from typing import Any
from urllib.parse import urlencode, quote

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.twitter")

# ──────────────────────────────────────────────
#  Helpers: rate-limit + env
# ──────────────────────────────────────────────

_last_call: dict[str, float] = {}


def _rate_limit(tool: str, min_interval: float = 1.0) -> None:
    """Espera si es necesario para respetar rate limit."""
    now = time.time()
    last = _last_call.get(tool, 0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[tool] = time.time()


def _env(key: str) -> str:
    """Lee variable de entorno, sin default — si no existe, retorna ''."""
    return (os.getenv(key) or "").strip()


# ──────────────────────────────────────────────
#  Helpers: OAuth 1.0a signing (para post)
# ──────────────────────────────────────────────

def _oauth1_signature(
    method: str,
    url: str,
    params: dict[str, str],
    consumer_secret: str,
    access_secret: str,
) -> str:
    """Genera firma OAuth 1.0a HMAC-SHA1."""
    # Ordenar parámetros alfabéticamente (RFC 5849 §3.4.1)
    sorted_params: list[tuple[str, str]] = sorted(
        (k, v) for k, v in params.items() if k not in ("realm",)
    )

    # Construir base string
    param_str = urlencode(sorted_params, safe="", quote_via=quote)
    base_str = (
        method.upper()
        + "&"
        + quote(url, safe="")
        + "&"
        + quote(param_str, safe="")
    )

    # Signing key
    signing_key = (
        quote(consumer_secret, safe="")
        + "&"
        + quote(access_secret, safe="")
    )

    # HMAC-SHA1 → base64
    raw = hmac.new(
        signing_key.encode("utf-8"),
        base_str.encode("utf-8"),
        hashlib.sha1,
    ).digest()

    import base64
    return base64.b64encode(raw).decode("utf-8")


def _oauth1_auth_header(
    method: str,
    url: str,
    api_key: str,
    api_secret: str,
    access_token: str,
    access_secret: str,
    extra_oauth: dict[str, str] | None = None,
) -> str:
    """Construye header Authorization OAuth 1.0a."""
    oauth_params: dict[str, str] = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    if extra_oauth:
        oauth_params.update(extra_oauth)

    # La firma se calcula sobre todos los params (oauth + query/body si aplica)
    # Para POST tweet, solo params oauth
    signature = _oauth1_signature(
        method, url, oauth_params, api_secret, access_secret
    )
    oauth_params["oauth_signature"] = signature

    # Construir header
    header_parts = []
    for k, v in sorted(oauth_params.items()):
        header_parts.append(f'{quote(k, safe="")}="{quote(v, safe="")}"')
    return "OAuth " + ", ".join(header_parts)


def _check_bearer() -> str | None:
    """Retorna Bearer token o mensaje de error si no configurado."""
    token = _env("TWITTER_BEARER_TOKEN")
    if not token:
        return (
            "Twitter API no configurada. Solicita al usuario que configure "
            "TWITTER_BEARER_TOKEN en Ajustes (gratis en developer.twitter.com)."
        )
    return None


def _check_oauth1() -> str | None:
    """Retorna mensaje de error si OAuth 1.0a no configurado."""
    missing = []
    for k in ("TWITTER_API_KEY", "TWITTER_API_SECRET",
              "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET"):
        if not _env(k):
            missing.append(k)
    if missing:
        return (
            "Twitter API OAuth 1.0a no configurada. Faltan: "
            + ", ".join(missing)
            + ". Solicita al usuario que complete la configuración en Ajustes "
            "(gratis en developer.twitter.com)."
        )
    return None


# ──────────────────────────────────────────────
#  1. twitter_post — Publicar tweet
# ──────────────────────────────────────────────

def twitter_post_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Publica un tweet en Twitter/X usando API v2. Máximo 280 caracteres."""
    try:
        text = str(arguments.get("text") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="Falta texto del tweet.")

        if len(text) > 280:
            return ToolResult(
                ok=False, output="",
                error=f"El tweet excede 280 caracteres ({len(text)}/280). Acorta el texto.",
            )

        err_oauth = _check_oauth1()
        if err_oauth:
            return ToolResult(ok=False, output="", error=err_oauth)

        api_key = _env("TWITTER_API_KEY")
        api_secret = _env("TWITTER_API_SECRET")
        access_token = _env("TWITTER_ACCESS_TOKEN")
        access_secret = _env("TWITTER_ACCESS_SECRET")

        _rate_limit("twitter_post")
        url = "https://api.twitter.com/2/tweets"

        # Construir OAuth 1.0a header
        auth_header = _oauth1_auth_header(
            "POST", url,
            api_key, api_secret,
            access_token, access_secret,
        )

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                url,
                json={"text": text},
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code == 201:
                data = resp.json()
                tweet_id = data.get("data", {}).get("id", "?")
                return ToolResult(
                    ok=True,
                    output=(
                        f"🐦 Tweet publicado con exito.\n"
                        f"ID: {tweet_id}\n"
                        f"Texto: {text[:100]}{'...' if len(text) > 100 else ''}\n"
                        f"Fuente: Twitter API v2"
                    ),
                )
            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="Autenticación OAuth 1.0a rechazada. Verifica TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN y TWITTER_ACCESS_SECRET.",
                )
            elif resp.status_code == 403:
                err_text = ""
                try:
                    err_data = resp.json()
                    err_text = str(err_data.get("detail", err_data.get("title", "")))
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Twitter rechazó la publicación (403). {err_text}. Verifica permisos de la app en developer.twitter.com.",
                )
            elif resp.status_code == 429:
                return ToolResult(
                    ok=False, output="",
                    error="Rate limit excedido en Twitter API. Espera unos minutos antes de publicar otro tweet (límite gratuito: 1500 tweets/mes).",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al publicar tweet ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al publicar tweet: {e}")
    except Exception as e:
        log.exception("twitter_post uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  2. twitter_search — Buscar tweets por keyword
# ──────────────────────────────────────────────

def twitter_search_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca tweets recientes por palabra clave usando Twitter API v2."""
    try:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, output="", error="Falta query de busqueda.")

        err_bearer = _check_bearer()
        if err_bearer:
            return ToolResult(ok=False, output="", error=err_bearer)

        bearer = _env("TWITTER_BEARER_TOKEN")
        max_results = min(int(arguments.get("limit") or 10), 100)

        _rate_limit("twitter_search")
        url = "https://api.twitter.com/2/tweets/search/recent"
        params: dict[str, str | int] = {
            "query": query,
            "max_results": max_results,
            "tweet.fields": "created_at,author_id,public_metrics",
            "user.fields": "name,username",
            "expansions": "author_id",
        }

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {bearer}"},
            )

            if resp.status_code == 200:
                data = resp.json()
                tweets = data.get("data") or []
                users = {
                    u["id"]: u
                    for u in (data.get("includes", {}).get("users") or [])
                }

                if not tweets:
                    return ToolResult(
                        ok=True,
                        output=f"🔍 No se encontraron tweets recientes para '{query}'.",
                    )

                lines = [f"🔍 Tweets sobre '{query}' ({len(tweets)} resultados):\n"]
                for i, t in enumerate(tweets[:10], 1):
                    text = (t.get("text") or "")[:150]
                    author_id = t.get("author_id", "")
                    user = users.get(author_id, {})
                    author_name = user.get("name", "?")
                    username = user.get("username", "?")
                    created = (t.get("created_at") or "")[:19]
                    metrics = t.get("public_metrics", {})
                    likes = metrics.get("like_count", 0)
                    rts = metrics.get("retweet_count", 0)

                    lines.append(
                        f"{i}. @{username} ({author_name}) — {created}\n"
                        f"   {text}\n"
                        f"   ❤ {likes}  🔁 {rts}"
                    )

                return ToolResult(
                    ok=True,
                    output="\n".join(lines) + "\n\nFuente: Twitter API v2",
                )

            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="TWITTER_BEARER_TOKEN invalido. Verifica en developer.twitter.com.",
                )
            elif resp.status_code == 429:
                return ToolResult(
                    ok=False, output="",
                    error="Rate limit excedido en Twitter API. Espera unos minutos.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al buscar tweets ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("twitter_search uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  3. twitter_timeline — Leer timeline del usuario
# ──────────────────────────────────────────────

def twitter_timeline_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee el timeline del usuario autenticado en Twitter usando API v2."""
    try:
        err_bearer = _check_bearer()
        if err_bearer:
            return ToolResult(ok=False, output="", error=err_bearer)

        bearer = _env("TWITTER_BEARER_TOKEN")
        max_results = min(int(arguments.get("limit") or 10), 100)

        # Paso 1: obtener el user ID del token (GET /2/users/me)
        _rate_limit("twitter_timeline_me")
        with httpx.Client(timeout=15) as client:
            me_resp = client.get(
                "https://api.twitter.com/2/users/me",
                headers={"Authorization": f"Bearer {bearer}"},
            )
            if me_resp.status_code != 200:
                err_body = ""
                try:
                    err_body = me_resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"No se pudo obtener el usuario autenticado ({me_resp.status_code}). Verifica TWITTER_BEARER_TOKEN. {err_body}",
                )
            me_data = me_resp.json().get("data", {})
            user_id = me_data.get("id", "")
            username = me_data.get("username", "?")

        # Paso 2: leer tweets del usuario
        _rate_limit("twitter_timeline_tweets")
        url = f"https://api.twitter.com/2/users/{user_id}/tweets"
        params: dict[str, str | int] = {
            "max_results": max_results,
            "tweet.fields": "created_at,public_metrics",
            "exclude": "retweets,replies",
        }

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {bearer}"},
            )

            if resp.status_code == 200:
                data = resp.json()
                tweets = data.get("data") or []

                if not tweets:
                    return ToolResult(
                        ok=True,
                        output=f"🐦 Timeline de @{username}: sin tweets recientes.",
                    )

                lines = [f"🐦 Timeline de @{username} ({len(tweets)} tweets):\n"]
                for i, t in enumerate(tweets[:15], 1):
                    text = (t.get("text") or "")[:200]
                    created = (t.get("created_at") or "")[:19]
                    metrics = t.get("public_metrics", {})
                    likes = metrics.get("like_count", 0)
                    rts = metrics.get("retweet_count", 0)

                    lines.append(
                        f"{i}. {created}\n"
                        f"   {text}\n"
                        f"   ❤ {likes}  🔁 {rts}"
                    )

                return ToolResult(
                    ok=True,
                    output="\n".join(lines) + "\n\nFuente: Twitter API v2",
                )

            elif resp.status_code == 429:
                return ToolResult(
                    ok=False, output="",
                    error="Rate limit excedido en Twitter API. Espera unos minutos.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al leer timeline ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("twitter_timeline uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  4. twitter_user_info — Obtener info de un perfil
# ──────────────────────────────────────────────

def twitter_user_info_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene informacion de un perfil de Twitter por nombre de usuario."""
    try:
        username = str(arguments.get("username") or "").strip().lstrip("@")
        if not username:
            return ToolResult(ok=False, output="", error="Falta username de Twitter.")

        err_bearer = _check_bearer()
        if err_bearer:
            return ToolResult(ok=False, output="", error=err_bearer)

        bearer = _env("TWITTER_BEARER_TOKEN")

        _rate_limit("twitter_user_info")
        url = f"https://api.twitter.com/2/users/by/username/{username}"
        params = {
            "user.fields": "description,public_metrics,verified,created_at,profile_image_url",
        }

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {bearer}"},
            )

            if resp.status_code == 200:
                data = resp.json().get("data", {})
                if not data:
                    return ToolResult(
                        ok=False, output="",
                        error=f"Usuario @{username} no encontrado.",
                    )

                name = data.get("name", "?")
                bio = (data.get("description") or "Sin biografía")[:200]
                verified = "✓ Verificado" if data.get("verified") else "No verificado"
                created = (data.get("created_at") or "?")[:10]
                metrics = data.get("public_metrics", {})
                followers = metrics.get("followers_count", 0)
                following = metrics.get("following_count", 0)
                tweet_count = metrics.get("tweet_count", 0)
                avatar = data.get("profile_image_url", "")

                # Formatear números grandes
                def _fmt(n: int) -> str:
                    if n >= 1_000_000:
                        return f"{n / 1_000_000:.1f}M"
                    if n >= 1_000:
                        return f"{n / 1_000:.1f}K"
                    return str(n)

                return ToolResult(
                    ok=True,
                    output=(
                        f"👤 @{username} — {name}\n"
                        f"{'🖼 ' + avatar if avatar else ''}\n"
                        f"Bio: {bio}\n"
                        f"Estado: {verified}\n"
                        f"Seguidores: {_fmt(followers)} | Siguiendo: {_fmt(following)}\n"
                        f"Tweets: {_fmt(tweet_count)} | Cuenta creada: {created}\n"
                        f"Perfil: https://twitter.com/{username}\n"
                        f"Fuente: Twitter API v2"
                    ),
                )

            elif resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Usuario @{username} no encontrado en Twitter.",
                )
            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="TWITTER_BEARER_TOKEN invalido. Verifica en developer.twitter.com.",
                )
            elif resp.status_code == 429:
                return ToolResult(
                    ok=False, output="",
                    error="Rate limit excedido en Twitter API. Espera unos minutos.",
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
        log.exception("twitter_user_info uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  5. twitter_trends — Trending topics
# ──────────────────────────────────────────────

def twitter_trends_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Muestra los trending topics (tendencias) de Twitter. Usa API si hay acceso elevado, o fallback trends24.in."""
    try:
        country = str(arguments.get("country") or "venezuela").strip().lower()

        bearer = _env("TWITTER_BEARER_TOKEN")

        # Intentar API de trends (requiere Elevated Access)
        if bearer:
            _rate_limit("twitter_trends_api")
            # WOEID 23424982 = Venezuela, 23424977 = USA, etc.
            woeid_map: dict[str, int] = {
                "venezuela": 23424982,
                "colombia": 23424787,
                "españa": 23424950,
                "espana": 23424950,
                "mexico": 23424900,
                "argentina": 23424747,
                "chile": 23424782,
                "peru": 23424919,
                "usa": 23424977,
                "estados unidos": 23424977,
                "global": 1,
            }
            woeid = woeid_map.get(country, 1)

            try:
                with httpx.Client(timeout=15) as client:
                    resp = client.get(
                        f"https://api.twitter.com/1.1/trends/place.json?id={woeid}",
                        headers={"Authorization": f"Bearer {bearer}"},
                    )
                    if resp.status_code == 200:
                        trends_data = resp.json()
                        if trends_data and len(trends_data) > 0:
                            trends_list = (
                                trends_data[0].get("trends") or []
                            )
                            if trends_list:
                                lines = [
                                    f"🔥 Trending Topics — {country.title()} "
                                    f"({len(trends_list)} tendencias):\n"
                                ]
                                for i, t in enumerate(trends_list[:20], 1):
                                    name = t.get("name", "?")
                                    volume = t.get("tweet_volume") or 0
                                    vol_str = (
                                        f" ({_fmt_trend(volume)} tweets)"
                                        if volume
                                        else ""
                                    )
                                    lines.append(f"{i}. {name}{vol_str}")
                                return ToolResult(
                                    ok=True,
                                    output="\n".join(lines)
                                    + "\n\nFuente: Twitter API v1.1",
                                )
            except Exception:
                log.debug("Twitter trends API falló, usando fallback trends24.in")

        # Fallback: scraping básico de trends24.in
        _rate_limit("twitter_trends_fallback")
        return _trends24_fallback(country)

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("twitter_trends uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def _fmt_trend(n: int) -> str:
    """Formatea volumen de tweets para trending topics."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _trends24_fallback(country: str) -> ToolResult:
    """Scraping básico de trends24.in como fallback."""
    try:
        country_map: dict[str, str] = {
            "venezuela": "venezuela",
            "colombia": "colombia",
            "españa": "spain",
            "espana": "spain",
            "mexico": "mexico",
            "argentina": "argentina",
            "chile": "chile",
            "peru": "peru",
            "usa": "united-states",
            "estados unidos": "united-states",
        }
        country_slug = country_map.get(country, "venezuela")
        url = f"https://trends24.in/{country_slug}/"

        with httpx.Client(timeout=20) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
            resp.raise_for_status()
            html = resp.text

        # Extraer trending topics del HTML
        trends = _extract_trends_from_html(html)

        if trends:
            lines = [
                f"🔥 Trending Topics — {country.title()} "
                f"({len(trends)} tendencias, via trends24.in):\n"
            ]
            for i, t in enumerate(trends[:20], 1):
                name = t.get("name", "?")
                count = t.get("count", "")
                count_str = f" ({count})" if count else ""
                lines.append(f"{i}. {name}{count_str}")
            return ToolResult(
                ok=True,
                output="\n".join(lines) + "\n\nFuente: trends24.in (fallback)",
            )
        else:
            return ToolResult(
                ok=True,
                output=(
                    f"🔥 No se pudieron obtener trending topics para {country.title()}.\n"
                    f"No se encontraron datos en trends24.in/{country_slug}.\n"
                    f"Para acceso directo: configura TWITTER_BEARER_TOKEN con Elevated Access "
                    f"en developer.twitter.com."
                ),
            )

    except httpx.HTTPError as e:
        return ToolResult(
            ok=True,
            output=(
                f"🔥 No se pudieron obtener trending topics para {country.title()}.\n"
                f"Error al consultar trends24.in: {e}\n"
                f"Para acceso directo: configura TWITTER_BEARER_TOKEN con Elevated Access "
                f"en developer.twitter.com."
            ),
        )
    except Exception as e:
        log.warning("trends24 fallback error: %s", e)
        return ToolResult(
            ok=True,
            output=(
                f"🔥 Trending topics no disponibles para {country.title()}.\n"
                f"Se requiere acceso elevado a Twitter API (Elevated Access) o "
                f"configurar TWITTER_BEARER_TOKEN con permisos de trends.\n"
                f"Mas info: developer.twitter.com"
            ),
        )


def _extract_trends_from_html(html: str) -> list[dict[str, str]]:
    """Extrae trending topics del HTML de trends24.in usando regex."""
    import re

    trends: list[dict[str, str]] = []

    # Buscar bloques de tarjetas de trend
    # Patrón típico de trends24.in: nombre en tag con clase trend-name o similar
    card_patterns = [
        # trends24.in estructura común
        r'<a[^>]*class="[^"]*trend-card[^"]*"[^>]*>.*?<span[^>]*class="[^"]*trend-name[^"]*"[^>]*>(.*?)</span>.*?<span[^>]*class="[^"]*tweet-count[^"]*"[^>]*>(.*?)</span>',
        r'<a[^>]*href="[^"]*/trend/[^"]*"[^>]*>.*?<span[^>]*>(.*?)</span>.*?<small[^>]*>(.*?)</small>',
        # Fallback más genérico
        r'<li[^>]*>.*?<a[^>]*>(.*?)</a>.*?<span[^>]*class="[^"]*count[^"]*"[^>]*>(.*?)</span>',
    ]

    for pat in card_patterns:
        matches = re.findall(pat, html, re.DOTALL | re.IGNORECASE)
        if matches:
            for name, count in matches:
                name = re.sub(r"<[^>]+>", "", name).strip()
                count = re.sub(r"<[^>]+>", "", count).strip()
                if name and len(name) > 1:
                    trends.append({"name": name, "count": count})
            break

    # Si no encontró con los patrones anteriores, intentar extraer cualquier lista de hashtags/tendencias
    if not trends:
        # Buscar hashtags en el HTML
        hashtag_pattern = r'<a[^>]*href="[^"]*/(?:trend|hashtag)/[^"]*"[^>]*>\s*(#?\w[\w\s]*?)\s*</a>'
        hashtags = re.findall(hashtag_pattern, html, re.IGNORECASE)
        seen: set[str] = set()
        for h in hashtags:
            h = h.strip()
            if h and h not in seen and len(h) > 1:
                seen.add(h)
                trends.append({"name": h, "count": ""})

    return trends


# ──────────────────────────────────────────────
#  TOOLS registry
# ──────────────────────────────────────────────

TOOLS = [
    ("twitter_post", twitter_post_handler),
    ("twitter_search", twitter_search_handler),
    ("twitter_timeline", twitter_timeline_handler),
    ("twitter_user_info", twitter_user_info_handler),
    ("twitter_trends", twitter_trends_handler),
]

# ──────────────────────────────────────────────
#  TOOL_SPECS — esquemas de parámetros
# ──────────────────────────────────────────────

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "twitter_post": {
        "description": "Publica un tweet en Twitter/X. Máximo 280 caracteres. Requiere OAuth 1.0a configurado.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Texto del tweet (máximo 280 caracteres)",
                },
            },
            "required": ["text"],
        },
        "category": "social",
        "capability": "B",
    },
    "twitter_search": {
        "description": "Busca tweets recientes en Twitter/X por palabra clave o hashtag.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Palabra clave o hashtag a buscar (ej: 'inteligencia artificial' o '#AI')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de resultados (default 10, max 100)",
                },
            },
            "required": ["query"],
        },
        "category": "social",
        "capability": "B",
    },
    "twitter_timeline": {
        "description": "Lee los tweets del timeline del usuario autenticado en Twitter/X.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de tweets a leer (default 10, max 100)",
                },
            },
        },
        "category": "social",
        "capability": "B",
    },
    "twitter_user_info": {
        "description": "Obtiene información de un perfil de Twitter/X: nombre, biografía, seguidores, verificación.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "Nombre de usuario de Twitter (con o sin @, ej: 'nordik_ia')",
                },
            },
            "required": ["username"],
        },
        "category": "social",
        "capability": "B",
    },
    "twitter_trends": {
        "description": "Muestra los trending topics (tendencias) de Twitter/X en un país. Usa API si hay acceso elevado, o fallback trends24.in.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "País para ver tendencias (default: 'venezuela'). Ej: colombia, mexico, españa, argentina, chile, peru, usa, global",
                },
            },
        },
        "category": "social",
        "capability": "B",
    },
}
