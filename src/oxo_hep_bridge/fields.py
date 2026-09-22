#!/usr/bin/env python3
"""Fonctions utilitaires partagées pour l'extraction de champs depuis les
paquets tshark -T ek aplatis (flat dict). Utilisées à la fois par
``normalizer.py`` et ``semantics.py``.
"""

from __future__ import annotations

from typing import Any


def pick(value: Any, index: int = 0) -> Any:
    """Retourne value[index] si value est une liste, sinon value tel quel.

    tshark -T ek encode parfois un champ répété (ex: udp.port apparaissant
    deux fois) comme une liste plutôt qu'un scalaire.
    """
    if isinstance(value, list):
        return value[index] if len(value) > index else None
    return value


def as_int(value: Any, default: int = 0) -> int:
    v = pick(value)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def as_str(value: Any, default: str = "") -> str:
    v = pick(value)
    return default if v is None else str(v)


def extract_noe_events(flat: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrait les événements NOE d'un paquet aplati.

    Le champ "noe" peut être un objet unique OU une liste d'objets quand
    plusieurs messages NOE sont empilés dans un seul paquet UA3G. Présent
    dans les captures d'exemple ``ua3g_freeseating_*`` (chaîne de
    dissection complète ``eth:ip:udp:uaudp:ua:noe``, voir
    tests/test_fields.py::test_extract_noe_events_finds_real_events_in_ua3g_freeseating_fixture),
    absent de ``uaudp_ipv6`` (tshark s'arrête à la couche ``uaudp``, voir
    docs/architecture.md#limites-connues).
    """
    noe = flat.get("noe")
    if noe is None:
        return []
    if isinstance(noe, list):
        return [n for n in noe if isinstance(n, dict)]
    if isinstance(noe, dict):
        return [noe]
    return []


def extract_noe_events_flat(flat: dict[str, Any]) -> list[dict[str, Any]]:
    """Comme extract_noe_events, mais retire le préfixe "noe_noe_" des clés
    de chaque événement pour produire des noms de champs propres.
    """
    events = extract_noe_events(flat)
    return [
        {k[len("noe_noe_") :] if k.startswith("noe_noe_") else k: v for k, v in ev.items()}
        for ev in events
    ]


def build_correlation_id(flat: dict[str, Any]) -> str:
    """Construit un identifiant de corrélation UA stable pour une session.

    Faute d'un identifiant de session natif exposé par le dissecteur UAUDP,
    on synthétise une clé à partir des adresses/ports IP. Les endpoints sont
    **canonicalisés** (triés) pour que A→B et B→A produisent le même
    identifiant de flux — indispensable pour corréler les deux sens d'une
    même conversation UDP dans HOMER. Cette heuristique doit être affinée si un
    identifiant plus stable est disponible côté OXO (ex: un identifiant de
    poste/appel, ou le champ ``transaction_id`` si le dissecteur l'expose).
    """
    src_ip = as_str(flat.get("ip_ip_src") or flat.get("ipv6_ipv6_src"))
    dst_ip = as_str(flat.get("ip_ip_dst") or flat.get("ipv6_ipv6_dst"))
    src_port = as_int(flat.get("udp_udp_srcport"))
    dst_port = as_int(flat.get("udp_udp_dstport"))
    endpoint_a = (src_ip, src_port)
    endpoint_b = (dst_ip, dst_port)
    lo, hi = sorted((endpoint_a, endpoint_b))
    return f"{lo[0]}:{lo[1]}-{hi[0]}:{hi[1]}"
