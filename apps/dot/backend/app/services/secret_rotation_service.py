"""Rotación automatizada de secretos de producción.

Rotaciones disponibles:
- JWT: genera nuevo par RS256, actualiza clave activa y rota tras cooldown.
- Fernet: genera nueva clave Fernet, re-encripta todos los tokens OAuth.
- API Keys: cicla claves DeepSeek/OpenAI desde backup configurado.
- Schedule: auto-rota cada 30 días vía CronService.

Cada rotación genera entrada inmutable en audit log de Firestore.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from app.firebase_db import get_db
from app.settings import settings

log = logging.getLogger("dot.secret_rotation")

# ─── Constantes ────────────────────────────────────────────────────

JWT_KEYS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "jwt"
ROTATION_COOLDOWN_MINUTES = 60  # no rotar más de 1 vez por hora
ROTATION_AUDIT_COLLECTION = "secret_rotation_audit"


# ─── Modelos ───────────────────────────────────────────────────────

@dataclass
class RotationRecord:
    """Registro inmutable de rotación en Firestore."""
    rotation_id: str
    secret_type: str  # jwt | fernet | api_keys
    initiator: str    # system | admin_uid
    timestamp: str
    success: bool
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── Helpers ───────────────────────────────────────────────────────

def _generate_rs256_key_pair() -> tuple[str, str]:
    """Genera nuevo par de claves RSA 2048-bit en formato PEM."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    return private_pem, public_pem


def _audit_rotation(record: RotationRecord) -> bool:
    """Persiste registro de rotación en Firestore."""
    db = get_db()
    if db is None:
        log.warning("Firestore no disponible — rotación no auditada: %s", record.secret_type)
        return False

    try:
        from firebase_admin import firestore

        doc_id = record.timestamp.replace(":", "-").replace(".", "-")
        payload = {
            "rotation_id": record.rotation_id,
            "secret_type": record.secret_type,
            "initiator": record.initiator,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "iso_timestamp": record.timestamp,
            "success": record.success,
            "error": record.error,
            "metadata": record.metadata,
        }
        (
            db.collection(ROTATION_AUDIT_COLLECTION)
            .document(doc_id)
            .set(payload)
        )
        log.info("Rotación auditada: %s id=%s ok=%s", record.secret_type, record.rotation_id, record.success)
        return True
    except Exception as e:
        log.error("Error auditando rotación %s: %s", record.secret_type, e)
        return False


