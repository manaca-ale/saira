"""Unit tests for normalize_offender_types (taxonomia de tipo de descarte).

Contexto: em prod o banco tinha 1152 Pessoa / 355 Outro e ZERO Carroça, apesar
de carroça ser evento conhecido no Arruda. A causa era o lookup sem strip de
acento — "carroça" nunca casava com a chave "carroca" e caía no descarte
silencioso. Estes testes travam o comportamento corrigido.
"""
from __future__ import annotations

import json
import logging

from worker.detector_gemini import normalize_offender_types


def test_accented_tokens_map_correctly():
    """O bug original: acento fazia o token ser descartado em silêncio."""
    assert normalize_offender_types(["carroça"]) == ["Carroca"]
    assert normalize_offender_types(["caminhão"]) == ["Caminhao"]
    assert normalize_offender_types(["ônibus"]) == ["Carro"]


def test_truck_is_its_own_category():
    """Caminhão deixou de colapsar em Carro (enum ganhou Caminhao)."""
    assert normalize_offender_types(["caminhao"]) == ["Caminhao"]
    assert normalize_offender_types(["truck"]) == ["Caminhao"]
    assert normalize_offender_types(["carro"]) == ["Carro"]


def test_extended_vocabulary():
    assert normalize_offender_types(["wheelbarrow"]) == ["Carroca"]
    assert normalize_offender_types(["handcart"]) == ["Carroca"]
    assert normalize_offender_types(["van"]) == ["Carro"]
    assert normalize_offender_types(["pedestrian"]) == ["Pessoa"]
    assert normalize_offender_types(["bicicleta"]) == ["Outro"]


def test_case_and_whitespace_insensitive():
    assert normalize_offender_types(["  CARROÇA  "]) == ["Carroca"]


def test_dedupes_preserving_order():
    assert normalize_offender_types(["pessoa", "person", "carro"]) == ["Pessoa", "Carro"]


def test_empty_input():
    assert normalize_offender_types(None) == []
    assert normalize_offender_types([]) == []


def test_unmapped_token_is_dropped_but_logged(caplog):
    """Token fora do mapa não pode virar lacuna invisível na taxonomia."""
    with caplog.at_level(logging.INFO, logger="worker.detector_gemini"):
        assert normalize_offender_types(["pessoa", "hovercraft"]) == ["Pessoa"]

    events = [
        json.loads(r.message)
        for r in caplog.records
        if r.message.startswith("{") and "offender_type_unmapped" in r.message
    ]
    assert events and events[0]["tokens"] == ["hovercraft"]


def test_no_log_when_all_tokens_map(caplog):
    with caplog.at_level(logging.INFO, logger="worker.detector_gemini"):
        normalize_offender_types(["pessoa", "carroça"])
    assert "offender_type_unmapped" not in caplog.text
