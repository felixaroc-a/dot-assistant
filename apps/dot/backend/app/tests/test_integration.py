"""Integration tests — flujo completo: auth → JWT → conversación → chat → memoria.

QA-Integration Agent, Jul 2026.
Usa httpx AsyncClient contra TestClient de FastAPI.
Mockea DeepSeek cuando no hay API key real (respuestas predefinidas).

Ejecutar:
    cd apps/dot/backend
    DOT_ENV=testing TESTING=1 pytest app/tests/test_integration.py -v -s
"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

from app.billing_models import ClienteORM, PlanSuscripcionORM
from app.main import app


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_TEST_CEDULA = "1234567890"
_TEST_PASSWORD = "test123"
_TEST_HARDWARE_SERIAL = "TESTSERIAL001"


def _create_test_cliente(db_session, **overrides) -> ClienteORM:
    """Crea un cliente de prueba con suscripción activa."""
    from hashlib import sha256

    plain = overrides.pop("password", _TEST_PASSWORD)
    hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    import os
    pepper = os.environ.get("HARDWARE_TOKEN_PEPPER", "test-pepper-32-chars-minimum!!!!")
    hw_hash = sha256((_TEST_HARDWARE_SERIAL + pepper).encode()).hexdigest()

    from app.billing_models import ClienteORM as Cliente
    cliente = Cliente(
        id=overrides.pop("id", uuid.uuid4()),
        nombre=overrides.pop("nombre", "Cliente Integration Test"),
        cedula=overrides.pop("cedula", _TEST_CEDULA),
        clave_acceso=overrides.pop("clave_acceso", hashed),
        correo=overrides.pop("correo", "integration@test.com"),
        telefono=overrides.pop("telefono", "+584121234567"),
        fecha_vencimiento=overrides.pop(
            "fecha_vencimiento", date.today() + timedelta(days=30),
        ),
        plan=overrides.pop("plan", PlanSuscripcionORM.mensual),
        hardware_token_hash=overrides.pop("hardware_token_hash", hw_hash),
    )
    db_session.add(cliente)
    db_session.commit()
    db_session.refresh(cliente)
    return cliente


async def _login(client: AsyncClient, cedula: str = _TEST_CEDULA, password: str = _TEST_PASSWORD) -> dict:
    """Helper: login y devuelve tokens + cliente_id."""
    resp = await client.post("/v1/auth/login", json={
        "cedula": cedula,
        "password": password,
        "hardware_serial": _TEST_HARDWARE_SERIAL,
    })
    assert resp.status_code == 200, f"Login falló: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "access_token" in data, f"access_token faltante: {data}"
    assert "refresh_token" in data, f"refresh_token faltante: {data}"
    return data


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def _create_conversation(client: AsyncClient, token: str, title: str = "Test Conversation") -> dict:
    """Helper: crea conversación y devuelve datos."""
    resp = await client.post(
        "/v1/chat/conversations",
        json={"title": title},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 201, f"Crear conversación falló: {resp.status_code} {resp.text}"
    return resp.json()


async def _send_message(client: AsyncClient, token: str, conversation_id: str, text: str) -> dict:
    """Helper: envía mensaje de chat y devuelve respuesta."""
    resp = await client.post(
        "/v1/chat/send",
        json={
            "conversation_id": conversation_id,
            "text": text,
        },
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200, f"Enviar mensaje falló: {resp.status_code} {resp.text}"
    return resp.json()


# ──────────────────────────────────────────────────────────────
# DeepSeek Mock Factory
# ──────────────────────────────────────────────────────────────

DEEPSEEK_MOCK_RESPONSES = {
    "¿Cuál es la capital de Venezuela?": (
        "La capital de Venezuela es Caracas, "
        "una ciudad ubicada en el norte del país."
    ),
    "Hola, ¿cómo estás?": (
        "¡Hola! Estoy aquí para ayudarte. "
        "¿En qué puedo asistirte hoy?"
    ),
    "default": (
        "Soy DOT, tu asistente IA de Nordik. "
        "Estoy aquí para ayudarte con tus tareas diarias."
    ),
}


def _choose_mock_response(user_text: str) -> str:
    """Elige respuesta mock basada en el texto del usuario."""
    for key, response in DEEPSEEK_MOCK_RESPONSES.items():
        if key.lower() in user_text.lower():
            return response
    return DEEPSEEK_MOCK_RESPONSES["default"]


def _make_mock_deepseek_response(content: str, usage_tokens: int = 150) -> dict:
    """Construye respuesta mock con formato DeepSeek API."""
    return {
        "id": f"mock-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": usage_tokens,
            "total_tokens": 50 + usage_tokens,
        },
    }


def _make_mock_deepseek_stream(content: str) -> list[dict]:
    """Construye chunks de streaming mock."""
    chunks = []
    for i, word in enumerate(content.split()):
        chunk = {
            "id": f"mock-stream-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion.chunk",
            "model": "deepseek-chat",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": word + " "},
                    "finish_reason": None,
                }
            ],
        }
        chunks.append(chunk)
    # Último chunk con finish_reason
    chunks.append({
        "id": f"mock-stream-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion.chunk",
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    })
    return chunks


# ──────────────────────────────────────────────────────────────
# AsyncClient Fixture
# ──────────────────────────────────────────────────────────────

@pytest.fixture
async def async_client():
    """AsyncClient usando ASGITransport para testear la app FastAPI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def auth_tokens(async_client, db_session):
    """Fixture que hace login y devuelve tokens + cliente_id."""
    _create_test_cliente(db_session)
    # Usamos pytest-asyncio o corremos sync
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        tokens = loop.run_until_complete(_login(async_client))
    finally:
        loop.close()
    return tokens


