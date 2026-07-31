"""Firebase Admin SDK con singleton controlado (init una vez al arrancar)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

from app.settings import settings

log = logging.getLogger("dot.firebase_db")

_db: firestore.Client | None = None
FIRESTORE_AVAILABLE = False

# Cache en memoria como fallback cuando Firestore falla (PASO 3)
_profile_cache: dict[str, dict] = {}


def init_firebase() -> None:
    global _db, FIRESTORE_AVAILABLE
    if firebase_admin._apps:
        _db = firestore.client()
        FIRESTORE_AVAILABLE = True
        return
    path = settings.firebase_service_account_path
    if not path.is_file():
        raise FileNotFoundError(
            f"No esta el archivo de cuenta de servicio de Firebase en: {path.resolve()}"
        )
    cred = credentials.Certificate(str(path))
    firebase_admin.initialize_app(cred)
    _db = firestore.client()
    FIRESTORE_AVAILABLE = True


def get_db() -> firestore.Client | None:
    """Retorna cliente Firestore o None si no esta disponible.
    
    NUNCA crashea — los callers deben manejar el caso None.
    """
    if not FIRESTORE_AVAILABLE:
        return None
    if _db is None:
        return None  # Modo offline, no crashear
    return _db


def save_oauth_pending_state(state: str, user_id: str, scopes: list[str]) -> None:
    get_db().collection("oauth_google_pending").document(state).set(
        {
            "user_id": user_id,
            "scopes": scopes,
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )


def take_oauth_pending_state(state: str) -> tuple[str, list[str]] | None:
    ref = get_db().collection("oauth_google_pending").document(state)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    ref.delete()

    created = data.get("created_at")
    if not created:
        return None

    if isinstance(created, datetime):
        dt = created
    else:
        dt = created.to_datetime()  # type: ignore[union-attr]

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    limit = datetime.now(timezone.utc) - timedelta(minutes=settings.oauth_state_ttl_minutes)
    if dt < limit:
        return None

    uid = data.get("user_id")
    if not uid:
        return None
    raw_scopes = data.get("scopes")
    if isinstance(raw_scopes, list) and raw_scopes:
        scopes = [str(s) for s in raw_scopes]
    else:
        scopes = list(settings.scopes)
    return str(uid), scopes


def save_user_google_tokens(user_id: str, ciphertext: str) -> None:
    get_db().collection("user_google_tokens").document(user_id).set(
        {
            "ciphertext": ciphertext,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
    )


def get_user_profile(user_id: str) -> dict | None:
    db = get_db()
    if db is None:
        return _profile_cache.get(user_id)
    try:
        snap = db.collection("users").document(user_id).get()
        if not snap.exists:
            return _profile_cache.get(user_id)
        data = snap.to_dict()
        if data:
            _profile_cache[user_id] = data
        return data
    except Exception:
        log.warning("Firestore fallo al leer perfil %s, usando cache", user_id[:8], exc_info=True)
        return _profile_cache.get(user_id)


def merge_user_profile(user_id: str, data: dict) -> None:
    if not data:
        return
    # Siempre actualizar cache en memoria
    cached = _profile_cache.get(user_id, {})
    cached.update(data)
    _profile_cache[user_id] = cached
    db = get_db()
    if db is None:
        log.info("perfil guardado en cache (modo offline)")
        return
    try:
        payload = {**data, "updated_at": firestore.SERVER_TIMESTAMP}
        db.collection("users").document(user_id).set(payload, merge=True)
    except Exception:
        log.warning("Firestore fallo al escribir perfil %s, datos en cache", user_id[:8], exc_info=True)


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def find_user_id_by_phone(phone_number: str) -> str | None:
    """Busca uid de `users/{uid}` por número de teléfono.

    Prioriza coincidencia exacta en `phone_number` y, si no encuentra, compara
    versiones normalizadas (solo dígitos) como fallback.
    """
    db = get_db()
    raw = (phone_number or "").strip()
    if not raw:
        return None

    normalized = _normalize_phone(raw)
    candidates = [raw]
    if normalized:
        candidates.extend([normalized, f"+{normalized}"])

    # Intento rápido por igualdad exacta (indexable en Firestore).
    for candidate in dict.fromkeys(candidates):
        docs = (
            db.collection("users")
            .where("phone_number", "==", candidate)
            .limit(1)
            .stream()
        )
        doc = next(iter(docs), None)
        if doc is not None:
            return doc.id

    # Fallback: comparar versión normalizada en memoria.
    for doc in db.collection("users").stream():
        data = doc.to_dict() or {}
        stored = str(data.get("phone_number", "")).strip()
        if stored and _normalize_phone(stored) == normalized:
            return doc.id

    return None


def get_user_google_tokens_ciphertext(user_id: str) -> str | None:
    """Obtiene el blob cifrado de tokens OAuth Google para un usuario."""
    snap = get_db().collection("user_google_tokens").document(user_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    value = data.get("ciphertext")
    if not value:
        return None
    return str(value)


def get_user_google_tokens_doc_data(user_id: str) -> dict | None:
    """Obtiene el documento completo de tokens Google OAuth (ciphertext + updated_at)."""
    snap = get_db().collection("user_google_tokens").document(user_id).get()
    if not snap.exists:
        return None
    return snap.to_dict()


def delete_user_google_tokens(user_id: str) -> None:
    """Elimina el documento de tokens Google OAuth de Firestore."""
    get_db().collection("user_google_tokens").document(user_id).delete()


# ─── Memoria atómica (FREE-M02) ────────────────────────────────────────────


def _memory_facts_collection(user_id: str):
    """Subcolección users/{uid}/memory/facts/{fact_id}.

    Firestore exige un documento contenedor antes de la subcolección `facts`;
    usamos `_data` como ancla interna.
    """
    db = get_db()
    if db is None:
        return None
    return (
        db.collection("users")
        .document(user_id)
        .collection("memory")
        .document("_data")
        .collection("facts")
    )


def list_active_memory_facts(user_id: str, limit: int = 200) -> list[dict]:
    """Lista hechos activos en users/{uid}/memory/facts/{fact_id}."""
    col = _memory_facts_collection(user_id)
    if col is None:
        return []
    try:
        facts: list[dict] = []
        for doc in col.where("is_active", "==", True).limit(limit).stream():
            facts.append({"fact_id": doc.id, **(doc.to_dict() or {})})

        def _sort_key(item: dict) -> datetime:
            updated = item.get("updated_at")
            if isinstance(updated, datetime):
                return updated
            if hasattr(updated, "to_datetime"):
                return updated.to_datetime()  # type: ignore[union-attr]
            return datetime.min.replace(tzinfo=timezone.utc)

        facts.sort(key=_sort_key, reverse=True)
        return facts
    except Exception:
        log.warning(
            "Firestore fallo al listar hechos de memoria para uid=%s",
            user_id[:8],
            exc_info=True,
        )
        return []


def find_memory_fact_id_by_key(user_id: str, key: str) -> str | None:
    """Busca fact_id activo por key en users/{uid}/memory/facts/."""
    col = _memory_facts_collection(user_id)
    if col is None or not key:
        return None
    try:
        for doc in col.where("key", "==", key).limit(10).stream():
            data = doc.to_dict() or {}
            if data.get("is_active", True):
                return doc.id
        return None
    except Exception:
        log.warning(
            "Firestore fallo al buscar hecho key=%s uid=%s",
            key,
            user_id[:8],
            exc_info=True,
        )
        return None


def set_memory_fact(user_id: str, fact_id: str, data: dict, merge: bool = False) -> bool:
    """Escribe un hecho en users/{uid}/memory/facts/{fact_id}."""
    col = _memory_facts_collection(user_id)
    if col is None:
        return False
    try:
        col.document(fact_id).set(data, merge=merge)
        return True
    except Exception:
        log.warning(
            "Firestore fallo al escribir hecho %s uid=%s",
            fact_id[:8],
            user_id[:8],
            exc_info=True,
        )
        return False


def deactivate_memory_fact(user_id: str, fact_id: str) -> bool:
    """Marca un hecho como inactivo (delete lógico)."""
    col = _memory_facts_collection(user_id)
    if col is None:
        return False
    try:
        col.document(fact_id).set(
            {
                "is_active": False,
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return True
    except Exception:
        log.warning(
            "Firestore fallo al desactivar hecho %s uid=%s",
            fact_id[:8],
            user_id[:8],
            exc_info=True,
        )
        return False


# ─── Pendrive recovery key backup ────────────────────────────────────────


def save_pendrive_recovery(uid: str, ciphertext: str) -> bool:
    """Guarda la recovery key del vault cifrada con Fernet en Firestore
    y confirma la escritura con reintentos.

    Returns:
        True si el documento se escribio y existe en Firestore.
    Raises:
        RuntimeError: si tras 3 reintentos no se pudo confirmar la escritura.
    """
    db = get_db()
    ref = db.collection("pendrive_recovery").document(uid)
    ref.set(
        {
            "ciphertext": ciphertext,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
    )

    # ── Confirmacion de escritura con backoff exponencial ──
    delays = [0.5, 1.0, 2.0]
    for attempt, delay in enumerate(delays, start=1):
        time.sleep(delay)
        snap = ref.get()
        if snap.exists:
            log.info(
                "Recovery key confirmada en Firestore para uid=%s (intento %d)",
                uid,
                attempt,
            )
            return True
        log.warning(
            "Intento %d: recovery key NO encontrada en Firestore para uid=%s",
            attempt,
            uid,
        )

    log.critical(
        "No se pudo confirmar la escritura de recovery key en Firestore "
        "para uid=%s tras %d reintentos",
        uid,
        len(delays),
    )
    raise RuntimeError(
        f"No se pudo confirmar la escritura de recovery key en Firestore para uid={uid}"
    )


def get_pendrive_recovery(uid: str) -> str | None:
    """Recupera la recovery key cifrada del vault desde Firestore."""
    snap = get_db().collection("pendrive_recovery").document(uid).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    return data.get("ciphertext")


def delete_pendrive_recovery(uid: str) -> None:
    """Elimina el backup de recovery key de Firestore."""
    get_db().collection("pendrive_recovery").document(uid).delete()


# ─── Admin alerts ────────────────────────────────────────────────────────


def save_admin_alert(
    alert_type: str,
    cliente_id: str,
    serial: str | None = None,
    reported_at: str | None = None,
    reason: str | None = None,
) -> str:
    """Crea una alerta en la colección `admin_alerts` de Firestore.

    Retorna el ID del documento creado.
    """
    db = get_db()
    doc_ref = db.collection("admin_alerts").document()
    payload: dict[str, object] = {
        "type": alert_type,
        "cliente_id": cliente_id,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    if serial:
        payload["serial"] = serial
    if reported_at:
        payload["reported_at"] = reported_at
    if reason:
        payload["reason"] = reason
    doc_ref.set(payload)
    log.info(
        "Alerta admin creada: type=%s cliente_id=%s doc_id=%s",
        alert_type,
        cliente_id,
        doc_ref.id,
    )
    return doc_ref.id
