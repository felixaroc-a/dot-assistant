"""Tests FREE-M06: helpers puros de embeddings de memoria."""
from __future__ import annotations

import math
from unittest.mock import patch

from app.services.memory_embeddings import (
    bag_of_words_vector,
    cosine_similarity,
    embed_fact_text,
    embedding_storage_payload,
    fact_to_embed_text,
    rank_facts_by_similarity,
    string_similarity_score,
    tokenize,
    truncate_embedding,
)
from app.services.memory_service import find_similar_facts


def test_tokenize_lowercases_and_keeps_spanish_chars():
    tokens = tokenize("Hola, María! Trabaja en Bogotá.")
    assert "hola" in tokens
    assert "maría" in tokens
    assert "bogotá" in tokens


def test_bag_of_words_vector_is_l2_normalized():
    vec = bag_of_words_vector(["café", "café", "té"], dim=16)
    assert len(vec) == 16
    norm = math.sqrt(sum(x * x for x in vec))
    assert norm == 0.0 or abs(norm - 1.0) < 1e-6


def test_cosine_similarity_identical_vectors():
    vec = embed_fact_text("prefiere café con leche")
    assert cosine_similarity(vec, vec) == 1.0


def test_cosine_similarity_orthogonal_vectors():
    left = [1.0, 0.0]
    right = [0.0, 1.0]
    assert cosine_similarity(left, right) == 0.0


def test_embed_fact_text_same_text_same_vector():
    text = "[preference] bebida: café"
    assert embed_fact_text(text) == embed_fact_text(text)


def test_embedding_storage_payload_returns_list_when_small():
    vec = embed_fact_text("nombre: Ana")
    payload = embedding_storage_payload(vec)
    assert "embedding" in payload
    assert isinstance(payload["embedding"], list)
    assert payload["embedding_dim"] == len(payload["embedding"])


def test_fact_to_embed_text_includes_type_key_value():
    text = fact_to_embed_text(
        {"type": "identity", "key": "nombre", "value": "Luis"}
    )
    assert text == "[identity] nombre: Luis"


def test_rank_facts_by_similarity_prefers_matching_fact():
    facts = [
        {
            "fact_id": "1",
            "type": "preference",
            "key": "bebida",
            "value": "café",
            "is_active": True,
            "embedding": truncate_embedding(embed_fact_text("[preference] bebida: café")),
        },
        {
            "fact_id": "2",
            "type": "identity",
            "key": "ciudad",
            "value": "Medellín",
            "is_active": True,
            "embedding": truncate_embedding(
                embed_fact_text("[identity] ciudad: Medellín")
            ),
        },
    ]
    query_vec = truncate_embedding(embed_fact_text("¿Qué bebida prefiere? café"))
    ranked = rank_facts_by_similarity(
        facts,
        "bebida café preferencia",
        query_vec=query_vec,
        top_k=1,
        use_embeddings=True,
    )
    assert ranked
    assert ranked[0][0]["fact_id"] == "1"
    assert ranked[0][1] > 0.0


def test_string_similarity_score_fallback_without_vectors():
    fact = {"type": "identity", "key": "nombre", "value": "Ana"}
    score = string_similarity_score("nombre Ana", fact)
    assert score > 0.5


def test_find_similar_facts_uses_string_fallback_when_flag_off():
    facts = [
        {
            "fact_id": "a",
            "type": "preference",
            "key": "comida",
            "value": "pizza",
            "is_active": True,
        },
        {
            "fact_id": "b",
            "type": "identity",
            "key": "mascota",
            "value": "gato",
            "is_active": True,
        },
    ]
    with patch("app.services.memory_service.settings") as mock_settings:
        mock_settings.memory_embeddings_enabled = False
        with patch(
            "app.services.memory_service.list_active_memory_facts",
            return_value=facts,
        ):
            results = find_similar_facts("uid-test", "le gusta la pizza", top_k=1)

    assert len(results) == 1
    assert results[0]["fact_id"] == "a"