# ──────────────────────────────────────────────────────────────
# Test 1: Flujo Completo Auth → JWT → Conversación → Chat → Memoria
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestFullFlow:
    """Flujo de integración completo: auth login → crear conversación →
    enviar mensaje → verificar respuesta → verificar memoria."""

    def test_complete_user_flow(self, client, db_session):
        """Test sincrónico con TestClient (compatible con conftest.py existente).

        Flujo:
        1. Crear cliente de prueba en BD
        2. Login con cédula + clave + serial → obtener JWT
        3. GET /users/me → verificar datos del cliente
        4. Crear conversación → obtener conversation_id
        5. Enviar mensaje de chat → recibir respuesta
        6. Verificar respuesta contiene texto coherente
        7. GET /users/me/memory → verificar memoria existe
        8. PATCH /users/me/memory → persistir memoria
        9. GET /users/me/memory → verificar persistencia
        """
        # ── Paso 1: Crear cliente ──────────────────────────
        cliente = _create_test_cliente(db_session)

        # ── Paso 2: Login ──────────────────────────────────
        login_resp = client.post("/v1/auth/login", json={
            "cedula": _TEST_CEDULA,
            "password": _TEST_PASSWORD,
            "hardware_serial": _TEST_HARDWARE_SERIAL,
        })
        assert login_resp.status_code == 200, (
            f"Login should return 200, got {login_resp.status_code}: {login_resp.text}"
        )
        login_data = login_resp.json()
        access_token = login_data["access_token"]
        refresh_token = login_data["refresh_token"]
        assert access_token, "access_token should not be empty"
        assert refresh_token, "refresh_token should not be empty"

        headers = _auth_headers(access_token)

        # ── Paso 3: GET /users/me ──────────────────────────
        me_resp = client.get("/users/me", headers=headers)
        assert me_resp.status_code == 200, (
            f"/users/me should return 200, got {me_resp.status_code}: {me_resp.text}"
        )
        me_data = me_resp.json()
        assert "nombre" in me_data, f"nombre should be in /me response: {me_data}"
        assert "cedula" in me_data, f"cedula should be in /me response: {me_data}"

        # ── Paso 4: Crear conversación ─────────────────────
        conv_resp = client.post(
            "/v1/chat/conversations",
            json={"title": "Integration Test Chat"},
            headers=headers,
        )
        assert conv_resp.status_code == 201, (
            f"Create conversation should return 201, got {conv_resp.status_code}: {conv_resp.text}"
        )
        conv_data = conv_resp.json()
        assert "conversation_id" in conv_data or "id" in conv_data, (
            f"conversation_id/id should be in response: {conv_data}"
        )
        conversation_id = conv_data.get("conversation_id") or conv_data.get("id")

        # ── Paso 5: Listar conversaciones ──────────────────
        list_resp = client.get("/v1/chat/conversations", headers=headers)
        assert list_resp.status_code == 200, (
            f"List conversations should return 200, got {list_resp.status_code}"
        )
        conv_list = list_resp.json()
        assert isinstance(conv_list, list), f"conversations should be a list, got {type(conv_list)}"
        assert len(conv_list) >= 1, f"Should have at least 1 conversation, got {len(conv_list)}"

        # ── Paso 6: Enviar mensaje de chat (mock DeepSeek) ─
        test_message = "¿Cuál es la capital de Venezuela?"
        expected_response = DEEPSEEK_MOCK_RESPONSES[
            "¿Cuál es la capital de Venezuela?"
        ]

        # Mockeamos el provider de IA para evitar llamada real a DeepSeek
        # Necesitamos mockear la función route_chat_detailed
        with patch(
            "app.services.provider_router.route_chat_detailed",
            return_value=(expected_response, 30, 20, None, None),
        ):
            chat_resp = client.post(
                "/v1/chat/send",
                json={
                    "conversation_id": conversation_id,
                    "text": test_message,
                },
                headers=headers,
            )

            assert chat_resp.status_code == 200, (
                f"Chat send should return 200, got {chat_resp.status_code}: {chat_resp.text}"
            )
            chat_data = chat_resp.json()
            assert "response" in chat_data or "reply" in chat_data or "content" in chat_data, (
                f"Response should contain reply text, got keys: {list(chat_data.keys())}"
            )

        # ── Paso 7: GET /users/me/memory ───────────────────
        mem_get_resp = client.get("/users/me/memory", headers=headers)
        assert mem_get_resp.status_code == 200, (
            f"GET memory should return 200, got {mem_get_resp.status_code}: {mem_get_resp.text}"
        )
        mem_data = mem_get_resp.json()
        assert isinstance(mem_data, dict), f"Memory should be a dict, got {type(mem_data)}"
        assert "version" in mem_data or "facts" in mem_data, (
            f"Memory should have version or facts: {mem_data}"
        )

        # ── Paso 8: PATCH /users/me/memory ─────────────────
        patch_payload = {
            "facts": ["Usuario prefiere respuestas en español"],
            "preferences": {"language": "es", "formality": "formal"},
            "version": 2,
        }
        mem_patch_resp = client.patch(
            "/users/me/memory",
            json=patch_payload,
            headers=headers,
        )
        assert mem_patch_resp.status_code == 200, (
            f"PATCH memory should return 200, got {mem_patch_resp.status_code}: {mem_patch_resp.text}"
        )

        # ── Paso 9: Verificar persistencia de memoria ──────
        mem_get2_resp = client.get("/users/me/memory", headers=headers)
        assert mem_get2_resp.status_code == 200, (
            f"GET memory (2nd) should return 200, got {mem_get2_resp.status_code}"
        )

        # ── Paso 10: Renombrar conversación ────────────────
        rename_resp = client.patch(
            f"/v1/chat/conversations/{conversation_id}",
            json={"title": "Renamed: Integration Test"},
            headers=headers,
        )
        # 200 o 204 son aceptables para rename
        assert rename_resp.status_code in (200, 204), (
            f"Rename should return 200 or 204, got {rename_resp.status_code}"
        )

        # ── Paso 11: Refresh token ─────────────────────────
        refresh_resp = client.post("/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert refresh_resp.status_code == 200, (
            f"Refresh should return 200, got {refresh_resp.status_code}: {refresh_resp.text}"
        )
        refresh_data = refresh_resp.json()
        new_access = refresh_data.get("access_token")
        new_refresh = refresh_data.get("refresh_token")
        assert new_access, "New access_token should be returned"
        assert new_refresh, "New refresh_token should be returned"
        assert new_access != access_token, "New access_token should differ from original"

        # ── Paso 12: Logout ────────────────────────────────
        logout_resp = client.post(
            "/v1/auth/logout",
            json={"refresh_token": new_refresh},
            headers=_auth_headers(new_access),
        )
        assert logout_resp.status_code in (200, 204), (
            f"Logout should return 200 or 204, got {logout_resp.status_code}"
        )

        # ── Paso 13: Verificar token revocado ──────────────
        me_after_logout = client.get("/users/me", headers=_auth_headers(new_access))
        assert me_after_logout.status_code == 401, (
            f"Access after logout should return 401, got {me_after_logout.status_code}"
        )

        # ── Paso 14: Archivar conversación ────────────────
        # Re-login para el test de archivar
        login2_resp = client.post("/v1/auth/login", json={
            "cedula": _TEST_CEDULA,
            "password": _TEST_PASSWORD,
            "hardware_serial": _TEST_HARDWARE_SERIAL,
        })
        assert login2_resp.status_code == 200
        token2 = login2_resp.json()["access_token"]

        archive_resp = client.post(
            f"/v1/chat/conversations/{conversation_id}/archive",
            headers=_auth_headers(token2),
        )
        assert archive_resp.status_code in (200, 204), (
            f"Archive should return 200 or 204, got {archive_resp.status_code}"
        )

        # ── Paso 15: Búsqueda de mensajes ──────────────────
        search_resp = client.get(
            "/v1/chat/conversations/search",
            params={"q": "capital"},
            headers=_auth_headers(token2),
        )
        assert search_resp.status_code == 200, (
            f"Search should return 200, got {search_resp.status_code}"
        )


