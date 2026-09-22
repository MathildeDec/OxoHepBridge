#!/usr/bin/env python3
"""Garde-fou de complétude — nommage IP Device Routing (opcode UA3G 0x13).

Contexte (session 38) : en creusant le candidat 0x14 "Application
Parameters" (finalement absent des captures, voir docs/roadmap.md), un
audit manuel avec `tshark` réel a listé toutes les valeurs réellement
présentes dans `sample_captures/*.pcap` pour "ua3g.ip", "ua3g.ip.cs" et les
quatre champs répétés d'identifiant de paramètre — confirmant qu'elles
sont toutes déjà couvertes par une table de `ua_opcode_names.py`, sauf
l'identifiant 0x0C (12) sur "ua3g.ip.get_param_req.parameter"/
"ua3g.ip.cs.cmd02.parameter", absent aussi de la table officielle
Wireshark `ip_device_routing_cmd_get_param_req_vals[]` (qui s'arrête à
0x0B) — pas une lacune du projet.

Ce module automatise cet audit ponctuel plutôt que de le refaire à la main
à chaque session future : si une prochaine capture d'exemple introduit une
sous-commande ou un identifiant de paramètre non couvert (et non déjà
listé dans `KNOWN_UNRESOLVED_PARAMETER_IDS` ci-dessous), ces tests
échouent au lieu de laisser passer une lacune de nommage inaperçue — même
esprit que `test_ci_config.py`/`test_docs.py` : vérifier le comportement
réel plutôt que relire le code à l'œil.

Ignorés (skip) si `tshark` n'est pas utilisable, comme
`test_real_tshark_integration.py::requires_real_tshark`
(duplication volontaire du détecteur : ces deux modules restent
indépendants l'un de l'autre par conception, comme
`test_sender.py::requires_ipv6`).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from oxo_hep_bridge.ua_opcode_names import (
    UA3G_IP_DEVICE_ROUTING_CS_NAMES,
    UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES,
    UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES,
    UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES,
    UA3G_IP_DEVICE_ROUTING_SYS_NAMES,
)

REPO_ROOT = Path(__file__).parent.parent
SAMPLE_CAPTURES = REPO_ROOT / "sample_captures"

# Identifiants confirmés absents même de la table officielle Wireshark
# amont (val_to_str_const y retomberait sur "Unknown") — à ne pas confondre
# avec une lacune du projet. Clé : nom du champ tshark, valeur : ensemble
# des identifiants tolérés comme non résolvables.
KNOWN_UNRESOLVED_PARAMETER_IDS: dict[str, frozenset[int]] = {
    # ip_device_routing_cmd_get_param_req_vals[] (packet-ua3g.c) s'arrête à
    # 0x0B ("Pseudo MAC Address") ; 0x0C apparaît pourtant dans
    # ua3g_freeseating_ipv6.pcap (poste réel demandant un paramètre que le
    # dissecteur amont lui-même ne documente pas).
    "ua3g.ip.get_param_req.parameter": frozenset({0x0C}),
    "ua3g.ip.cs.cmd02.parameter": frozenset({0x0C}),
}


def _real_tshark_available() -> bool:
    """Cf. test_real_tshark_integration.py::_real_tshark_available —
    détecteur dupliqué volontairement, voir docstring du module."""
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


def _field_values(field: str) -> set[int]:
    """Valeurs entières distinctes d'un champ tshark répété, sur les trois
    captures d'exemple — chaque ligne peut contenir plusieurs valeurs
    séparées par des virgules (plusieurs occurrences du champ dans une
    même trame)."""
    values: set[int] = set()
    for pcap in sorted(SAMPLE_CAPTURES.glob("*.pcap")):
        result = subprocess.run(  # noqa: S603
            ["tshark", "-r", str(pcap), "-Y", field, "-T", "fields", "-e", field],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        for line in result.stdout.splitlines():
            for raw_token in line.split(","):
                token = raw_token.strip()
                if token:
                    values.add(int(token, 0) if token.startswith("0x") else int(token))
    return values


@requires_real_tshark
def test_ua3g_ip_sys_values_in_sample_captures_are_all_documented():
    """Toute sous-commande "ua3g.ip" (System->Terminal) réellement présente
    dans les captures d'exemple doit être dans
    UA3G_IP_DEVICE_ROUTING_SYS_NAMES."""
    values = _field_values("ua3g.ip")
    assert values, "aucune valeur ua3g.ip trouvée dans sample_captures/"
    undocumented = {v for v in values if v not in UA3G_IP_DEVICE_ROUTING_SYS_NAMES}
    assert not undocumented, (
        f"sous-commande(s) ua3g.ip non documentée(s) dans "
        f"UA3G_IP_DEVICE_ROUTING_SYS_NAMES : {sorted(hex(v) for v in undocumented)}"
    )


@requires_real_tshark
def test_ua3g_ip_cs_values_in_sample_captures_are_all_documented():
    """Toute sous-commande "ua3g.ip.cs" (Terminal->System) réellement
    présente dans les captures d'exemple doit être dans
    UA3G_IP_DEVICE_ROUTING_CS_NAMES."""
    values = _field_values("ua3g.ip.cs")
    assert values, "aucune valeur ua3g.ip.cs trouvée dans sample_captures/"
    undocumented = {v for v in values if v not in UA3G_IP_DEVICE_ROUTING_CS_NAMES}
    assert not undocumented, (
        f"sous-commande(s) ua3g.ip.cs non documentée(s) dans "
        f"UA3G_IP_DEVICE_ROUTING_CS_NAMES : {sorted(hex(v) for v in undocumented)}"
    )


@pytest.mark.parametrize(
    ("field", "table"),
    [
        ("ua3g.ip.get_param_req.parameter", UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES),
        ("ua3g.ip.cs.cmd02.parameter", UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES),
        ("ua3g.ip.set_param_req.parameter", UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES),
        ("ua3g.ip.freeseating.parameter", UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES),
    ],
)
@requires_real_tshark
def test_ua3g_ip_parameter_ids_in_sample_captures_are_documented_or_known_gaps(
    field: str, table: dict[int, str]
) -> None:
    """Tout identifiant de paramètre réellement présent dans les captures
    d'exemple doit être résolu par la table dédiée, sauf s'il figure dans
    KNOWN_UNRESOLVED_PARAMETER_IDS (lacune confirmée de la table officielle
    Wireshark amont, pas du projet)."""
    values = _field_values(field)
    if not values:
        pytest.skip(f"aucune valeur {field} trouvée dans sample_captures/")
    known_gaps = KNOWN_UNRESOLVED_PARAMETER_IDS.get(field, frozenset())
    undocumented = {v for v in values if v not in table and v not in known_gaps}
    assert not undocumented, (
        f"identifiant(s) {field} non documenté(s) et non listé(s) comme "
        f"lacune connue : {sorted(hex(v) for v in undocumented)}"
    )
