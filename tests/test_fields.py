#!/usr/bin/env python3
"""Tests unitaires de fields.py — fonctions utilitaires partagées par
normalizer.py/semantics.py, jusqu'ici seulement exercées indirectement via
ces deux modules (fixtures pcap réelles). Ce fichier cible spécifiquement les
cas limites (valeurs manquantes/malformées) plus faciles à isoler ici."""

from __future__ import annotations

from oxo_hep_bridge.fields import (
    as_int,
    as_str,
    build_correlation_id,
    extract_noe_events,
    extract_noe_events_flat,
    pick,
)


def test_extract_noe_events_finds_real_events_in_ua3g_freeseating_fixture(
    ua3g_freeseating_ipv4_flat_lines,
):
    """Garde-fou : le docstring de extract_noe_events affirmait à tort que
    le champ "noe" n'apparaît dans aucune capture d'exemple — faux, la
    fixture ua3g_freeseating_ipv4 (chaîne de dissection complète
    eth:ip:udp:uaudp:ua:noe) en contient réellement. Utilise la fixture
    conftest.ua3g_freeseating_ipv4_flat_lines, jusqu'ici définie mais
    inutilisée par aucun test."""
    events_per_packet = [extract_noe_events(flat) for flat in ua3g_freeseating_ipv4_flat_lines]
    packets_with_noe = [events for events in events_per_packet if events]
    assert packets_with_noe, "aucun événement NOE trouvé dans la fixture ua3g_freeseating_ipv4"
    # au moins un événement porte un champ NOE reconnaissable (pas un dict vide)
    assert any("noe_noe_class" in ev for events in packets_with_noe for ev in events)


def test_uaudp_opcode_16_23_content_loss_matches_documented_figure(
    uaudp_ipv6_flat_lines,
):
    """Garde-fou : docs/architecture.md#limites-connues, README.md et
    noe-ua3g-homer-mapping.md#6ter affirmaient qu'~12 % des trames uaudp de
    la fixture uaudp_ipv6 portent un opcode >= 16 (canal local, contenu NOE
    perdu par le dissecteur Wireshark upstream) — chiffre jamais recalculé
    depuis son estimation initiale (session 16). Un comptage réel donne
    163/993 trames uaudp, soit ~16 %, pas ~12 % (voir CHANGELOG session 20).
    Ce test fige le chiffre exact pour éviter une nouvelle dérive silencieuse
    entre la doc et le comportement réel."""
    uaudp_packets = [f for f in uaudp_ipv6_flat_lines if "uaudp_uaudp_opcode" in f]
    flagged = [f for f in uaudp_packets if as_int(f["uaudp_uaudp_opcode"]) >= 16]
    assert len(uaudp_packets) == 993
    assert len(flagged) == 163
    # confirme la perte de contenu : aucune de ces trames flaggées ne porte
    # de sous-couche ua/noe (extract_noe_events dépend entièrement de tshark)
    assert all(not extract_noe_events(f) for f in flagged)


# --- Session 43 : audit documentaire (backlog docs/roadmap.md vide) --------
#
# Le total agrégé ci-dessus (163/993) est protégé depuis la session 20, mais
# le détail par opcode et la « rythmique observée » de la table
# docs/noe-ua3g-homer-mapping.md#6ter ne l'étaient par aucun test — trouvé en
# vérifiant empiriquement cette table contre la fixture réelle (conforme à
# docs/session-protocol.md : backlog vide => vérifier les affirmations
# documentaires existantes plutôt que rester sans rien produire). Les deux
# tests suivants étendent la même protection au reste de la table.


def test_uaudp_opcode_16_23_per_opcode_breakdown_matches_documented_table(
    uaudp_ipv6_flat_lines,
):
    """Garde-fou (session 43) : la colonne « Occurrences » de la table
    « Le motif » (noe-ua3g-homer-mapping.md#6ter) donne, par opcode
    16-23 : 9/6/11/1/24/24/1/87. Vérifié par un comptage réel — exact au
    moment de l'écriture de ce test. Fige le détail pour éviter une dérive
    silencieuse (seul le total 163 était protégé jusqu'ici, voir le test
    précédent)."""
    uaudp_packets = [f for f in uaudp_ipv6_flat_lines if "uaudp_uaudp_opcode" in f]
    counts: dict[int, int] = {}
    for f in uaudp_packets:
        opcode = as_int(f["uaudp_uaudp_opcode"])
        if opcode >= 16:
            counts[opcode] = counts.get(opcode, 0) + 1
    assert counts == {16: 9, 17: 6, 18: 11, 19: 1, 20: 24, 21: 24, 22: 1, 23: 87}


def test_uaudp_opcode_16_burst_rhythm_matches_documented_timing(uaudp_ipv6_flat_lines):
    """Garde-fou (session 43) : la « rythmique observée » documentée pour
    l'opcode 16 (Connect+0x10) — trois rafales débutant à ~33,0 s / ~191,4 s
    / ~350,0 s (temps relatif de capture), espacées de ~158,5 s quasi pile.
    Regroupe les temps par rafale (écart > 5 s = nouvelle rafale ; les
    échanges d'une même rafale documentée sont espacés de l'ordre de la
    seconde, largement sous ce seuil) plutôt que de figer un nombre fixe de
    trames par rafale."""
    times = sorted(
        float(pick(f["frame_frame_time_relative"]))
        for f in uaudp_ipv6_flat_lines
        if "uaudp_uaudp_opcode" in f and as_int(f["uaudp_uaudp_opcode"]) == 16
    )
    bursts: list[list[float]] = [[times[0]]]
    for t in times[1:]:
        if t - bursts[-1][-1] > 5:
            bursts.append([t])
        else:
            bursts[-1].append(t)
    burst_starts = [round(b[0], 1) for b in bursts]
    assert burst_starts == [33.0, 191.4, 350.0]
    gaps = [round(b - a, 1) for a, b in zip(burst_starts, burst_starts[1:], strict=False)]
    assert all(158.0 <= gap <= 159.0 for gap in gaps)