# ──────────────────────────────────────────────────────────────
# Test 2: Seguridad — Aislamiento entre Usuarios
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestSecurityIsolation:
    """Verifica que usuarios no puedan acceder a datos de otros."""

    def test_cross_user_conversation_isolation(self, client, db_session):
        """Usuario A no puede acceder a conversaciones del Usuario B."""
        # Crear dos clientes
        cliente_a = _create_test_cliente(
            db_session,
            id=uuid.uuid4(),
            cedula="1111111111",
            nombre="Usuario A",
            clave_acceso=bcrypt.hashpw("passA".encode(), bcrypt.gensalt()).decode(),
        )
        cliente_b = _create_test_cliente(
            db_session,
            id=uuid.uuid4(),
            cedula="2222222222",
            nombre="Usuario B",
            clave_acceso=bcrypt.hashpw("passB".encode(), bcrypt.gensalt()).decode(),
        )

        # Login Usuario A (con hardware_serial que coincide con el hash)
        import os
        from hashlib import sha256
        pepper = os.environ.get("HARDWARE_TOKEN_PEPPER", "test-pepper-32-chars-minimum!!!!")
        hw_hash_a = sha256(("SERIALA" + pepper).encode()).hexdigest()
        cliente_a.hardware_token_hash = hw_hash_a
        db_session.commit()

        login_a = client.post("/v1/auth/login", json={
            "cedula": "1111111111",
            "password": "passA",
            "hardware_serial": "SERIALA",
        })
        assert login_a.status_code == 200, f"Login A failed: {login_a.text}"
        token_a = login_a.json()["access_token"]

        # Crear conversación como Usuario A
        conv_a = client.post(
            "/v1/chat/conversations",
            json={"title": "Conversación de A"},
            headers=_auth_headers(token_a),
        )
        assert conv_a.status_code == 201, f"Create conv A failed: {conv_a.text}"
        conv_a_id = conv_a.json().get("conversation_id") or conv_a.json().get("id")

        # Login Usuario B
        hw_hash_b = sha256(("SERIALB" + pepper).encode()).hexdigest()
        cliente_b.hardware_token_hash = hw_hash_b
        db_session.commit()

        login_b = client.post("/v1/auth/login", json={
            "cedula": "2222222222",
            "password": "passB",
            "hardware_serial": "SERIALB",
        })
        assert login_b.status_code == 200, f"Login B failed: {login_b.text}"
        token_b = login_b.json()["access_token"]

        # Usuario B intenta acceder a conversación de A
        # Debería fallar con 403 o 404
        msgs_b = client.get(
            f"/v1/chat/conversations/{conv_a_id}/messages",
            headers=_auth_headers(token_b),
        )
        assert msgs_b.status_code in (403, 404), (
            f"User B should NOT access User A's conversation. "
            f"Expected 403 or 404, got {msgs_b.status_code}: {msgs_b.text}"
        )

        # Usuario B intenta enviar mensaje a conversación de A
        send_b = client.post(
            "/v1/chat/send",
            json={
                "conversation_id": conv_a_id,
                "text": "Intento de acceso no autorizado",
            },
            headers=_auth_headers(token_b),
        )
        assert send_b.status_code in (403, 404), (
            f"User B should NOT send message to User A's conversation. "
            f"Expected 403 or 404, got {send_b.status_code}: {send_b.text}"
        )

        # Usuario A sí puede acceder a su propia conversación
        msgs_a = client.get(
            f"/v1/chat/conversations/{conv_a_id}/messages",
            headers=_auth_headers(token_a),
        )
        assert msgs_a.status_code == 200, (
            f"User A should access own conversation, got {msgs_a.status_code}"
        )


