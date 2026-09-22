#!/usr/bin/env python3
"""Tests du module d'observabilité Stats : compteurs, taux de succès,
journalisation de synthèse, et intégration dans Bridge (erreurs d'envoi
capturées sans crash)."""

from __future__ import annotations

import json

from loguru import logger as _logger

from oxo_hep_bridge.stats import Stats


def test_stats_success_rate_zero_when_nothing_received():
    stats = Stats()
    assert stats.success_rate == 0.0


def test_stats_success_rate_computed_from_sent_and_received():
    stats = Stats(received=100, sent=80, skipped=20)
    assert stats.success_rate == 80.0


def test_stats_to_dict_roundtrip():
    stats = Stats(received=10, sent=8, skipped=2, send_errors=1, normalize_errors=1)
    data = stats.to_dict()
    assert data["received"] == 10
    assert data["sent"] == 8
    assert data["skipped"] == 2
    assert data["send_errors"] == 1
    assert data["normalize_errors"] == 1
    assert data["success_rate"] == 80.0
    # sérialisable en JSON
    json.dumps(data)


def test_stats_log_summary_includes_counts():
    captured: list[str] = []

    def _sink(message):
        captured.append(str(message))

    handler_id = _logger.add(_sink, level="DEBUG")
    try:
        stats = Stats(received=64, sent=60, skipped=4)
        stats.log_summary()
    finally:
        _logger.remove(handler_id)
    summary_text = "\n".join(captured)
    assert "64 paquets reçus" in summary_text
    assert "60 envoyés" in summary_text
    assert "4 ignorés" in summary_text


def test_stats_log_summary_verbose_when_errors():
    captured: list[str] = []

    def _sink(message):
        captured.append(str(message))

    handler_id = _logger.add(_sink, level="DEBUG")
    try:
        stats = Stats(received=10, sent=8, skipped=1, send_errors=1)
        stats.log_summary()
    finally:
        _logger.remove(handler_id)
    detail_text = "\n".join(captured)
    assert "détail" in detail_text
    assert "1" in detail_text  # send_errors affiché


def test_stats_to_dict_includes_send_retries():
    stats = Stats(received=10, sent=10, send_retries=3)
    data = stats.to_dict()
    assert data["send_retries"] == 3
    json.dumps(data)


def test_stats_log_summary_shown_when_retries_even_without_errors():
    """Des tentatives supplémentaires sans erreur finale (collecteur revenu
    après une brève coupure) méritent d'être visibles, pas seulement les
    échecs définitifs."""
    captured: list[str] = []

    def _sink(message):
        captured.append(str(message))

    handler_id = _logger.add(_sink, level="DEBUG")
    try:
        stats = Stats(received=5, sent=5, send_retries=2)
        stats.log_summary()
    finally:
        _logger.remove(handler_id)
    detail_text = "\n".join(captured)
    assert "détail" in detail_text
    assert "tentatives d'envoi supplémentaires" in detail_text


# --- Session 42 : Stats.to_dict() lié aux enregistrements de log_summary() ---
#
# Dernier candidat vérifié de docs/roadmap.md (session 39) : to_dict()
# existait déjà mais n'était jamais consommé ailleurs que par ses propres
# tests. log_summary() lie désormais le dict complet à chaque enregistrement
# via logger.bind(stats=...) — invisible côté texte humain (assertions
# ci-dessus, toujours vraies), mais exploité par un sink JSON
# (serialize=True, voir cli.py --log-json-file).


def test_stats_log_summary_binds_full_stats_dict_as_extra():
    captured_records: list[dict] = []

    def _sink(message):
        captured_records.append(message.record)

    handler_id = _logger.add(_sink, level="DEBUG")
    try:
        stats = Stats(received=64, sent=60, skipped=4)
        stats.log_summary()
    finally:
        _logger.remove(handler_id)

    assert len(captured_records) == 1  # pas d'erreurs/retries => pas de ligne détail
    assert captured_records[0]["extra"]["stats"] == stats.to_dict()


def test_stats_log_summary_verbose_detail_line_also_binds_stats_extra():
    """La ligne « détail » (verbose ou erreurs/retries non nuls) doit porter
    le même dict complet que la ligne résumé — pas seulement les 4 valeurs
    qu'elle interpole en texte."""
    captured_records: list[dict] = []

    def _sink(message):
        captured_records.append(message.record)

    handler_id = _logger.add(_sink, level="DEBUG")
    try:
        stats = Stats(received=10, sent=8, skipped=1, send_errors=1, normalize_errors=1)
        stats.log_summary()
    finally:
        _logger.remove(handler_id)

    assert len(captured_records) == 2  # résumé + détail
    for record in captured_records:
        assert record["extra"]["stats"] == stats.to_dict()


def test_stats_log_summary_extra_invisible_in_default_text_sink():
    """Garde-fou négatif : logger.bind() ne doit rien changer au *message*
    interpolé (le texte du format string, pas la ligne complète qui inclut
    aussi le nom du module `oxo_hep_bridge.stats` — qui contient lui-même la
    sous-chaîne « stats ») — seul un sink serialize=True expose extra.stats
    (voir tests ci-dessus)."""
    captured_messages: list[str] = []

    def _sink(message):
        captured_messages.append(message.record["message"])

    handler_id = _logger.add(_sink, level="DEBUG")
    try:
        stats = Stats(received=64, sent=60, skipped=4)
        stats.log_summary()
    finally:
        _logger.remove(handler_id)
    assert captured_messages == [
        "terminé : 64 paquets reçus, 60 envoyés, 4 ignorés (93.8% envoyés/reçus)"
    ]