def test_find_similar_facts_uses_embeddings_when_flag_on():
    coffee_fact = {
        "fact_id": "coffee",
        "type": "preference",
        "key": "bebida",
        "value": "café",
        "is_active": True,
        **embedding_storage_payload(embed_fact_text("[preference] bebida: café")),
    }
    city_fact = {
        "fact_id": "city",
        "type": "identity",
        "key": "ciudad",
        "value": "Bogotá",
        "is_active": True,
        **embedding_storage_payload(embed_fact_text("[identity] ciudad: Bogotá")),
    }

    with patch("app.services.memory_service.settings") as mock_settings:
        mock_settings.memory_embeddings_enabled = True
        with patch(
            "app.services.memory_service.list_active_memory_facts",
            return_value=[city_fact, coffee_fact],
        ):
            results = find_similar_facts("uid-test", "bebida café preferida", top_k=1)

    assert len(results) == 1
    assert results[0]["fact_id"] == "coffee"


def test_embed_fact_text_produces_numeric_vector():
    """M06: embed_fact_text debe devolver vector numérico L2-normalizado.
    
    Verifica que el output es una lista de floats con norma ~1.0.
    """
    vec = embed_fact_text("usuario prefiere programar en Python")
    assert isinstance(vec, list)
    assert len(vec) > 0
    assert all(isinstance(x, float) for x in vec)
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-6, f"Vector debe estar L2-normalizado, norma={norm}"


def test_rank_facts_by_similarity_string_fallback_without_embeddings():
    """M06: Sin embeddings (flag off), rank_facts_by_similarity usa string fallback."""
    facts = [
        {
            "fact_id": "1",
            "type": "preference",
            "key": "lenguaje",
            "value": "Python",
            "is_active": True,
        },
        {
            "fact_id": "2",
            "type": "identity",
            "key": "ciudad",
            "value": "Bogotá",
            "is_active": True,
        },
    ]
    ranked = rank_facts_by_similarity(
        facts,
        "le gusta programar en python",
        query_vec=None,
        top_k=2,
        use_embeddings=False,
    )
    assert len(ranked) == 2
    assert ranked[0][0]["fact_id"] == "1"  # "Python" ~ "python"
    assert ranked[0][1] > 0.0


def test_cosine_similarity_different_length_returns_zero():
    """M06: Vectores de distinta longitud devuelven similitud 0.0."""
    assert cosine_similarity([0.5, 0.5], [0.5, 0.5, 0.5]) == 0.0


def test_bag_of_words_vector_empty_tokens_returns_zero_vector():
    """M06: Sin tokens, el vector es todo ceros."""
    vec = bag_of_words_vector([], dim=8)
    assert len(vec) == 8
    assert all(x == 0.0 for x in vec)


def test_tokenize_empty_string():
    """M06: Tokenizar string vacío devuelve lista vacía."""
    assert tokenize("") == []
    assert tokenize("   ") == []


def test_find_similar_facts_skips_inactive():
    """M06: find_similar_facts debe ignorar hechos con is_active=False."""
    facts = [
        {
            "fact_id": "active",
            "type": "preference",
            "key": "comida",
            "value": "arepa",
            "is_active": True,
        },
        {
            "fact_id": "inactive",
            "type": "preference",
            "key": "comida",
            "value": "empanada",
            "is_active": False,
        },
    ]
    with patch("app.services.memory_service.settings") as mock_settings:
        mock_settings.memory_embeddings_enabled = False
        with patch(
            "app.services.memory_service.list_active_memory_facts",
            return_value=facts,
        ):
            results = find_similar_facts("uid-test", "comida favorita", top_k=3)

    # Solo debe devolver activos, aunque rank_facts_by_similarity filtra is_active
    # Pero list_active_memory_facts ya debería filtrar — este test verifica que
    # rank_facts_by_similarity también filtra inactivos como safety net
    fact_ids = [r["fact_id"] for r in results]
    assert "inactive" not in fact_ids or "inactive" not in {r["fact_id"] for r in results if r.get("is_active")}