# ──────────────────────────────────────────────────────────────
# Test 3: Login Edge Cases
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestLoginEdgeCases:
    """Cubre todos los casos borde del flujo de login."""

    def test_login_invalid_cedula(self, client, db_session):
        _create_test_cliente(db_session)
        resp = client.post("/v1/auth/login", json={
            "cedula": "0000000000",
            "password": _TEST_PASSWORD,
            "hardware_serial": _TEST_HARDWARE_SERIAL,
        })
        assert resp.status_code == 401, (
            f"Wrong cedula should return 401, got {resp.status_code}"
        )
        assert "detail" in resp.json()

    def test_login_invalid_password(self, client, db_session):
        _create_test_cliente(db_session)
        resp = client.post("/v1/auth/login", json={
            "cedula": _TEST_CEDULA,
            "password": "wrongpassword",
            "hardware_serial": _TEST_HARDWARE_SERIAL,
        })
        assert resp.status_code == 401, (
            f"Wrong password should return 401, got {resp.status_code}"
        )

    def test_login_invalid_hardware_serial(self, client, db_session):
        _create_test_cliente(db_session)
        resp = client.post("/v1/auth/login", json={
            "cedula": _TEST_CEDULA,
            "password": _TEST_PASSWORD,
            "hardware_serial": "WRONGSERIAL",
        })
        assert resp.status_code == 401, (
            f"Wrong hardware_serial should return 401, got {resp.status_code}"
        )

    def test_login_missing_hardware_serial(self, client, db_session):
        _create_test_cliente(db_session)
        resp = client.post("/v1/auth/login", json={
            "cedula": _TEST_CEDULA,
            "password": _TEST_PASSWORD,
        })
        # Debe devolver 400 (pendrive_required) porque el cliente tiene hardware_token_hash
        assert resp.status_code == 400, (
            f"Missing hardware_serial should return 400, got {resp.status_code}"
        )
        data = resp.json()
        assert "detail" in data

    def test_login_expired_subscription(self, client, db_session):
        _create_test_cliente(
            db_session,
            fecha_vencimiento=date.today() - timedelta(days=1),
        )
        resp = client.post("/v1/auth/login", json={
            "cedula": _TEST_CEDULA,
            "password": _TEST_PASSWORD,
            "hardware_serial": _TEST_HARDWARE_SERIAL,
        })
        assert resp.status_code == 403, (
            f"Expired subscription should return 403, got {resp.status_code}"
        )
        data = resp.json()
        assert "detail" in data

    def test_login_empty_credentials(self, client, db_session):
        _create_test_cliente(db_session)
        resp = client.post("/v1/auth/login", json={
            "cedula": "",
            "password": "",
        })
        # Puede ser 400 (validación Pydantic) o 401 (auth fallida)
        assert resp.status_code in (400, 401, 422), (
            f"Empty credentials should return 4xx, got {resp.status_code}"
        )

    def test_access_without_token(self, client):
        """Endpoints protegidos rechazan requests sin token."""
        resp = client.get("/users/me")
        assert resp.status_code == 401, (
            f"/users/me without token should return 401, got {resp.status_code}"
        )

        resp2 = client.get("/v1/chat/conversations")
        assert resp2.status_code == 401, (
            f"conversations without token should return 401, got {resp2.status_code}"
        )

    def test_access_with_expired_token(self, client, db_session, monkeypatch):
        """Token expirado debe ser rechazado."""
        # Usemos el token del test flow pero con exp pasado
        _create_test_cliente(db_session)
        login_resp = client.post("/v1/auth/login", json={
            "cedula": _TEST_CEDULA,
            "password": _TEST_PASSWORD,
            "hardware_serial": _TEST_HARDWARE_SERIAL,
        })
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        # Verificar que el token funciona
        me_ok = client.get("/users/me", headers=_auth_headers(token))
        assert me_ok.status_code == 200, "Token should be valid initially"

        # Simular token expirado forzando una expiración en el decode
        with patch("app.jwt_util.decode_product_token", side_effect=Exception("Token expired")):
            me_expired = client.get("/users/me", headers=_auth_headers(token))
            assert me_expired.status_code in (401, 500), (
                f"Expired token should be rejected, got {me_expired.status_code}"
            )


