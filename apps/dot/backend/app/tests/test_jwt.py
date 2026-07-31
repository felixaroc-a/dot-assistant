"""Tests unitarios de JWT (sin base de datos)."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import jwt as jwt_lib
import pytest
from jwt.exceptions import ExpiredSignatureError, InvalidSignatureError

from app import jwt_util
from app.jwt_keys import JwtSigningConfig, get_jwt_signing_config
from app.refresh_store import clear_memory_families, create_family, rotate_refresh
from app.refresh_store import RefreshTokenReuseError
from app.token_revocation import clear_memory_revocations, is_jti_revoked, revoke_jti

os.environ["DOT_ENV"] = "testing"
os.environ["JWT_SECRET"] = "test-secret-key-at-least-32-bytes-long-for-hs256!!"
os.environ["TOKEN_ENCRYPTION_KEY"] = "ySmbGdhaPWIrdHxlbm4tFcmnvFiXQ4lrEVTN0wOFZIQ="


class TestAccessToken:
    def setup_method(self) -> None:
        clear_memory_revocations()
        clear_memory_families()

    def test_encode_decode_success(self) -> None:
        cfg = get_jwt_signing_config()
        cid = uuid4()
        fv = date.today() + timedelta(days=30)
        token, expires, jti = jwt_util.encode_access_token(
            cliente_id=cid,
            cedula="123",
            correo="test@test.com",
            plan_val="mensual",
            fecha_vencimiento=fv,
            expires_minutes=30,
            cfg=cfg,
        )
        claims = jwt_util.decode_product_token(token, cfg)
        assert claims["sub"] == str(cid)
        assert claims["jti"] == jti
        assert claims["token_use"] == "access"
        assert expires > 0

    def test_expired_token(self) -> None:
        cfg = get_jwt_signing_config()
        cid = uuid4()
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(cid),
            "cedula": "123",
            "token_use": "access",
            "jti": str(uuid4()),
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        }
        token = jwt_lib.encode(payload, cfg.sign_key, algorithm=cfg.algorithm)
        if isinstance(token, bytes):
            token = token.decode("ascii")

        try:
            jwt_util.decode_product_token(token, cfg)
            assert False, "Debio lanzar ExpiredSignatureError"
        except ExpiredSignatureError:
            pass

    def test_invalid_signature(self) -> None:
        cfg = get_jwt_signing_config()
        cid = uuid4()
        token, _, _ = jwt_util.encode_access_token(
            cliente_id=cid,
            cedula="123",
            correo="test@test.com",
            plan_val="mensual",
            fecha_vencimiento=date.today() + timedelta(days=30),
            expires_minutes=30,
            cfg=cfg,
        )
        wrong_cfg = JwtSigningConfig(
            algorithm=cfg.algorithm,
            sign_key="different-secret-key-at-least-32-bytes!!",
            verify_key="different-secret-key-at-least-32-bytes!!",
        )

        try:
            jwt_util.decode_product_token(token, wrong_cfg)
            assert False
        except InvalidSignatureError:
            pass


class TestRefreshToken:
    def setup_method(self) -> None:
        clear_memory_families()

    def test_encode_decode_and_rotate(self) -> None:
        cfg = get_jwt_signing_config()
        cid = uuid4()
        family_id, jti = create_family(str(cid))
        token, expires = jwt_util.encode_refresh_token(
            cliente_id=cid,
            expires_days=30,
            family_id=family_id,
            jti=jti,
            cfg=cfg,
        )
        claims = jwt_util.decode_product_token(token, cfg)
        assert claims["family_id"] == family_id
        assert claims["token_use"] == "refresh"
        assert expires > 0

        new_jti = rotate_refresh(family_id, jti, str(cid))
        assert new_jti != jti

        with pytest.raises(RefreshTokenReuseError):
            rotate_refresh(family_id, jti, str(cid))


class TestRevocation:
    def setup_method(self) -> None:
        clear_memory_revocations()

    def test_revoke_jti(self) -> None:
        jti = str(uuid4())
        assert not is_jti_revoked(jti)
        revoke_jti(jti)
        assert is_jti_revoked(jti)


class TestPasswordUtil:
    def test_hash_and_verify(self) -> None:
        from app.password_util import hash_password, verify_password, is_hashed

        h = hash_password("test123")
        assert is_hashed(h)
        assert verify_password(h, "test123")
        assert not verify_password(h, "wrong")
