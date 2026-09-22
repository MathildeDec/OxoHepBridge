#!/usr/bin/env python3
"""Tests unitaires de semantics.py — construction/sérialisation de la
payload sémantique. Complète les tests d'intégration sur fixtures pcap
réelles (ci-dessous, pour ``ua3g``) par des cas synthétiques ciblant les cas
limites (champ absent, message unique vs empilé)."""

from __future__ import annotations

from oxo_hep_bridge.semantics import build_semantic_payload, encode_semantic_payload


def _base_flat(**extra):
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5000",
        "udp_udp_dstport": "32640",
    }
    flat.update(extra)
    return flat


def test_build_semantic_payload_includes_ua3g_section_when_present():
    """tshark -T ek imbrique le(s) message(s) UA3G d'un paquet sous une clé
    "ua3g" — un dict pour un message unique (voir docstring du module) —
    jamais des clés "ua3g_ua3g_*" à plat directement dans le paquet aplati."""
    flat = _base_flat(ua3g={"ua3g_ua3g_msg_type": "5", "ua3g_ua3g_len": "12"})
    payload = build_semantic_payload(flat)

    assert payload["ua3g"] == [{"msg_type": "5", "len": "12"}]


def test_build_semantic_payload_stacks_multiple_ua3g_messages_in_one_packet():
    """Un paquet UAUDP opcode 7 peut porter plusieurs messages UA3G empilés
    (jusqu'à 3 observés dans les captures d'exemple) : tshark -T ek les
    représente alors en liste plutôt qu'en dict unique sous "ua3g"."""
    flat = _base_flat(
        ua3g=[
            {"ua3g_ua3g_opcode": "0x29", "ua3g_ua3g_command_main_voice_mode": "0x13"},
            {"ua3g_ua3g_opcode": "0x3f", "ua3g_ua3g_command_mute": False},
        ]
    )
    payload = build_semantic_payload(flat)

    assert payload["ua3g"] == [
        {"opcode": "0x29", "command_main_voice_mode": "0x13"},
        {"opcode": "0x3f", "command_mute": False},
    ]


def test_build_semantic_payload_omits_ua3g_section_when_absent():
    payload = build_semantic_payload(_base_flat())
    assert "ua3g" not in payload


def test_build_semantic_payload_adds_ua3g_opcode_name_when_direction_from_terminal():
    """Port source 32512 (dans UAUDP_TERMINAL_DEFAULT_PORTS) -> message
    Terminal->System, table UA3G_OPCODE_TERM_NAMES (opcode 159 = "Unsolicited
    Message", cas réel de ua3g_freeseating_ipv6.pcap)."""
    flat = _base_flat(
        udp_udp_srcport="32512",
        udp_udp_dstport="32640",
        ua3g={"ua3g_ua3g_opcode": "159"},
    )
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["opcode_name"] == "Unsolicited Message"


def test_build_semantic_payload_adds_ua3g_opcode_name_when_direction_from_system():
    """Port destination 32512 -> message System->Terminal, table
    UA3G_OPCODE_SYS_NAMES (opcode 63 = "Mute", cas réel de
    ua3g_freeseating_ipv4.pcap)."""
    flat = _base_flat(
        udp_udp_srcport="32640",
        udp_udp_dstport="32512",
        ua3g={"ua3g_ua3g_opcode": "63"},
    )
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["opcode_name"] == "Mute"


def test_build_semantic_payload_no_ua3g_opcode_name_when_direction_unknown():
    """Ni le port source ni le port destination n'appartiennent à
    UAUDP_TERMINAL_DEFAULT_PORTS -> sens non déterminable, pas de nom
    inventé (ex: capture faite avec --decode-as sur deux ports non
    standards des deux côtés)."""
    flat = _base_flat(
        udp_udp_srcport="40000",
        udp_udp_dstport="40001",
        ua3g={"ua3g_ua3g_opcode": "63"},
    )
    payload = build_semantic_payload(flat)
    assert "opcode_name" not in payload["ua3g"][0]


def test_build_semantic_payload_no_ua3g_opcode_name_when_opcode_unresolvable():
    flat = _base_flat(
        udp_udp_srcport="32640",
        udp_udp_dstport="32512",
        ua3g={"ua3g_ua3g_opcode": "254"},
    )
    payload = build_semantic_payload(flat)
    assert "opcode_name" not in payload["ua3g"][0]