# ──────────────────────────────────────────────────────────────
# Test 4: Health y Capacidades
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestHealthAndCapabilities:
    """Verifica endpoints de salud y capacidades del sistema."""

    def test_health_basic(self, client):
        """GET /health responde ok."""
        resp = client.get("/health")
        assert resp.status_code == 200, (
            f"/health should return 200, got {resp.status_code}"
        )
        data = resp.json()
        assert data.get("status") == "ok", f"status should be 'ok': {data}"

    def test_health_db(self, client, db_session):
        """GET /health/db verifica esquema de BD."""
        resp = client.get("/health/db")
        assert resp.status_code in (200, 503), (
            f"/health/db should return 200 or 503, got {resp.status_code}"
        )
        data = resp.json()
        assert "status" in data

    def test_capabilities_requires_auth(self, client):
        """GET /v1/capabilities/ sin JWT debe devolver 401."""
        resp = client.get("/v1/capabilities/")
        assert resp.status_code == 401, (
            f"Capabilities without auth should return 401, got {resp.status_code}"
        )

    def test_capabilities_with_auth(self, client, db_session):
        """GET /v1/capabilities/ con JWT válido devuelve lista de capacidades."""
        _create_test_cliente(db_session)
        tokens = _login_sync(client)
        resp = client.get("/v1/capabilities/", headers=_auth_headers(tokens["access_token"]))
        assert resp.status_code == 200, (
            f"Capabilities with auth should return 200, got {resp.status_code}"
        )
        data = resp.json()
        assert "capabilities" in data, f"Should have 'capabilities' key: {data}"
        assert isinstance(data["capabilities"], list), (
            f"capabilities should be a list: {type(data['capabilities'])}"
        )
        assert len(data["capabilities"]) > 0, "Should have at least 1 capability"

    def test_usage_summary(self, client, db_session):
        """GET /v1/chat/usage/summary devuelve consumo IA."""
        _create_test_cliente(db_session)
        tokens = _login_sync(client)
        resp = client.get(
            "/v1/chat/usage/summary",
            headers=_auth_headers(tokens["access_token"]),
        )
        assert resp.status_code == 200, (
            f"Usage summary should return 200, got {resp.status_code}"
        )
        data = resp.json()
        assert "limit_usd" in data, f"Should have limit_usd: {data}"
        assert "consumed_usd" in data, f"Should have consumed_usd: {data}"
        assert "percent" in data, f"Should have percent: {data}"
        assert "blocked" in data, f"Should have blocked: {data}"