def test_uaudp_opcode_20_rhythm_matches_documented_timing(uaudp_ipv6_flat_lines):
    """Garde-fou (session 43) : rythme « ~15,1 s » documenté pour
    Keepalive+0x10 (opcode 20) — le plus stable des quatre rythmes de la
    table (24 occurrences, intervalle quasi constant d'une trame à
    l'autre), donc le meilleur candidat de non-régression parmi eux."""
    times = sorted(
        float(pick(f["frame_frame_time_relative"]))
        for f in uaudp_ipv6_flat_lines
        if "uaudp_uaudp_opcode" in f and as_int(f["uaudp_uaudp_opcode"]) == 20
    )
    intervals = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert len(intervals) == 23  # 24 occurrences => 23 écarts consécutifs
    assert all(15.0 <= i <= 15.2 for i in intervals)


def test_pick_returns_scalar_unchanged():
    assert pick("foo") == "foo"
    assert pick(42) == 42
    assert pick(None) is None


def test_pick_returns_indexed_element_of_list():
    assert pick(["a", "b"]) == "a"
    assert pick(["a", "b"], index=1) == "b"


def test_pick_returns_none_when_index_out_of_range():
    assert pick(["a"], index=5) is None


def test_as_int_parses_valid_string():
    assert as_int("42") == 42


def test_as_int_returns_default_on_missing_value():
    assert as_int(None) == 0
    assert as_int(None, default=-1) == -1


def test_as_int_returns_default_on_unparsable_value():
    """Une chaîne non numérique (ex: champ tshark inattendu) ne doit pas
    lever, mais retomber sur le défaut."""
    assert as_int("not-a-number") == 0
    assert as_int("not-a-number", default=99) == 99


def test_as_int_returns_default_on_unparsable_type():
    """Un type qui n'est ni str ni int (ex: dict imbriqué mal formé côté
    tshark) doit aussi retomber sur le défaut plutôt que de lever TypeError."""
    assert as_int({"unexpected": "dict"}) == 0


def test_as_int_picks_from_list_before_parsing():
    assert as_int(["7", "8"]) == 7


def test_as_str_returns_default_on_missing_value():
    assert as_str(None) == ""
    assert as_str(None, default="n/a") == "n/a"


def test_as_str_stringifies_non_string_values():
    assert as_str(42) == "42"


def test_extract_noe_events_returns_empty_list_when_field_absent():
    assert extract_noe_events({}) == []


def test_extract_noe_events_wraps_single_dict_in_list():
    flat = {"noe": {"noe_noe_class": 128}}
    assert extract_noe_events(flat) == [{"noe_noe_class": 128}]


def test_extract_noe_events_passes_through_list_of_dicts():
    flat = {"noe": [{"noe_noe_class": 128}, {"noe_noe_class": 21}]}
    assert extract_noe_events(flat) == [{"noe_noe_class": 128}, {"noe_noe_class": 21}]


def test_extract_noe_events_filters_out_non_dict_list_items():
    """Un dissecteur qui produirait une liste mixte (bruit non-dict) ne doit
    pas faire planter l'extraction : les éléments non-dict sont ignorés."""
    flat = {"noe": [{"noe_noe_class": 128}, "unexpected-string", None]}
    assert extract_noe_events(flat) == [{"noe_noe_class": 128}]


def test_extract_noe_events_returns_empty_list_for_unexpected_type():
    """Un champ "noe" qui ne serait ni dict ni liste (ex: scalaire) doit
    retomber sur une liste vide plutôt que de lever."""
    assert extract_noe_events({"noe": "unexpected-scalar"}) == []


def test_extract_noe_events_flat_strips_noe_noe_prefix():
    flat = {"noe": {"noe_noe_class": 128, "noe_noe_method": 2}}
    assert extract_noe_events_flat(flat) == [{"class": 128, "method": 2}]


def test_extract_noe_events_flat_leaves_unprefixed_keys_unchanged():
    flat = {"noe": {"class": 128, "other_field": "x"}}
    assert extract_noe_events_flat(flat) == [{"class": 128, "other_field": "x"}]


def test_extract_noe_events_flat_returns_empty_list_when_no_events():
    assert extract_noe_events_flat({}) == []


def test_build_correlation_id_canonicalizes_endpoint_order():
    """A->B et B->A doivent produire le même identifiant (endpoints triés)."""
    flat_a_to_b = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5000",
        "udp_udp_dstport": "32640",
    }
    flat_b_to_a = {
        "ip_ip_src": "10.0.0.2",
        "ip_ip_dst": "10.0.0.1",
        "udp_udp_srcport": "32640",
        "udp_udp_dstport": "5000",
    }
    assert build_correlation_id(flat_a_to_b) == build_correlation_id(flat_b_to_a)


def test_build_correlation_id_falls_back_to_ipv6_fields_when_ipv4_absent():
    flat = {
        "ipv6_ipv6_src": "fe80::1",
        "ipv6_ipv6_dst": "fe80::2",
        "udp_udp_srcport": "5000",
        "udp_udp_dstport": "32640",
    }
    corr_id = build_correlation_id(flat)
    assert "fe80::1" in corr_id
    assert "fe80::2" in corr_id