def test_build_semantic_payload_adds_ua3g_ip_name_for_ip_device_routing_from_system():
    """Message opcode 0x13 "IP Device Routing" côté System->Terminal : champ
    "ip" résolu via UA3G_IP_DEVICE_ROUTING_SYS_NAMES (5 = "Start Tone", cas
    réel de ua3g_freeseating_ipv4.pcap). Pas de déduction par port requise
    pour ce champ : "ip" n'existe que côté système."""
    flat = _base_flat(ua3g={"ua3g_ua3g_opcode": "19", "ua3g_ua3g_ip": "5"})
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["ip_name"] == "Start Tone"
    assert "ip_cs_name" not in payload["ua3g"][0]


def test_build_semantic_payload_adds_ua3g_ip_cs_name_for_ip_device_routing_from_terminal():
    """Message opcode 0x13 côté Terminal->System : champ "ip_cs" résolu via
    UA3G_IP_DEVICE_ROUTING_CS_NAMES (2 = "Get Parameters Value Response",
    cas réel de ua3g_freeseating_ipv6.pcap)."""
    flat = _base_flat(ua3g={"ua3g_ua3g_opcode": "19", "ua3g_ua3g_ip_cs": "2"})
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["ip_cs_name"] == "Get Parameters Value Response"
    assert "ip_name" not in payload["ua3g"][0]


def test_build_semantic_payload_no_ua3g_ip_name_when_unresolvable():
    flat = _base_flat(ua3g={"ua3g_ua3g_opcode": "19", "ua3g_ua3g_ip": "255"})
    payload = build_semantic_payload(flat)
    assert "ip_name" not in payload["ua3g"][0]


def test_build_semantic_payload_never_overwrites_existing_ua3g_ip_name():
    flat = _base_flat(ua3g={"ua3g_ua3g_opcode": "19", "ua3g_ua3g_ip": "5", "ip_name": "deja-la"})
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["ip_name"] == "deja-la"


def test_build_semantic_payload_omits_qos_section_when_absent():
    payload = build_semantic_payload(_base_flat())
    assert "qos" not in payload


def test_build_semantic_payload_omits_noe_section_when_absent():
    payload = build_semantic_payload(_base_flat())
    assert "noe" not in payload


def test_encode_semantic_payload_returns_none_for_non_ua_packet():
    """Un paquet sans champ uaudp/ua3g/noe (ex: bruit DHCP/TFTP) doit être
    signalé comme non exploitable plutôt que sérialisé avec une payload
    vide."""
    assert encode_semantic_payload(_base_flat()) is None


def test_encode_semantic_payload_returns_bytes_when_ua3g_present():
    flat = _base_flat(ua3g={"ua3g_ua3g_msg_type": "5"})
    encoded = encode_semantic_payload(flat)
    assert encoded is not None
    assert b"ua3g" in encoded


def test_encode_semantic_payload_returns_bytes_when_noe_present():
    flat = _base_flat(noe={"noe_noe_class": 128})
    encoded = encode_semantic_payload(flat)
    assert encoded is not None
    assert b"noe" in encoded


def test_build_semantic_payload_extracts_ua3g_from_real_freeseating_fixture(
    ua3g_freeseating_ipv4_flat_lines,
):
    """Garde-fou (session 30) : avant correctif, l'extraction ua3g de
    build_semantic_payload cherchait des clés "ua3g_ua3g_*" à plat dans le
    paquet aplati — un chemin qui ne matchait jamais rien puisque tshark -T
    ek imbrique toujours le(s) message(s) UA3G sous une clé "ua3g" (dict ou
    liste, comme "noe"). Résultat vérifié empiriquement (tshark réel,
    session 30) : la section "ua3g" de la payload JSON n'était jamais
    peuplée sur les 3 captures d'exemple, alors que 11 paquets de
    ua3g_freeseating_ipv4 en portent réellement (opcode, command_mute,
    main_voice_mode...). Ce test fige le comportement corrigé sur données
    réelles plutôt que sur un cas synthétique."""
    payloads = [build_semantic_payload(flat) for flat in ua3g_freeseating_ipv4_flat_lines]
    packets_with_ua3g = [p["ua3g"] for p in payloads if "ua3g" in p]
    assert packets_with_ua3g, "aucun message ua3g trouvé dans la fixture ua3g_freeseating_ipv4"
    assert len(packets_with_ua3g) == 11
    assert all(isinstance(msgs, list) and msgs for msgs in packets_with_ua3g)
    # au moins un message porte un champ ua3g reconnaissable (préfixe retiré)
    assert any("opcode" in msg for msgs in packets_with_ua3g for msg in msgs)
    # le préfixe brut ne doit plus jamais fuiter après extraction
    assert not any(
        k.startswith("ua3g_ua3g_") for msgs in packets_with_ua3g for msg in msgs for k in msg
    )
    # fixture réelle : tous ces messages sont System->Terminal (port source
    # 32640, port destination 32512 dans UAUDP_TERMINAL_DEFAULT_PORTS) ; au
    # moins un opcode connu (41 = "Main Voice Mode") doit être nommé.
    assert any(
        msg.get("opcode_name") == "Main Voice Mode" for msgs in packets_with_ua3g for msg in msgs
    )