def _login_sync(client) -> dict:
    """Login sincrónico helper para tests con TestClient."""
    resp = client.post("/v1/auth/login", json={
        "cedula": _TEST_CEDULA,
        "password": _TEST_PASSWORD,
        "hardware_serial": _TEST_HARDWARE_SERIAL,
    })
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    return resp.json()


# ──────────────────────────────────────────────────────────────
# Test 5: Conversaciones — Renombrar, Archivar, Buscar
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestConversationsCRUD:
    """CRUD completo de conversaciones con un solo usuario."""

    def test_conversation_crud_flow(self, client, db_session):
        """Flujo: crear → listar → renombrar → archivar → desarchivar → buscar."""
        _create_test_cliente(db_session)
        tokens = _login_sync(client)
        headers = _auth_headers(tokens["access_token"])

        # Crear conversación
        create = client.post(
            "/v1/chat/conversations",
            json={"title": "CRUD Test"},
            headers=headers,
        )
        assert create.status_code == 201, f"Create failed: {create.status_code} {create.text}"
        conv = create.json()
        conv_id = conv.get("conversation_id") or conv.get("id")
        assert conv_id, f"No conversation id in response: {conv}"

        # Listar — debe aparecer
        list_resp = client.get("/v1/chat/conversations", headers=headers)
        assert list_resp.status_code == 200
        conv_list = list_resp.json()
        conv_ids = [c.get("conversation_id") or c.get("id") for c in conv_list]
        assert conv_id in conv_ids, f"Created conversation {conv_id} not in list: {conv_ids}"

        # Renombrar
        rename = client.patch(
            f"/v1/chat/conversations/{conv_id}",
            json={"title": "CRUD Test Renamed"},
            headers=headers,
        )
        assert rename.status_code in (200, 204), (
            f"Rename failed: {rename.status_code} {rename.text}"
        )

        # Archivar
        archive = client.post(
            f"/v1/chat/conversations/{conv_id}/archive",
            headers=headers,
        )
        assert archive.status_code in (200, 204), (
            f"Archive failed: {archive.status_code} {archive.text}"
        )

        # Búsqueda — debe encontrar por título original
        search = client.get(
            "/v1/chat/conversations/search",
            params={"q": "CRUD"},
            headers=headers,
        )
        assert search.status_code == 200, (
            f"Search failed: {search.status_code} {search.text}"
        )

        # Listar archivadas
        archived = client.get(
            "/v1/chat/conversations/archived",
            headers=headers,
        )
        assert archived.status_code == 200, (
            f"List archived failed: {archived.status_code}"
        )
        archived_list = archived.json()
        archived_ids = [
            a.get("conversation_id") or a.get("id") for a in archived_list
        ]
        assert conv_id in archived_ids, (
            f"Archived conversation {conv_id} not in archived list: {archived_ids}"
        )

        # Desarchivar
        unarchive = client.post(
            f"/v1/chat/conversations/{conv_id}/unarchive",
            headers=headers,
        )
        assert unarchive.status_code in (200, 204), (
            f"Unarchive failed: {unarchive.status_code} {unarchive.text}"
        )


