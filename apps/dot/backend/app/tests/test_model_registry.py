"""Tests para el registro de modelos multi-proveedor."""
from __future__ import annotations

import pytest

from app.services.model_registry import (
    ModelInfo,
    get_all_models,
    get_available_models,
    get_default_model,
    get_fallback_chain,
    get_model_by_id,
    get_models_for_provider,
    is_multi_model_available,
)


class TestModelRegistry:
    """Verifica que el catálogo de modelos se carga y filtra correctamente."""

    def test_get_all_models_returns_catalog(self) -> None:
        models = get_all_models()
        assert len(models) >= 8, f"Se esperaban al menos 8 modelos, hay {len(models)}"

        model_ids = {m.model_id for m in models}
        expected = {
            "deepseek-chat",
            "deepseek-reasoner",
            "gpt-4o-mini",
            "gpt-4o",
            "claude-3-haiku-20240307",
            "claude-3-5-sonnet-20241022",
            "llama-3.3-70b-versatile",
            "mixtral-8x7b-32768",
        }
        assert expected.issubset(model_ids), f"Faltan modelos: {expected - model_ids}"

    def test_get_available_models_filters_by_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        # Solo DeepSeek configurado
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test-ds")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")

        available = get_available_models()
        providers = {m.provider for m in available}
        assert providers == {"deepseek"}, f"Esperado solo deepseek, obtenido {providers}"
        assert len(available) == 2  # deepseek-chat + deepseek-reasoner

    def test_get_available_models_multiple_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test-ds")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "sk-test-oai")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")

        available = get_available_models()
        providers = {m.provider for m in available}
        assert "deepseek" in providers
        assert "openai" in providers
        assert "anthropic" not in providers

    def test_get_available_models_none_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")

        available = get_available_models()
        assert available == [], f"Esperado vacío, obtenido {len(available)} modelos"

    def test_get_default_model_returns_deepseek_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test-ds")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")

        default = get_default_model()
        assert default is not None
        assert default.provider == "deepseek"
        assert default.model_id == "deepseek-chat"

    def test_get_default_model_returns_openai_when_deepseek_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "sk-test-oai")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")

        default = get_default_model()
        assert default is not None
        assert default.provider == "openai"

    def test_get_default_model_returns_none_when_no_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")

        default = get_default_model()
        assert default is None

    def test_get_model_by_id_returns_correct_model(self) -> None:
        model = get_model_by_id("gpt-4o-mini")
        assert model is not None
        assert model.model_id == "gpt-4o-mini"
        assert model.provider == "openai"
        assert model.context_window == 128000

    def test_get_model_by_id_returns_none_for_unknown(self) -> None:
        model = get_model_by_id("nonexistent-model")
        assert model is None

    def test_get_models_for_provider(self) -> None:
        deepseek_models = get_models_for_provider("deepseek")
        assert len(deepseek_models) == 2

        openai_models = get_models_for_provider("openai")
        assert len(openai_models) == 2

        groq_models = get_models_for_provider("groq")
        assert len(groq_models) == 2
        # Groq models should be free tier
        for m in groq_models:
            assert m.tier == "free"
            assert m.cost_input_1m == 0.0
            assert m.cost_output_1m == 0.0

    def test_get_fallback_chain_respects_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        # Todos configurados
        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test-ds")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "sk-test-oai")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "sk-test-ant")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "sk-test-grq")

        chain = get_fallback_chain()
        assert len(chain) >= 8
        # Primer proveedor debe ser deepseek (prioridad más alta)
        assert chain[0].provider == "deepseek"

    def test_get_fallback_chain_with_preferred_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test-ds")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "sk-test-oai")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")

        chain = get_fallback_chain("gpt-4o-mini")
        assert len(chain) > 0
        # El modelo preferido debe ir primero
        assert chain[0].model_id == "gpt-4o-mini"

    def test_is_multi_model_available_one_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test-ds")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")

        assert is_multi_model_available() is False

    def test_is_multi_model_available_two_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "sk-test-ds")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "sk-test-oai")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")

        assert is_multi_model_available() is True

    def test_model_info_to_dict(self) -> None:
        model = get_model_by_id("deepseek-chat")
        assert model is not None
        d = model.to_dict()
        assert d["id"] == "deepseek-chat"
        assert d["provider"] == "deepseek"
        assert "capabilities" in d
        assert "available" in d
        assert isinstance(d["available"], bool)

    def test_deepseek_reasoner_has_correct_costs(self) -> None:
        model = get_model_by_id("deepseek-reasoner")
        assert model is not None
        assert model.is_reasoner is True
        assert model.cost_input_1m == 0.55
        assert model.cost_output_1m == 2.19
        assert "reasoning" in model.capabilities


class TestMultiModelIntegration:
    """Pruebas de integración ligera con el router."""

    def test_model_router_default_imports(self) -> None:
        """Verifica que los imports del model_router no fallen."""
        from app.services.model_router import (
            AllProvidersExhaustedError,
            route_chat_completion,
            route_chat_stream,
        )
        assert AllProvidersExhaustedError is not None
        assert route_chat_completion is not None
        assert route_chat_stream is not None

    def test_model_router_exhausted_when_no_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings
        from app.services.model_router import route_chat_completion, AllProvidersExhaustedError

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")
        # También desactivar model_routing para que route_chat_detailed use el path multi-model
        monkeypatch.setattr(app_settings.settings, "model_routing_enabled", True)

        with pytest.raises(AllProvidersExhaustedError):
            route_chat_completion([{"role": "user", "content": "Hola"}])

    @pytest.mark.asyncio
    async def test_model_router_stream_exhausted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as app_settings
        from app.services.model_router import route_chat_stream

        monkeypatch.setattr(app_settings.settings, "deepseek_api_key", "")
        monkeypatch.setattr(app_settings.settings, "openai_api_key", "")
        monkeypatch.setattr(app_settings.settings, "anthropic_api_key", "")
        monkeypatch.setattr(app_settings.settings, "groq_api_key", "")
        monkeypatch.setattr(app_settings.settings, "model_routing_enabled", True)

        results = []
        async for token, finish in route_chat_stream([{"role": "user", "content": "Hola"}]):
            results.append((token, finish))
        assert len(results) > 0
        # Debe haber un mensaje de error
        assert any("Error" in t for t, _ in results)