def test_build_semantic_payload_adds_ip_name_from_real_freeseating_ipv4_fixture(
    ua3g_freeseating_ipv4_flat_lines,
):
    """Garde-fou sur données réelles (pas seulement synthétiques) : la
    fixture ua3g_freeseating_ipv4 porte des messages opcode 0x13 "IP Device
    Routing" système avec un champ "ip" observé à 5/6/9/10/16/17 — au moins
    "Start Tone" (5) et "Free Seating" (17, cohérent avec le nom du fichier
    de capture) doivent être résolus."""
    payloads = [build_semantic_payload(flat) for flat in ua3g_freeseating_ipv4_flat_lines]
    ip_names = {
        msg.get("ip_name")
        for p in payloads
        for msg in p.get("ua3g", [])
        if msg.get("opcode") == "19"
    }
    assert "Start Tone" in ip_names
    assert "Free Seating" in ip_names


def test_build_semantic_payload_adds_ip_cs_name_from_real_freeseating_ipv6_fixture(
    ua3g_freeseating_ipv6_flat_lines,
):
    """Garde-fou équivalent côté terminal : seule la fixture ipv6 porte des
    messages opcode 0x13 avec un champ "ip_cs" (0 = "Init", 2 = "Get
    Parameters Value Response")."""
    payloads = [build_semantic_payload(flat) for flat in ua3g_freeseating_ipv6_flat_lines]
    ip_cs_names = {
        msg.get("ip_cs_name")
        for p in payloads
        for msg in p.get("ua3g", [])
        if msg.get("opcode") == "19"
    }
    assert "Init" in ip_cs_names
    assert "Get Parameters Value Response" in ip_cs_names


def test_build_semantic_payload_adds_ip_get_param_req_parameter_names_list():
    """Champ répété "ua3g.ip.get_param_req.parameter" (sous-commande 0x09
    "Get Parameters Value") : liste d'identifiants résolue élément par
    élément, alignée sur la liste source (255 = non résolvable, conservé
    comme None plutôt que retiré)."""
    flat = _base_flat(
        ua3g={
            "ua3g_ua3g_opcode": "19",
            "ua3g_ua3g_ip": "9",
            "ua3g_ua3g_ip_get_param_req_parameter": ["3", "255", "10"],
        }
    )
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["ip_get_param_req_parameter_names"] == [
        "Local IP Address",
        None,
        "MAC Address",
    ]


def test_build_semantic_payload_adds_ip_cs_cmd02_parameter_names_list():
    """Champ répété "ua3g.ip.cs.cmd02.parameter" (sous-commande 0x02 "Get
    Parameters Value Response") : mêmes identifiants que la requête 0x09
    (même table), mais avec le doublement consécutif réel observé côté
    dissecteur (voir UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES) — la liste de
    libellés reflète fidèlement le doublement de la liste source."""
    flat = _base_flat(
        ua3g={
            "ua3g_ua3g_opcode": "19",
            "ua3g_ua3g_ip_cs": "2",
            "ua3g_ua3g_ip_cs_cmd02_parameter": ["3", "3", "10", "10"],
        }
    )
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["ip_cs_cmd02_parameter_names"] == [
        "Local IP Address",
        "Local IP Address",
        "MAC Address",
        "MAC Address",
    ]