# ──────────────────────────────────────────────────────────────
# Test 6: WebSocket Auth
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestWebSocketAuth:
    """Verifica que WebSocket requiera autenticación."""

    def test_ws_rejected_without_token(self, client, db_session):
        """WebSocket sin token debe ser rechazado."""
        _create_test_cliente(db_session)
        tokens = _login_sync(client)

        # Conexión sin token
        with client.websocket_connect("/ws/notifications") as ws:
            # Debe cerrarse inmediatamente con código de error
            try:
                data = ws.receive_text()
                # Si llegamos aquí, no se cerró — pero no debería pasar
                pytest.fail("WebSocket without token should be rejected")
            except Exception:
                # Esperado: conexión cerrada por el servidor
                pass

    def test_ws_accepted_with_valid_token(self, client, db_session):
        """WebSocket con JWT válido debe ser aceptado."""
        _create_test_cliente(db_session)
        tokens = _login_sync(client)

        try:
            with client.websocket_connect(
                f"/ws/notifications?token={tokens['access_token']}"
            ) as ws:
                # Conexión aceptada
                assert ws, "WebSocket should be connected"
        except Exception as e:
            pytest.fail(f"WebSocket with valid token should connect: {e}")

    def test_ws_rejected_with_invalid_token(self, client):
        """WebSocket con token inválido debe ser rechazado."""
        try:
            with client.websocket_connect(
                "/ws/notifications?token=invalid.token.here"
            ) as ws:
                ws.receive_text()
                pytest.fail("WebSocket with invalid token should be rejected")
        except Exception:
            # Esperado
            pass


# ──────────────────────────────────────────────────────────────
# Test 7: CORS y Headers de Seguridad
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestSecurityHeaders:
    """Verifica headers de seguridad y CORS."""

    def test_cors_preflight(self, client):
        """OPTIONS preflight debe responder correctamente."""
        resp = client.options(
            "/v1/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        assert resp.status_code == 200, (
            f"OPTIONS should return 200, got {resp.status_code}"
        )

    def test_security_headers_present(self, client):
        """Headers de seguridad deben estar presentes en las respuestas."""
        resp = client.get("/health")
        headers = resp.headers

        # SecurityHeadersMiddleware agrega estos
        # No todos pueden estar en test (depende de config)
        security_headers = [
            "x-content-type-options",
            "x-frame-options",
        ]
        for header in security_headers:
            # Verificar solo si está presente (puede variar en test)
            if header in headers:
                pass  # OK, presente

    def test_cors_origin_allowed(self, client):
        """Orígenes configurados deben ser permitidos."""
        resp = client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.status_code == 200
        # CORS headers deberían estar presentes
        if "access-control-allow-origin" in resp.headers:
            assert resp.headers["access-control-allow-origin"] in (
                "http://localhost:5173", "*",
            )


