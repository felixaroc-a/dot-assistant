"""Perfil: mapeo Firestore → DTO y contrato HTTP /users/me/profile."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.auth_deps import require_product_jwt
from app.repositories.profile_repository import doc_to_profile, patch_profile
from app.schemas.profile import (
    AiCredentialsPatch,
    SavedAutomationDto,
    UserProfilePatch,
    UserProfileResponse,
)
from app.services.oauth_service import encrypt_ai_credentials, get_user_ai_credentials

PROFILE_RESPONSE_KEYS = frozenset(UserProfileResponse.model_fields.keys())
SAVED_AUTOMATION_JSON_KEYS = frozenset(SavedAutomationDto.model_fields.keys())


@pytest.fixture
def profile_api_client(client: TestClient) -> TestClient:
    client.app.dependency_overrides[require_product_jwt] = lambda: {"sub": "uid-profile-contract"}
    yield client
    client.app.dependency_overrides.pop(require_product_jwt, None)


def test_doc_to_profile_maps_legacy_integration_id():
    raw = {
        "display_name": "Ana",
        "integrations": ["gmail"],
        "saved_automations": [
            {
                "id": "1",
                "name": "Auto",
                "integrationId": "gmail",
                "instruction": "Revisar inbox",
            }
        ],
        "onboarding_completed": True,
    }
    profile = doc_to_profile(raw)
    assert profile.display_name == "Ana"
    assert profile.integrations == ["gmail"]
    assert profile.onboarding_completed is True
    assert profile.saved_automations is not None
    assert profile.saved_automations[0].integration_id == "gmail"


def test_doc_to_profile_maps_ai_credentials_ciphertext():
    ciphertext = encrypt_ai_credentials(
        provider_id="deepseek",
        username="ana.usuario",
        password="secreto-ia",
    )
    raw = {
        "ai_provider_id": "deepseek",
        "ai_credentials_ciphertext": ciphertext,
    }
    profile = doc_to_profile(raw)
    assert profile.ai_credentials is not None
    assert profile.ai_credentials.provider_id == "deepseek"
    assert profile.ai_credentials.username == "ana.usuario"
    assert profile.ai_credentials.has_password is True


def test_patch_profile_encrypts_ai_credentials(monkeypatch):
    captured: dict = {}

    def _fake_merge(user_id: str, data: dict) -> None:
        captured["user_id"] = user_id
        captured["data"] = data

    def _fake_get(user_id: str) -> dict:
        return {
            "display_name": "Ana",
            "ai_provider_id": "deepseek",
            **captured.get("data", {}),
        }

    monkeypatch.setattr("app.repositories.profile_repository.merge_user_profile", _fake_merge)
    monkeypatch.setattr("app.repositories.profile_repository.get_user_profile", _fake_get)

    body = UserProfilePatch(
        display_name="Ana",
        ai_credentials=AiCredentialsPatch(
            provider_id="deepseek",
            username="ana.usuario",
            password="secreto-ia",
        ),
    )
    profile = patch_profile("uid-123", body)
    assert captured["user_id"] == "uid-123"
    stored = captured["data"]
    assert "ai_credentials" not in stored
    assert isinstance(stored.get("ai_credentials_ciphertext"), str)
    assert profile.ai_credentials is not None
    assert profile.ai_credentials.provider_id == "deepseek"
    assert profile.ai_credentials.username == "ana.usuario"
    assert profile.ai_credentials.has_password is True


def test_get_user_ai_credentials_reads_firestore_profile(monkeypatch):
    ciphertext = encrypt_ai_credentials(
        provider_id="gemini",
        username="gema",
        password="pass-123",
    )

    monkeypatch.setattr(
        "app.services.oauth_service.get_user_profile",
        lambda _uid: {"ai_credentials_ciphertext": ciphertext},
    )
    creds = get_user_ai_credentials("uid-xyz")
    assert creds is not None
    assert creds["provider_id"] == "gemini"
    assert creds["username"] == "gema"
    assert creds["password"] == "pass-123"


def test_doc_to_profile_empty():
    profile = doc_to_profile({})
    assert profile.display_name is None
    assert profile.integrations is None


def test_saved_automation_dto_api_json_uses_snake_case():
    dto = SavedAutomationDto(
        id="1",
        name="Auto",
        integration_id="gmail",
        instruction="Revisar inbox",
        output_type="chat",
    )
    payload = json.loads(dto.model_dump_json())
    assert payload["integration_id"] == "gmail"
    assert "integrationId" not in payload
    assert payload["output_type"] == "chat"
    assert "outputType" not in payload


def test_saved_automation_dto_accepts_legacy_camel_case_input():
    dto = SavedAutomationDto.model_validate(
        {
            "id": "1",
            "name": "Auto",
            "integrationId": "gmail",
            "instruction": "Revisar",
            "outputType": "chat",
        }
    )
    assert dto.integration_id == "gmail"
    assert dto.output_type == "chat"


def test_user_profile_response_serializes_saved_automations_snake_case():
    profile = doc_to_profile(
        {
            "saved_automations": [
                {
                    "id": "1",
                    "name": "Auto",
                    "integration_id": "gmail",
                    "instruction": "Revisar",
                    "output_type": "chat",
                }
            ]
        }
    )
    payload = json.loads(profile.model_dump_json())
    auto = payload["saved_automations"][0]
    assert auto["integration_id"] == "gmail"
    assert "integrationId" not in auto
    assert auto["output_type"] == "chat"
    assert "outputType" not in auto


def test_get_users_me_profile_json_contract(profile_api_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.repositories.profile_repository.get_user_profile",
        lambda _uid: {
            "display_name": "Ana",
            "saved_automations": [
                {
                    "id": "auto-1",
                    "name": "Inbox",
                    "integrationId": "gmail",
                    "instruction": "Revisar",
                    "outputType": "chat",
                }
            ],
        },
    )
    resp = profile_api_client.get(
        "/users/me/profile",
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert frozenset(data.keys()) == PROFILE_RESPONSE_KEYS
    auto = data["saved_automations"][0]
    assert frozenset(auto.keys()) == SAVED_AUTOMATION_JSON_KEYS
    assert auto["integration_id"] == "gmail"
    assert auto["output_type"] == "chat"
    assert "integrationId" not in auto
    assert "outputType" not in auto


def test_patch_users_me_profile_json_contract(profile_api_client: TestClient, monkeypatch) -> None:
    stored: dict = {"display_name": "Ana"}

    def _merge(user_id: str, data: dict) -> None:
        assert user_id == "uid-profile-contract"
        stored.update(data)

    monkeypatch.setattr(
        "app.repositories.profile_repository.merge_user_profile",
        _merge,
    )
    monkeypatch.setattr(
        "app.repositories.profile_repository.get_user_profile",
        lambda _uid: stored,
    )

    resp = profile_api_client.patch(
        "/users/me/profile",
        headers={"Authorization": "Bearer test"},
        json={
            "saved_automations": [
                {
                    "id": "auto-1",
                    "name": "Inbox",
                    "integrationId": "gmail",
                    "instruction": "Revisar",
                    "outputType": "docx",
                }
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert frozenset(data.keys()) == PROFILE_RESPONSE_KEYS
    auto = data["saved_automations"][0]
    assert auto["integration_id"] == "gmail"
    assert auto["output_type"] == "docx"
    assert "integrationId" not in auto
    assert "outputType" not in auto

    merged_auto = stored["saved_automations"][0]
    assert merged_auto["integration_id"] == "gmail"
    assert merged_auto["output_type"] == "docx"
    assert "integrationId" not in merged_auto
    assert "outputType" not in merged_auto