def test_build_semantic_payload_accepts_lone_scalar_parameter_not_wrapped_in_list():
    """tshark n'encapsule pas toujours un champ répété présent une seule
    fois dans une liste."""
    flat = _base_flat(
        ua3g={
            "ua3g_ua3g_opcode": "19",
            "ua3g_ua3g_ip": "9",
            "ua3g_ua3g_ip_get_param_req_parameter": "3",
        }
    )
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["ip_get_param_req_parameter_names"] == ["Local IP Address"]


def test_build_semantic_payload_no_parameter_names_when_nothing_resolvable():
    flat = _base_flat(
        ua3g={
            "ua3g_ua3g_opcode": "19",
            "ua3g_ua3g_ip": "9",
            "ua3g_ua3g_ip_get_param_req_parameter": ["254", "255"],
        }
    )
    payload = build_semantic_payload(flat)
    assert "ip_get_param_req_parameter_names" not in payload["ua3g"][0]


def test_build_semantic_payload_never_overwrites_existing_parameter_names():
    flat = _base_flat(
        ua3g={
            "ua3g_ua3g_opcode": "19",
            "ua3g_ua3g_ip": "9",
            "ua3g_ua3g_ip_get_param_req_parameter": ["3"],
            "ip_get_param_req_parameter_names": ["deja-la"],
        }
    )
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["ip_get_param_req_parameter_names"] == ["deja-la"]


def test_build_semantic_payload_adds_ip_get_param_req_parameter_names_from_real_fixture(
    ua3g_freeseating_ipv6_flat_lines,
):
    """Garde-fou sur données réelles : la fixture ua3g_freeseating_ipv6
    porte un message opcode 0x13 ip=9 "Get Parameters Value" demandant les
    identifiants 12, 3, 4, 1, 10 (12 non résolvable, absent de la table) —
    au moins "Local IP Address" (3) et "MAC Address" (10) doivent l'être."""
    payloads = [build_semantic_payload(flat) for flat in ua3g_freeseating_ipv6_flat_lines]
    names_lists = [
        msg.get("ip_get_param_req_parameter_names")
        for p in payloads
        for msg in p.get("ua3g", [])
        if msg.get("ip") == "9"
    ]
    assert names_lists, "aucun message ip=9 trouvé dans la fixture"
    flattened = {n for names in names_lists for n in names}
    assert "Local IP Address" in flattened
    assert "MAC Address" in flattened


def test_build_semantic_payload_adds_ip_cs_cmd02_parameter_names_from_real_fixture(
    ua3g_freeseating_ipv6_flat_lines,
):
    """Garde-fou équivalent côté réponse terminal : la fixture porte un
    message opcode 0x13 ip_cs=2 "Get Parameters Value Response" avec des
    identifiants 3/4/1/10 doublés — au moins "Local IP Address" (3) et
    "MAC Address" (10) doivent être résolus, avec le doublement préservé."""
    payloads = [build_semantic_payload(flat) for flat in ua3g_freeseating_ipv6_flat_lines]
    names_lists = [
        msg.get("ip_cs_cmd02_parameter_names")
        for p in payloads
        for msg in p.get("ua3g", [])
        if msg.get("ip_cs") == "2"
    ]
    assert names_lists, "aucun message ip_cs=2 trouvé dans la fixture"
    names = names_lists[0]
    assert "Local IP Address" in names
    assert "MAC Address" in names
    assert names.count("Local IP Address") == 2  # doublement réel, voir docstring du test ci-dessus


def test_build_semantic_payload_adds_ip_set_param_req_parameter_names_list():
    """Champ répété "ua3g.ip.set_param_req.parameter" (sous-commande 0x0A
    "Set Parameters Value", requête système) : table de résolution dédiée
    et distincte de celle de get_param_req/cmd02 (voir
    UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES). Comme cmd02, ce champ
    porte lui aussi un doublement consécutif réel côté dissecteur (session
    34) — mais ici côté requête système, pas réponse terminal."""
    flat = _base_flat(
        ua3g={
            "ua3g_ua3g_opcode": "19",
            "ua3g_ua3g_ip": "10",
            "ua3g_ua3g_ip_set_param_req_parameter": ["3", "3", "255", "255"],
        }
    )
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["ip_set_param_req_parameter_names"] == [
        "SNMP MIB2 SysContact",
        "SNMP MIB2 SysContact",
        None,
        None,
    ]


