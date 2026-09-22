#!/usr/bin/env python3
"""Bout en bout avec un vrai binaire tshark (pas `FakePopen`).

Contexte (session 24) : `docs/roadmap.md` § « À faire » est vide depuis
plusieurs sessions. Les sessions avec accès réseau (17, 20, 23...) ne s'en
servaient que pour `pytest`/`mypy`/`ruff` — la suite elle-même n'a jamais
dépendu de `tshark` (voir `FakePopen` dans `conftest.py`, et `make run-dry`
dans le Makefile qui reste un geste manuel, jamais exécuté par `pytest`).
Rien dans le CHANGELOG n'indique qu'une session précédente ait eu `tshark`
installé pour vérifier le pipeline contre un vrai subprocess plutôt que
contre les fixtures `.ek.ndjson` rejouées.

Ce sandbox avait les deux à la fois (réseau + `apt-get install tshark`
fonctionnel) : l'occasion de vérifier empiriquement, pour la première fois,
que `Bridge.run()` fonctionne réellement de bout en bout sur les 3 captures
d'exemple avec un vrai `tshark` — pas seulement contre des fixtures figées.
Résultat : succès complet sur les 3 captures, chiffres exacts conformes à la
documentation (README § « Captures d'exemple » pour 64/339/2544 ; le 993
envoyés sur `uaudp_ipv6.pcap` est le même total déjà vérifié en session 20
pour le calcul de perte de contenu NOE sur les opcodes UAUDP >= 16, voir
`docs/architecture.md#limites-connues` et
`tests/test_fields.py::test_uaudp_opcode_16_23_content_loss_matches_documented_figure`).

Ces tests sont ignorés (skip) si `tshark` n'est pas utilisable — exactement
comme `test_sender.py::requires_ipv6` est ignoré si l'IPv6 n'est pas
disponible à l'exécution. `make test` continue donc de ne jamais dépendre de
`tshark` (voir CLAUDE.md), mais toute session future qui en disposerait
obtient automatiquement cette vérification de bout en bout au lieu d'avoir à
la refaire à la main.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from oxo_hep_bridge.bridge import Bridge
from oxo_hep_bridge.config import Config

REPO_ROOT = Path(__file__).parent.parent
SAMPLE_CAPTURES = REPO_ROOT / "sample_captures"


def _real_tshark_available() -> bool:
    """Détecte un vrai `tshark` utilisable, pas seulement présent dans le
    `PATH` : `-v` doit réellement s'exécuter avec succès (même discipline
    que `_ipv6_runtime_available()` dans `test_sender.py` : une détection
    statique ne suffit pas, il faut une tentative d'exécution réelle)."""
    if shutil.which("tshark") is None:
        return False
    try:
        subprocess.run(  # noqa: S603
            ["tshark", "-v"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


requires_real_tshark = pytest.mark.skipif(
    not _real_tshark_available(),
    reason="tshark réel non disponible/utilisable dans cet environnement d'exécution",
)


def _run_dry(pcap_name: str, *, decode_as: list[str] | None = None) -> Bridge:
    """Construit une Config pointant sur une capture d'exemple et lance un
    run complet en dry-run (aucun envoi réseau, uniquement l'encodage)."""
    config = Config()
    config.capture.pcap = str(SAMPLE_CAPTURES / pcap_name)
    config.capture.decode_as = list(decode_as or [])
    config.dry_run = True
    config.logging.stats_interval = 0  # pas de log de progression, sortie de test propre
    bridge = Bridge(config)
    returncode = bridge.run()
    assert returncode == 0
    return bridge


@requires_real_tshark
def test_ua3g_freeseating_ipv4_end_to_end_with_real_tshark() -> None:
    """64 paquets (README § Captures d'exemple), tous normalisés et
    "envoyés" en dry-run, sans aucune erreur tshark/normalize/send."""
    stats = _run_dry("ua3g_freeseating_ipv4.pcap").stats
    assert stats.received == 64
    assert stats.sent == 64
    assert stats.skipped == 0
    assert stats.send_errors == 0
    assert stats.normalize_errors == 0
    assert stats.tshark_errors == 0


@requires_real_tshark
def test_ua3g_freeseating_ipv6_end_to_end_with_real_tshark() -> None:
    """339 paquets (README § Captures d'exemple), même chaîne qu'en IPv4
    mais en IPv6 — voir aussi la résolution IPv4/IPv6/DNS de --hep-host,
    hors sujet ici puisque dry-run n'ouvre aucune socket réelle."""
    stats = _run_dry("ua3g_freeseating_ipv6.pcap").stats
    assert stats.received == 339
    assert stats.sent == 339
    assert stats.skipped == 0
    assert stats.send_errors == 0
    assert stats.normalize_errors == 0
    assert stats.tshark_errors == 0


@requires_real_tshark
def test_uaudp_ipv6_end_to_end_matches_documented_opcode_figure() -> None:
    """2544 trames au total (README), dont 993 réellement uaudp et donc
    normalisées/envoyées — le même total que celui déjà vérifié en session 20
    pour la perte de contenu NOE sur les opcodes UAUDP >= 16 (163/993, voir
    docs/architecture.md#limites-connues). Les 1551 trames restantes
    (2544 - 993) sont du bruit hors uaudp/UA que normalize() ignore
    volontairement, pas une erreur."""
    stats = _run_dry("uaudp_ipv6.pcap", decode_as=["udp.port==32640,uaudp"]).stats
    assert stats.received == 2544
    assert stats.sent == 993
    assert stats.skipped == 2544 - 993
    assert stats.send_errors == 0
    assert stats.normalize_errors == 0
    assert stats.tshark_errors == 0


# Session 45 : docs/ua3g-call-signaling-decroche-numerotation.md était le
# dernier document exploratoire signalé « pas encore audité » dans
# docs/roadmap.md (backlog fonctionnel vide depuis la session 42). Vérifié
# ligne à ligne contre un vrai tshark cette session : toutes les
# affirmations se confirment exactes (table des opcodes UAUDP 0-7,
# libellés natifs, durées/comptages des 3 captures, unique occurrence de
# `hook_status` en frame 119 de la capture ipv6 freeseating — dans un
# message d'enregistrement du poste, pas un décroché en cours d'appel —
# et absence totale de `digit_dialed.digit_value`/`key_number` sur les 3
# captures d'exemple). Contrairement au §6ter de
# `noe-ua3g-homer-mapping.md` (déjà protégé depuis la session 43), ce
# constat n'était encore protégé par aucun test — seul le texte du
# document l'affirmait. Les commandes ci-dessous reproduisent exactement
# celle donnée en §5 du document (mêmes options `-d`/`-Y`/`-T fields`),
# contre un vrai binaire tshark plutôt que via `FakePopen`/les fixtures
# `.ek.ndjson` (ces champs ne sont d'ailleurs extraits par aucun code du
# pont — `semantics.py` ne les expose pas, voir
# docs/architecture.md#limites-connues — donc aucune fixture existante ne
# les couvre).
_UA3G_CALL_SIGNALING_DECODE_AS = [
    "udp.port==32640,uaudp",
    "udp.port==32513,uaudp",
]


def _tshark_field_rows(pcap_name: str, display_filter: str, *fields: str) -> list[list[str]]:
    """Rejoue exactement la commande de
    `docs/ua3g-call-signaling-decroche-numerotation.md#5` (mêmes options
    `-d`) sur une capture d'exemple, et renvoie les lignes de sortie
    (une par trame correspondant au filtre), déjà découpées par champ."""
    args = ["tshark", "-r", str(SAMPLE_CAPTURES / pcap_name)]
    for mapping in _UA3G_CALL_SIGNALING_DECODE_AS:
        args += ["-d", mapping]
    args += ["-Y", display_filter, "-T", "fields"]
    for field in fields:
        args += ["-e", field]
    result = subprocess.run(  # noqa: S603
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=True,
        text=True,
    )
    lines = [line for line in result.stdout.splitlines() if line]
    return [line.split("\t") for line in lines]


@requires_real_tshark
@pytest.mark.parametrize(
    "pcap_name",
    ["ua3g_freeseating_ipv4.pcap", "ua3g_freeseating_ipv6.pcap", "uaudp_ipv6.pcap"],
)
def test_ua3g_call_signaling_doc_digit_dialed_never_observed(pcap_name: str) -> None:
    """`docs/ua3g-call-signaling-decroche-numerotation.md#4` : aucune des 3
    captures d'exemple ne contient de valeur pour
    `ua3g.digit_dialed.digit_value` — c'est le fondement de la conclusion du
    document (impossible de reconstituer un numéro composé depuis ces
    fichiers)."""
    rows = _tshark_field_rows(
        pcap_name, "ua3g.digit_dialed.digit_value", "ua3g.digit_dialed.digit_value"
    )
    assert rows == []


@requires_real_tshark
@pytest.mark.parametrize(
    "pcap_name",
    ["ua3g_freeseating_ipv4.pcap", "ua3g_freeseating_ipv6.pcap", "uaudp_ipv6.pcap"],
)
def test_ua3g_call_signaling_doc_key_number_never_observed(pcap_name: str) -> None:
    """Même garde-fou que ci-dessus pour `ua3g.key_number` (§4 du même
    document : numéro de touche clavier physique, pas nécessairement un
    chiffre composé)."""
    rows = _tshark_field_rows(pcap_name, "ua3g.key_number", "ua3g.key_number")
    assert rows == []


@requires_real_tshark
def test_ua3g_call_signaling_doc_hook_status_single_boot_occurrence() -> None:
    """`docs/ua3g-call-signaling-decroche-numerotation.md#2` et `#4` :
    `ua3g.unsolicited_msg.hook_status` n'apparaît que sur la capture ipv6
    freeseating, une seule fois (frame 119), à l'intérieur d'un message
    `IP Device Routing: Init` (enregistrement/boot du poste, `ua3g.opcode`
    0x13 puis 0x9f) — jamais lors d'un décroché en cours d'appel. Les deux
    autres captures n'en contiennent aucune occurrence."""
    for pcap_name in ("ua3g_freeseating_ipv4.pcap", "uaudp_ipv6.pcap"):
        assert (
            _tshark_field_rows(
                pcap_name,
                "ua3g.unsolicited_msg.hook_status",
                "ua3g.unsolicited_msg.hook_status",
            )
            == []
        )

    rows = _tshark_field_rows(
        "ua3g_freeseating_ipv6.pcap",
        "ua3g.unsolicited_msg.hook_status",
        "frame.number",
        "ua3g.opcode",
        "ua3g.unsolicited_msg.hook_status",
    )
    assert len(rows) == 1
    frame_number, opcode, hook_status = rows[0]
    assert frame_number == "119"
    assert opcode == "0x13,0x9f"
    assert hook_status == "0"


@requires_real_tshark
@pytest.mark.parametrize(
    ("pcap_name", "expected_packets", "expected_duration_seconds"),
    [
        ("ua3g_freeseating_ipv4.pcap", 64, 19.683166),
        ("ua3g_freeseating_ipv6.pcap", 339, 141.595744),
        ("uaudp_ipv6.pcap", 2544, 356.884835),
    ],
)
def test_ua3g_call_signaling_doc_capture_durations_and_counts(
    pcap_name: str, expected_packets: int, expected_duration_seconds: float
) -> None:
    """Table `docs/ua3g-call-signaling-decroche-numerotation.md#4` (durée et
    nombre de paquets des 3 captures d'exemple). Les comptages de paquets
    sont aussi vérifiés indirectement par `stats.received` dans les tests
    ci-dessus ; ce test-ci protège en plus la durée affichée dans le
    document, jamais vérifiée par un test existant."""
    rows = _tshark_field_rows(pcap_name, "frame", "frame.number", "frame.time_relative")
    assert len(rows) == expected_packets
    last_relative_time = float(rows[-1][1])
    assert last_relative_time == pytest.approx(expected_duration_seconds, abs=1e-3)


@requires_real_tshark
def test_ua3g_call_signaling_doc_uaudp_opcode_labels() -> None:
    """`docs/ua3g-call-signaling-decroche-numerotation.md#1`/`#3` : les
    valeurs `uaudp.opcode` 0-7 réellement observées dans les captures
    d'exemple portent bien les libellés natifs tshark documentés (jamais
    "OFF_HOOK"/"KEY_PRESSED"/... — hypothèse explicitement invalidée par le
    document)."""
    expected_labels = {
        "0": "Connect",
        "1": "Connect ACK",
        "2": "Release",
        "3": "Release ACK",
        "4": "Keepalive",
        "5": "Keepalive ACK",
        "6": "NACK",
        "7": "Data",
    }
    for pcap_name in (
        "ua3g_freeseating_ipv4.pcap",
        "ua3g_freeseating_ipv6.pcap",
        "uaudp_ipv6.pcap",
    ):
        # `_ws.col.info` (colonne "Info" affichée par défaut) commence par
        # le libellé natif de `uaudp.opcode` ("Connect ACK - ...", "Data
        # ACK", ...) : pas de champ `-T fields` dédié pour le seul libellé
        # textuel d'un `value_string`, `-V`/la colonne Info sont les deux
        # façons standard d'observer ce que tshark affiche réellement,
        # utilisées ailleurs dans ce module et dans le document audité.
        rows = _tshark_field_rows(pcap_name, "uaudp.opcode <= 7", "uaudp.opcode", "_ws.col.info")
        assert rows, pcap_name
        for opcode, info in rows:
            assert info.startswith(expected_labels[opcode]), (pcap_name, opcode, info)