def _cooldown_ok() -> bool:
    """Verifica que no se haya rotado en las últimas ROTATION_COOLDOWN_MINUTES."""
    db = get_db()
    if db is None:
        return True  # sin Firestore, permitir (dev/test)

    try:
        from firebase_admin import firestore

        cutoff = datetime.now(timezone.utc).timestamp() - (ROTATION_COOLDOWN_MINUTES * 60)

        docs = (
            db.collection(ROTATION_AUDIT_COLLECTION)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict() or {}
            ts = data.get("timestamp")
            if ts and hasattr(ts, "timestamp"):
                if ts.timestamp() > cutoff:
                    return False
        return True
    except Exception:
        return True  # fail-open en cooldown check (no bloquear rotación manual)


# ─── Servicio ──────────────────────────────────────────────────────

class SecretRotationService:
    """Servicio de rotación automatizada de secretos de producción."""

    def __init__(self) -> None:
        self._last_rotation: dict[str, datetime] = {}
        self._lock = threading.Lock()

    # ── JWT ──────────────────────────────────────────────────────

    def rotate_jwt_keys(self, initiator: str = "system") -> RotationRecord:
        """Genera nuevo par RS256, escribe archivos PEM y recarga claves.

        Las claves activas se escriben en config/jwt/private.pem y public.pem.
        La clave anterior se respalda como .prev.{timestamp}.bak.
        """
        record_id = secrets.token_hex(8)
        now_iso = datetime.now(timezone.utc).isoformat()

        if not _cooldown_ok():
            return RotationRecord(
                rotation_id=record_id,
                secret_type="jwt",
                initiator=initiator,
                timestamp=now_iso,
                success=False,
                error="Cooldown activo — espere al menos %d minutos entre rotaciones" % ROTATION_COOLDOWN_MINUTES,
            )

        try:
            private_pem, public_pem = _generate_rs256_key_pair()

            JWT_KEYS_DIR.mkdir(parents=True, exist_ok=True)

            # Backup de claves existentes
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            for fname in ("private.pem", "public.pem"):
                key_file = JWT_KEYS_DIR / fname
                if key_file.exists():
                    backup_file = JWT_KEYS_DIR / f"{fname}.prev.{ts}.bak"
                    key_file.rename(backup_file)
                    log.info("JWT backup: %s -> %s", fname, backup_file.name)

            # Escribir nuevas claves
            (JWT_KEYS_DIR / "private.pem").write_text(private_pem)
            (JWT_KEYS_DIR / "public.pem").write_text(public_pem)
            (JWT_KEYS_DIR / "private.pem").chmod(0o600)
            (JWT_KEYS_DIR / "public.pem").chmod(0o644)

            # Actualizar variables de entorno para el proceso actual
            os.environ["JWT_PRIVATE_KEY_PEM"] = private_pem
            os.environ["JWT_PUBLIC_KEY_PEM"] = public_pem

            # Invalidar caché de JwtSigningConfig
            from app.jwt_keys import get_jwt_signing_config

            # Forzar recarga invocando get_jwt_signing_config nuevamente
            new_cfg = get_jwt_signing_config()

            with self._lock:
                self._last_rotation["jwt"] = datetime.now(timezone.utc)

            record = RotationRecord(
                rotation_id=record_id,
                secret_type="jwt",
                initiator=initiator,
                timestamp=now_iso,
                success=True,
                metadata={
                    "algorithm": new_cfg.algorithm,
                    "key_size": 2048,
                    "backup_suffix": f".prev.{ts}.bak",
                },
            )
            _audit_rotation(record)
            log.info("JWT keys rotadas exitosamente (id=%s, key_size=2048)", record_id)
            return record

        except Exception as e:
            log.exception("Error rotando JWT keys: %s", e)
            record = RotationRecord(
                rotation_id=record_id,
                secret_type="jwt",
                initiator=initiator,
                timestamp=now_iso,
                success=False,
                error=str(e),
            )
            _audit_rotation(record)
            return record

    # ── Fernet ───────────────────────────────────────────────────

    def rotate_fernet_key(self, initiator: str = "system") -> RotationRecord:
        """Genera nueva clave Fernet y re-encripta todos los tokens OAuth.

        La clave anterior se respalda en la variable de entorno
        TOKEN_ENCRYPTION_KEY_PREV para permitir descifrado durante
        el período de transición.
        """
        record_id = secrets.token_hex(8)
        now_iso = datetime.now(timezone.utc).isoformat()

        if not _cooldown_ok():
            return RotationRecord(
                rotation_id=record_id,
                secret_type="fernet",
                initiator=initiator,
                timestamp=now_iso,
                success=False,
                error="Cooldown activo",
            )

        try:
            old_key = settings.token_encryption_key.strip()
            new_key = Fernet.generate_key().decode()

            # Respaldar clave anterior
            if old_key:
                os.environ["TOKEN_ENCRYPTION_KEY_PREV"] = old_key

            # Re-encriptar tokens OAuth existentes con nueva clave
            reencrypted_count = self._reencrypt_all_oauth_tokens(old_key, new_key)

            # Actualizar clave activa
            os.environ["TOKEN_ENCRYPTION_KEY"] = new_key

            with self._lock:
                self._last_rotation["fernet"] = datetime.now(timezone.utc)

            record = RotationRecord(
                rotation_id=record_id,
                secret_type="fernet",
                initiator=initiator,
                timestamp=now_iso,
                success=True,
                metadata={
                    "tokens_reencrypted": reencrypted_count,
                    "old_key_backed_up": bool(old_key),
                },
            )
            _audit_rotation(record)
            log.info("Fernet key rotada exitosamente — %d tokens re-encriptados", reencrypted_count)
            return record

        except Exception as e:
            log.exception("Error rotando Fernet key: %s", e)
            record = RotationRecord(
                rotation_id=record_id,
                secret_type="fernet",
                initiator=initiator,
                timestamp=now_iso,
                success=False,
                error=str(e),
            )
            _audit_rotation(record)
            return record

    def _reencrypt_all_oauth_tokens(self, old_key: str, new_key: str) -> int:
        """Re-encripta todos los tokens OAuth en Firestore con la nueva clave."""
        if not old_key:
            return 0

        db = get_db()
        if db is None:
            log.warning("Firestore no disponible — saltando re-encriptación de tokens OAuth")
            return 0

        old_fernet = Fernet(old_key.encode())
        new_fernet = Fernet(new_key.encode())
        count = 0

        try:
            docs = db.collection("user_google_tokens").stream()
            for doc in docs:
                data = doc.to_dict()
                if not data:
                    continue
                encrypted = data.get("encrypted_blob")
                if not encrypted:
                    continue
                try:
                    # Descifrar con clave anterior
                    plain = old_fernet.decrypt(encrypted.encode() if isinstance(encrypted, str) else encrypted)
                    # Re-encriptar con nueva clave
                    new_encrypted = new_fernet.encrypt(plain)
                    # Actualizar en Firestore
                    doc.reference.update({"encrypted_blob": new_encrypted.decode()})
                    count += 1
                except Exception:
                    log.debug("No se pudo re-encriptar token %s", doc.id)
                    continue

            log.info("Re-encriptados %d tokens OAuth con nueva Fernet", count)
            return count
        except Exception as e:
            log.error("Error en re-encriptación masiva de tokens: %s", e)
            return count

    # ── API Keys ─────────────────────────────────────────────────

    def rotate_api_keys(self, initiator: str = "system") -> RotationRecord:
        """Cicla claves de API (DeepSeek/OpenAI) usando respaldo configurado.

        Prioridad de respaldo: DEEPSEEK_API_KEY_BACKUP, OPENAI_API_KEY_BACKUP.
        Si no hay backup configurado, solo registra el intento sin rotar.
        """
        record_id = secrets.token_hex(8)
        now_iso = datetime.now(timezone.utc).isoformat()
        rotated: list[str] = []
        errors: list[str] = []

        # DeepSeek
        ds_current = os.environ.get("DEEPSEEK_API_KEY", "")
        ds_backup = os.environ.get("DEEPSEEK_API_KEY_BACKUP", "")
        if ds_backup and ds_backup != ds_current:
            os.environ["DEEPSEEK_API_KEY"] = ds_backup
            os.environ["DEEPSEEK_API_KEY_PREV"] = ds_current
            rotated.append("deepseek")
            log.info("DeepSeek API key rotada")
        else:
            if not ds_backup:
                errors.append("deepseek: sin backup configurado (DEEPSEEK_API_KEY_BACKUP)")

        # OpenAI
        oa_current = os.environ.get("OPENAI_API_KEY", "")
        oa_backup = os.environ.get("OPENAI_API_KEY_BACKUP", "")
        if oa_backup and oa_backup != oa_current:
            os.environ["OPENAI_API_KEY"] = oa_backup
            os.environ["OPENAI_API_KEY_PREV"] = oa_current
            rotated.append("openai")
            log.info("OpenAI API key rotada")
        else:
            if not oa_backup:
                errors.append("openai: sin backup configurado (OPENAI_API_KEY_BACKUP)")

        success = len(rotated) > 0
        record = RotationRecord(
            rotation_id=record_id,
            secret_type="api_keys",
            initiator=initiator,
            timestamp=now_iso,
            success=success,
            error="; ".join(errors) if errors else None,
            metadata={"rotated": rotated, "errors": errors},
        )
        _audit_rotation(record)
        return record

    # ── Schedule ─────────────────────────────────────────────────

    def schedule_rotation(self, cron_service=None) -> None:
        """Programa rotación automática cada 30 días vía CronService.

        Si no se provee cron_service, se registra la intención y el
        caller debe invocar schedule_rotation con el cron_service activo
        desde el lifespan de main.py.
        """
        if cron_service is None:
            log.warning("schedule_rotation llamado sin cron_service — rotación no programada")
            return

        from apscheduler.triggers.interval import IntervalTrigger

        def _auto_rotate_all() -> None:
            log.info("Rotación automática programada iniciando...")
            self.rotate_jwt_keys(initiator="system")
            self.rotate_fernet_key(initiator="system")
            self.rotate_api_keys(initiator="system")

        try:
            cron_service._scheduler.add_job(
                _auto_rotate_all,
                trigger=IntervalTrigger(days=30),
                id="secret_rotation_30d",
                name="Secret Rotation (30d)",
                replace_existing=True,
            )
            log.info("Rotación automática programada cada 30 días")
        except Exception as e:
            log.error("No se pudo programar rotación automática: %s", e)

    # ── Health ───────────────────────────────────────────────────

    def get_rotation_history(self, secret_type: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Recupera historial de rotaciones desde Firestore."""
        db = get_db()
        if db is None:
            return []

        try:
            from firebase_admin import firestore

            query = (
                db.collection(ROTATION_AUDIT_COLLECTION)
                .order_by("timestamp", direction=firestore.Query.DESCENDING)
                .limit(min(limit, 100))
            )

            if secret_type:
                query = query.where("secret_type", "==", secret_type)

            return [doc.to_dict() or {} for doc in query.stream()]
        except Exception as e:
            log.error("Error leyendo historial de rotaciones: %s", e)
            return []


# Singleton global
_secret_rotation_service: SecretRotationService | None = None


def get_secret_rotation_service() -> SecretRotationService:
    global _secret_rotation_service
    if _secret_rotation_service is None:
        _secret_rotation_service = SecretRotationService()
    return _secret_rotation_service