def test_build_semantic_payload_no_set_param_req_parameter_names_when_nothing_resolvable():
    flat = _base_flat(
        ua3g={
            "ua3g_ua3g_opcode": "19",
            "ua3g_ua3g_ip": "10",
            "ua3g_ua3g_ip_set_param_req_parameter": ["254", "254"],
        }
    )
    payload = build_semantic_payload(flat)
    assert "ip_set_param_req_parameter_names" not in payload["ua3g"][0]


def test_build_semantic_payload_adds_ip_set_param_req_parameter_names_from_real_fixture(
    ua3g_freeseating_ipv6_flat_lines,
):
    """Garde-fou sur données réelles : la fixture ua3g_freeseating_ipv6
    porte 23 messages opcode 0x13 ip=10 "Set Parameters Value" — tous avec
    un doublement consécutif de chaque identifiant (vérifié sur les 23),
    ex. un message demandant SNMP MIB2 SysContact/SysName/SysLocation
    (identifiants 3/4/5, chacun doublé)."""
    payloads = [build_semantic_payload(flat) for flat in ua3g_freeseating_ipv6_flat_lines]
    names_lists = [
        msg.get("ip_set_param_req_parameter_names")
        for p in payloads
        for msg in p.get("ua3g", [])
        if msg.get("ip") == "10"
    ]
    assert names_lists, "aucun message ip=10 trouvé dans la fixture"
    assert len(names_lists) == 23
    assert [
        "SNMP MIB2 SysContact",
        "SNMP MIB2 SysContact",
        "SNMP MIB2 SysName",
        "SNMP MIB2 SysName",
        "SNMP MIB2 SysLocation",
        "SNMP MIB2 SysLocation",
    ] in names_lists
    # doublement consécutif systématique : chaque liste a une longueur
    # paire et chaque paire d'éléments consécutifs est identique.
    for names in names_lists:
        assert len(names) % 2 == 0
        for i in range(0, len(names), 2):
            assert names[i] == names[i + 1]


def test_build_semantic_payload_adds_ip_freeseating_parameter_names_list():
    """Champ répété "ua3g.ip.freeseating.parameter" (sous-commande 0x11
    "Free Seating", requête système) : table de résolution dédiée
    UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES (4 entrées
    seulement). Comme set_param_req, ce champ porte lui aussi un
    doublement consécutif réel côté dissecteur."""
    flat = _base_flat(
        ua3g={
            "ua3g_ua3g_opcode": "19",
            "ua3g_ua3g_ip": "17",
            "ua3g_ua3g_ip_freeseating_parameter": ["0", "0", "1", "1"],
        }
    )
    payload = build_semantic_payload(flat)
    assert payload["ua3g"][0]["ip_freeseating_parameter_names"] == [
        "Pseudo MAC Address",
        "Pseudo MAC Address",
        "Maincpu1",
        "Maincpu1",
    ]


def test_build_semantic_payload_no_freeseating_parameter_names_when_nothing_resolvable():
    flat = _base_flat(
        ua3g={
            "ua3g_ua3g_opcode": "19",
            "ua3g_ua3g_ip": "17",
            "ua3g_ua3g_ip_freeseating_parameter": ["254", "254"],
        }
    )
    payload = build_semantic_payload(flat)
    assert "ip_freeseating_parameter_names" not in payload["ua3g"][0]


def test_build_semantic_payload_adds_ip_freeseating_parameter_names_from_real_fixture(
    ua3g_freeseating_ipv6_flat_lines,
):
    """Garde-fou sur données réelles : la fixture ua3g_freeseating_ipv6
    porte un message opcode 0x13 ip=17 "Free Seating" avec l'identifiant
    brut [0, 0, 1, 1, 2, 2] (Pseudo MAC Address, Maincpu1, Maincpu2, tous
    doublés) — cohérent avec le nom du fichier de capture."""
    payloads = [build_semantic_payload(flat) for flat in ua3g_freeseating_ipv6_flat_lines]
    names_lists = [
        msg.get("ip_freeseating_parameter_names")
        for p in payloads
        for msg in p.get("ua3g", [])
        if msg.get("ip") == "17"
    ]
    assert names_lists, "aucun message ip=17 trouvé dans la fixture"
    assert names_lists[0] == [
        "Pseudo MAC Address",
        "Pseudo MAC Address",
        "Maincpu1",
        "Maincpu1",
        "Maincpu2",
        "Maincpu2",
    ]