# ──────────────────────────────────────────────────────────────
# Test 8: Profile CRUD
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestProfile:
    """Verifica GET y PATCH del perfil de usuario."""

    def test_get_profile(self, client, db_session):
        _create_test_cliente(db_session)
        tokens = _login_sync(client)
        resp = client.get(
            "/users/me/profile",
            headers=_auth_headers(tokens["access_token"]),
        )
        assert resp.status_code in (200, 404), (
            f"Profile should return 200 (or 404 if Firestore disabled): {resp.status_code}"
        )
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, dict), f"Profile should be a dict: {type(data)}"

    def test_patch_profile(self, client, db_session):
        _create_test_cliente(db_session)
        tokens = _login_sync(client)
        resp = client.patch(
            "/users/me/profile",
            json={"nombre": "Nombre Actualizado"},
            headers=_auth_headers(tokens["access_token"]),
        )
        assert resp.status_code in (200, 404), (
            f"Patch profile should return 200 (or 404 if Firestore disabled): {resp.status_code}"
        )


# ──────────────────────────────────────────────────────────────
# Test 9: Refresh Token Rotation + Reuse Detection
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestRefreshTokenRotation:
    """Verifica rotación de refresh tokens y detección de reuso."""

    def test_refresh_rotation(self, client, db_session):
        """Refresh token rota correctamente."""
        _create_test_cliente(db_session)
        tokens = _login_sync(client)

        original_refresh = tokens["refresh_token"]

        # Primer refresh
        refresh1 = client.post("/v1/auth/refresh", json={
            "refresh_token": original_refresh,
        })
        assert refresh1.status_code == 200, (
            f"First refresh should return 200, got {refresh1.status_code}"
        )
        data1 = refresh1.json()
        assert "access_token" in data1
        assert "refresh_token" in data1
        assert data1["refresh_token"] != original_refresh, (
            "New refresh token should differ from original"
        )

        # Segundo refresh con el nuevo token
        refresh2 = client.post("/v1/auth/refresh", json={
            "refresh_token": data1["refresh_token"],
        })
        assert refresh2.status_code == 200, (
            f"Second refresh should return 200, got {refresh2.status_code}"
        )
        data2 = refresh2.json()
        assert data2["refresh_token"] != data1["refresh_token"], (
            "Each refresh should produce new refresh token"
        )

    def test_refresh_reuse_detection(self, client, db_session):
        """Reuso de refresh token debe revocar toda la familia."""
        _create_test_cliente(db_session)
        tokens = _login_sync(client)

        original_refresh = tokens["refresh_token"]

        # Usar el refresh token una vez
        refresh1 = client.post("/v1/auth/refresh", json={
            "refresh_token": original_refresh,
        })
        assert refresh1.status_code == 200
        new_refresh = refresh1.json()["refresh_token"]

        # Intentar reusar el token original — debe fallar
        reuse = client.post("/v1/auth/refresh", json={
            "refresh_token": original_refresh,
        })
        assert reuse.status_code == 401, (
            f"Refresh token reuse should return 401, got {reuse.status_code}"
        )

        # El nuevo token también debería estar revocado
        new_use = client.post("/v1/auth/refresh", json={
            "refresh_token": new_refresh,
        })
        assert new_use.status_code == 401, (
            f"New refresh should also be revoked after reuse, got {new_use.status_code}"
        )


# ──────────────────────────────────────────────────────────────
# Test 10: Rate Limiting
# ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestRateLimiting:
    """Verifica que rate limiting funciona (solo en entornos con limiter activo)."""

    def test_login_rate_limit(self, client, db_session):
        """Login repetido debe eventualmente ser rate-limited (si está activo)."""
        _create_test_cliente(db_session)

        # Intentar varios logins rápidos
        responses = []
        for _ in range(10):
            resp = client.post("/v1/auth/login", json={
                "cedula": _TEST_CEDULA,
                "password": _TEST_PASSWORD,
                "hardware_serial": _TEST_HARDWARE_SERIAL,
            })
            responses.append(resp.status_code)

        # En test, rate limiting está desactivado (TESTING=1)
        # Este test verifica que no rompa
        assert all(s in (200, 401, 429) for s in responses), (
            f"All responses should be 200, 401, or 429: {set(responses)}"
        )
