"""Tests para el enrutador de proveedores IA (DeepSeek-only v1)."""
from __future__ import annotations

import pytest

from app.services.provider_router import (
    ProviderNotAvailableError,
    get_available_providers,
    route_chat,
    route_summarize,
    route_translate,
)


class TestDeepSeekSinApiKey:
    """Test que sin API key lance ProviderNotAvailableError."""

    def test_deepseek_sin_api_key_lanza_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "")

        with pytest.raises(ProviderNotAvailableError) as exc:
            route_chat("Hola")
        assert "DeepSeek" in str(exc.value)

    def test_ignora_provider_id_sin_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "")

        with pytest.raises(ProviderNotAvailableError) as exc:
            route_chat("Hola", provider_id="gemini")
        assert "DeepSeek" in str(exc.value)


class TestDeepSeekConMock:
    """Test que deepseek funcione con mock."""

    def test_deepseek_con_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test-key")
        monkeypatch.setattr(app_settings.settings, "model_routing_enabled", False)

        class MockProvider:
            class _MockResponse:
                content = "Respuesta mock de DeepSeek"
                usage = None
                finish_reason = "stop"
                model = "mock-deepseek"

            def chat(self, messages: list[dict], system_prompt: str | None = None):
                return self._MockResponse()

        monkeypatch.setattr("app.services.ai_provider.AIProvider", lambda: MockProvider())

        result = route_chat("Hola, ¿cómo estás?")
        assert "DeepSeek" in result or "Respuesta" in result

    def test_ignora_provider_id_con_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test-key")
        monkeypatch.setattr(app_settings.settings, "model_routing_enabled", False)

        class MockProvider:
            class _MockResponse:
                content = "Siempre DeepSeek"
                usage = None
                finish_reason = "stop"
                model = "mock-deepseek"

            def chat(self, messages: list[dict], system_prompt: str | None = None):
                return self._MockResponse()

        monkeypatch.setattr("app.services.ai_provider.AIProvider", lambda: MockProvider())

        result = route_chat("Hola", provider_id="chatgpt")
        assert result == "Siempre DeepSeek"

        result = route_chat("Hola", provider_id="gemini")
        assert result == "Siempre DeepSeek"

        result = route_chat("Hola", provider_id="proveedor-inexistente")
        assert result == "Siempre DeepSeek"


class TestGetAvailableProviders:
    """Test get_available_providers retorna todos los proveedores con estado."""

    def test_solo_deepseek_disponible(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test")

        providers = get_available_providers()
        assert len(providers) == 4  # deepseek, openai, anthropic, groq
        deepseek = [p for p in providers if p.id == "deepseek"][0]
        assert deepseek.is_available is True

    def test_deepseek_no_disponible(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "")

        providers = get_available_providers()
        assert len(providers) == 4  # all providers listed
        deepseek = [p for p in providers if p.id == "deepseek"][0]
        assert deepseek.is_available is False


class TestRouteTranslate:
    """Tests para traducción con Google primario y fallback DeepSeek."""

    def test_route_translate_usa_google_si_hay_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "google_translate_api_key", "google-test")
        monkeypatch.setattr(
            "app.services.provider_router._translate_with_google",
            lambda text, target, _key: f"{text}=>{target}",
        )

        translated, provider_used, target = route_translate("Hola mundo", "inglés")
        assert translated == "Hola mundo=>en"
        assert provider_used == "google_translate"
        assert target == "en"

    def test_route_translate_fallback_a_deepseek_si_google_falla(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "google_translate_api_key", "google-test")
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "deepseek-test")

        def _fail_google(_text: str, _target: str, _key: str) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr("app.services.provider_router._translate_with_google", _fail_google)
        monkeypatch.setattr(
            "app.services.provider_router._call_deepseek",
            lambda _text, _prompt, _ai_provider=None: "Hello world",
        )

        translated, provider_used, target = route_translate("Hola mundo", "en")
        assert translated == "Hello world"
        assert provider_used == "deepseek"
        assert target == "en"

    def test_route_translate_falla_si_no_hay_google_ni_deepseek(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "google_translate_api_key", "")
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "")

        with pytest.raises(ProviderNotAvailableError) as exc:
            route_translate("Hola mundo", "español")
        assert "GOOGLE_TRANSLATE_API_KEY" in str(exc.value)


class TestRouteSummarize:
    def test_route_summarize_usa_route_chat_sin_document_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        class _FakeSummarizer:
            def summarize(self, _content: str, summarize_fn):
                summary = summarize_fn("PROMPT BLOQUE")
                return {
                    "summary": summary,
                    "source_type": "text",
                    "chunks": 1,
                }

        monkeypatch.setattr(
            "app.services.summarizer_service.SummarizerService",
            lambda: _FakeSummarizer(),
        )

        def _fake_route_chat(
            _text: str,
            _provider_id: str | None = None,
            _system_prompt: str | None = None,
            include_document_action_prompt: bool = True,
            ai_provider=None,
        ) -> str:
            captured["include_document_action_prompt"] = include_document_action_prompt
            return "Resumen final"

        monkeypatch.setattr("app.services.provider_router.route_chat", _fake_route_chat)

        summary, source_type, chunks = route_summarize("texto a resumir")
        assert summary == "Resumen final"
        assert source_type == "text"
        assert chunks == 1
        assert captured["include_document_action_prompt"] is False
