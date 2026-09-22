#!/usr/bin/env python3
"""Tests des dictionnaires de noms officiels UAUDP/NOE
(``oxo_hep_bridge.ua_opcode_names``) et de leur intégration dans la payload
sémantique (``semantics.annotate_noe_event`` / ``build_semantic_payload``).

Les valeurs numériques utilisées ici (opcode 7, classe 128, méthode 2,
serveur 21, propriété 40...) sont recoupées avec les valeurs brutes
réellement observées dans ``tests/fixtures/ua3g_freeseating_ipv4.ek.ndjson``
(paquet contenant un SetProperty "visible" sur une FrameBox via le Call
Server) — pas des valeurs inventées pour les besoins du test.
"""

from __future__ import annotations

import json

from oxo_hep_bridge.normalizer import normalize
from oxo_hep_bridge.semantics import annotate_noe_event, build_semantic_payload
from oxo_hep_bridge.ua_opcode_names import (
    NOE_CLASS_NAMES,
    NOE_ERRCODE_NAMES,
    NOE_EVENT_NAMES,
    NOE_METHOD_NAMES,
    NOE_PROPERTY_NAMES,
    NOE_SERVER_NAMES,
    UA3G_IP_DEVICE_ROUTING_CS_NAMES,
    UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES,
    UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES,
    UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES,
    UA3G_IP_DEVICE_ROUTING_SYS_NAMES,
    UA3G_OPCODE_SYS_NAMES,
    UA3G_OPCODE_TERM_NAMES,
    UAUDP_OPCODE_NAMES,
    UAUDP_TERMINAL_DEFAULT_PORTS,
    decode_name,
    decode_names,
)


def test_uaudp_opcode_names_match_official_dissector_table():
    """Les 8 opcodes UAUDP définis par le dissecteur ALE (packet-uaudp.c)."""
    assert UAUDP_OPCODE_NAMES == {
        0: "Connect",
        1: "Connect ACK",
        2: "Release",
        3: "Release ACK",
        4: "Keepalive",
        5: "Keepalive ACK",
        6: "NACK",
        7: "Data",
    }


def test_noe_event_names_include_hookswitch_events():
    """EVT_ONHOOK / EVT_OFFHOOK sont les noms officiels utilisés dans le
    mapping conceptuel de docs/noe-ua3g-homer-mapping.md §3 — vérifier
    qu'ils sont bien résolus depuis la table sourcée."""
    assert NOE_EVENT_NAMES[6] == "EVT_ONHOOK"
    assert NOE_EVENT_NAMES[7] == "EVT_OFFHOOK"


def test_noe_server_names():
    assert NOE_SERVER_NAMES == {0x15: "Call Server", 0x16: "Presentation Server"}


def test_noe_method_names():
    assert NOE_METHOD_NAMES[2] == "SetProperty"
    assert NOE_METHOD_NAMES[4] == "Notify"


def test_decode_name_returns_none_for_unresolvable_value():
    assert decode_name(UAUDP_OPCODE_NAMES, None) is None
    assert decode_name(UAUDP_OPCODE_NAMES, "not-a-number") is None
    assert decode_name(UAUDP_OPCODE_NAMES, 255) is None  # pas dans la table


def test_decode_name_accepts_str_and_int():
    assert decode_name(UAUDP_OPCODE_NAMES, "7") == "Data"
    assert decode_name(UAUDP_OPCODE_NAMES, 7) == "Data"


def test_annotate_noe_event_resolves_all_known_fields():
    """Cas réel recoupé avec le fixture ua3g_freeseating_ipv4 : SetProperty
    "visible" sur une FrameBox (classe 128) via le Call Server (0x15)."""
    event = annotate_noe_event(
        {
            "objectid": "4867",
            "class": "128",
            "method": "2",
            "server": "21",
            "property": "40",
        }
    )
    assert event["class_name"] == "FrameBox"
    assert event["method_name"] == "SetProperty"
    assert event["server_name"] == "Call Server"
    assert event["property_name"] == "visible"
    # le champ numérique d'origine reste intact
    assert event["class"] == "128"


def test_annotate_noe_event_never_overwrites_existing_name_field():
    event = annotate_noe_event({"class": "128", "class_name": "deja-la"})
    assert event["class_name"] == "deja-la"


def test_annotate_noe_event_resolves_hex_server_and_property_as_emitted_by_tshark():
    """Non-régression : tshark rend `server`/`property`/`objectid` du
    dissecteur packet-noe.c en hexadécimal préfixé ("0x15", "0x28"), pas en
    décimal — contrairement à `class`/`method`/`event` ("128", "2"). Vérifié
    directement sur sample_captures/uaudp_ipv6.pcap (`tshark -T ek`) et sur
    ua3g_freeseating_ipv4/ipv6.pcap (503 événements NOE réels). Avant le fix
    de `decode_name()` (int(value) sans base=0), server_name/property_name
    n'étaient jamais résolus sur du trafic réel malgré des tables correctes
    — le test ci-dessus (`test_annotate_noe_event_resolves_all_known_fields`)
    ne le détectait pas car il utilise des valeurs décimales inventées.
    """
    event = annotate_noe_event(
        {
            "objectid": "0x1303",
            "class": "128",
            "method": "2",
            "server": "0x15",
            "property": "0x28",
        }
    )
    assert event["server_name"] == "Call Server"
    assert event["property_name"] == "visible"


def test_annotate_noe_event_skips_unresolvable_or_missing_values():
    event = annotate_noe_event({"objectid": "4867", "class": "not-a-class"})
    assert "class_name" not in event
    event2 = annotate_noe_event({"objectid": "4867"})
    assert "class_name" not in event2


def test_build_semantic_payload_adds_uaudp_opcode_name():
    flat = {"uaudp_uaudp_opcode": "7"}
    payload = build_semantic_payload(flat)
    assert payload["uaudp"]["opcode"] == "7"
    assert payload["uaudp"]["opcode_name"] == "Data"


def test_build_semantic_payload_no_opcode_name_when_unresolvable():
    """opcode 99 n'existe pas dans le dissecteur -> pas de nom inventé."""
    flat = {"uaudp_uaudp_opcode": "99"}
    payload = build_semantic_payload(flat)
    assert "opcode_name" not in payload["uaudp"]


def test_normalize_end_to_end_includes_noe_names():
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5060",
        "udp_udp_dstport": "32640",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "uaudp_uaudp_opcode": "7",
        "noe": [
            {
                "noe_noe_objectid": "4867",
                "noe_noe_class": "128",
                "noe_noe_method": "2",
                "noe_noe_server": "21",
                "noe_noe_property": "40",
            }
        ],
    }
    pkt = normalize(flat, capture_agent_id=2001)
    assert pkt is not None
    payload = json.loads(pkt.payload.decode("utf-8"))
    assert payload["uaudp"]["opcode_name"] == "Data"
    assert payload["noe"][0]["class_name"] == "FrameBox"
    assert payload["noe"][0]["method_name"] == "SetProperty"
    assert payload["noe"][0]["server_name"] == "Call Server"
    assert payload["noe"][0]["property_name"] == "visible"


def test_all_tables_are_non_empty_and_keys_are_ints():
    for table in (
        UAUDP_OPCODE_NAMES,
        NOE_CLASS_NAMES,
        NOE_METHOD_NAMES,
        NOE_SERVER_NAMES,
        NOE_EVENT_NAMES,
        NOE_ERRCODE_NAMES,
        NOE_PROPERTY_NAMES,
        UA3G_OPCODE_SYS_NAMES,
        UA3G_OPCODE_TERM_NAMES,
        UA3G_IP_DEVICE_ROUTING_SYS_NAMES,
        UA3G_IP_DEVICE_ROUTING_CS_NAMES,
        UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES,
        UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES,
    ):
        assert table
        assert all(isinstance(k, int) for k in table)
        assert all(isinstance(v, str) and v for v in table.values())


def test_ua3g_opcode_tables_match_fixture_observations():
    """Valeurs recoupées avec les messages UA3G réels de
    ua3g_freeseating_ipv4/ipv6.ek.ndjson (port 32640 = système, 32512 =
    terminal, voir docstring de ua_opcode_names) : les deux tables ne se
    fusionnent pas, chacune doit rester correcte pour son sens.
    """
    # opcode 0x13 (19) : même libellé "IP Device Routing" dans les deux
    # tables (SC_IP_DEVICE_ROUTING == CS_IP_DEVICE_ROUTING == 0x13) — observé
    # dans les deux sens sur ua3g_freeseating_ipv4/ipv6.
    assert UA3G_OPCODE_SYS_NAMES[0x13] == "IP Device Routing"
    assert UA3G_OPCODE_TERM_NAMES[0x13] == "IP Device Routing"
    # opcode 3 : ambigu entre les deux tables -> confirme qu'une fusion serait
    # fausse la moitié du temps (Software Reset vs Digital Dialed).
    assert UA3G_OPCODE_SYS_NAMES[3] == "Software Reset"
    assert UA3G_OPCODE_TERM_NAMES[3] == "Digital Dialed"
    # opcodes uniquement observés côté terminal dans les fixtures.
    assert UA3G_OPCODE_TERM_NAMES[159] == "Unsolicited Message"
    assert UA3G_OPCODE_TERM_NAMES[33] == "Version Information"
    # opcodes uniquement observés côté système dans les fixtures.
    assert UA3G_OPCODE_SYS_NAMES[41] == "Main Voice Mode"
    assert UA3G_OPCODE_SYS_NAMES[63] == "Mute"


def test_ua3g_ip_device_routing_sys_names_match_official_dissector_table():
    """str_command_ip_device_routing[] (packet-ua3g.c), champ ua3g.ip —
    sous-commande d'un message opcode 0x13 côté System->Terminal."""
    assert UA3G_IP_DEVICE_ROUTING_SYS_NAMES == {
        0x00: "Reset",
        0x01: "Start RTP",
        0x02: "Stop RTP",
        0x03: "Redirect",
        0x04: "Tone Definition",
        0x05: "Start Tone",
        0x06: "Stop Tone",
        0x07: "Start Listen RTP",
        0x08: "Stop Listen RTP",
        0x09: "Get Parameters Value",
        0x0A: "Set Parameters Value",
        0x0B: "Send Digit",
        0x0C: "Pause RTP",
        0x0D: "Restart RTP",
        0x0E: "Start Record RTP",
        0x0F: "Stop Record RTP",
        0x10: "Set SIP Parameters",
        0x11: "Free Seating",
        0x14: "Application Parameters",
    }


def test_ua3g_ip_device_routing_cs_names_match_official_dissector_table():
    """str_command_cs_ip_device_routing[] (packet-ua3g.c), champ
    ua3g.ip.cs — sous-commande d'un message opcode 0x13 côté
    Terminal->System."""
    assert UA3G_IP_DEVICE_ROUTING_CS_NAMES == {
        0x00: "Init",
        0x01: "Incident",
        0x02: "Get Parameters Value Response",
        0x03: "QOS Ticket RSP",
    }


def test_ua3g_ip_device_routing_tables_match_fixture_observations():
    """Valeurs recoupées avec les messages UA3G opcode 0x13 réels de
    ua3g_freeseating_ipv4/ipv6.ek.ndjson : champ "ip" (System->Terminal,
    port destination 32512) observé à 4, 5, 6, 9, 10, 16, 17 ; champ
    "ip_cs" (Terminal->System, port source 32512, uniquement dans la
    fixture ipv6) observé à 0 et 2."""
    assert UA3G_IP_DEVICE_ROUTING_SYS_NAMES[5] == "Start Tone"
    assert UA3G_IP_DEVICE_ROUTING_SYS_NAMES[6] == "Stop Tone"
    assert UA3G_IP_DEVICE_ROUTING_SYS_NAMES[0x0A] == "Set Parameters Value"
    assert UA3G_IP_DEVICE_ROUTING_SYS_NAMES[0x11] == "Free Seating"
    assert UA3G_IP_DEVICE_ROUTING_CS_NAMES[0] == "Init"
    assert UA3G_IP_DEVICE_ROUTING_CS_NAMES[2] == "Get Parameters Value Response"


def test_ua3g_ip_device_routing_parameter_names_match_official_dissector_table():
    """ip_device_routing_cmd_get_param_req_vals[] (packet-ua3g.c), partagée
    par "ua3g.ip.get_param_req.parameter" (requête, sous-commande 0x09) et
    "ua3g.ip.cs.cmd02.parameter" (réponse, sous-commande 0x02) — deux
    entrées distinctes (0x00 et 0x01) pointent vers le même libellé
    "Firmware Version" dans le dissecteur, pas une erreur de recopie."""
    assert UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES == {
        0x00: "Firmware Version",
        0x01: "Firmware Version",
        0x02: "DHCP IP Address",
        0x03: "Local IP Address",
        0x04: "Subnetwork Mask",
        0x05: "Router IP Address",
        0x06: "TFTP IP Address",
        0x07: "MainCPU IP Address",
        0x08: "Default Codec",
        0x09: "Ethernet Drivers Config",
        0x0A: "MAC Address",
        0x0B: "Pseudo MAC Address",
    }


def test_ua3g_ip_device_routing_parameter_names_match_fixture_observations():
    """Valeurs recoupées avec les messages UA3G opcode 0x13 réels
    (ip=9 "Get Parameters Value") de ua3g_freeseating_ipv6.ek.ndjson :
    identifiants de paramètre demandés observés 12, 3, 4, 1, 10 — 12 (0x0C)
    n'est volontairement pas dans la table (absent du dissecteur)."""
    assert UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES[3] == "Local IP Address"
    assert UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES[4] == "Subnetwork Mask"
    assert UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES[1] == "Firmware Version"
    assert UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES[10] == "MAC Address"
    assert 12 not in UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES


def test_decode_names_resolves_each_element_of_a_repeated_field():
    assert decode_names(UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES, ["3", "4", "10"]) == [
        "Local IP Address",
        "Subnetwork Mask",
        "MAC Address",
    ]


def test_decode_names_keeps_unresolvable_elements_as_none_for_alignment():
    """L'alignement positionnel avec le champ source (ex: une liste de
    longueurs associée) est préservé même quand un élément n'est pas
    résolvable — pas de suppression silencieuse d'une position."""
    assert decode_names(UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES, ["3", "255", "4"]) == [
        "Local IP Address",
        None,
        "Subnetwork Mask",
    ]


def test_decode_names_returns_none_when_nothing_resolvable_or_value_absent():
    assert decode_names(UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES, ["255", "254"]) is None
    assert decode_names(UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES, None) is None


def test_decode_names_accepts_a_lone_scalar_value_not_wrapped_in_a_list():
    """tshark n'encapsule pas toujours un champ répété présent une seule
    fois dans une liste (même remarque que ``pick()`` dans fields.py)."""
    assert decode_names(UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES, "3") == ["Local IP Address"]


def test_uaudp_terminal_default_ports_matches_wireshark_default_preference():
    """UAUDP_PORT_RANGE = "32000,32512" dans packet-uaudp.c (valeur par
    défaut de la préférence Wireshark, pas de plage 32000-32512 malgré la
    syntaxe : deux ports individuels)."""
    assert frozenset({32000, 32512}) == UAUDP_TERMINAL_DEFAULT_PORTS


def test_ua3g_ip_device_routing_set_parameter_names_match_official_dissector_table():
    """ip_device_routing_cmd_set_param_req_vals[]/..._vals_ext
    (packet-ua3g.c), champ répété "ua3g.ip.set_param_req.parameter" —
    sous-commande 0x0A "Set Parameters Value" de IP Device Routing. Table
    distincte de UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES (0x09/0x02) malgré
    la proximité du nom de champ tshark. 40 entrées (roadmap.md citait
    "~41", une estimation approximative antérieure au comptage exact)."""
    assert UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES == {
        0x00: "QOS IP TOS",
        0x01: "QOS 8021 VLID",
        0x02: "QOS 8021 PRI",
        0x03: "SNMP MIB2 SysContact",
        0x04: "SNMP MIB2 SysName",
        0x05: "SNMP MIB2 SysLocation",
        0x06: "Default Compressor",
        0x07: "Error String Net Down",
        0x08: "Error String Cable PB",
        0x09: "Error String Try Connect",
        0x0A: "Error String Connected",
        0x0B: "Error String Reset",
        0x0C: "Error String Duplicate IP Address",
        0x0D: "SNMP MIB Community",
        0x0E: "TFTP Backup Sec Mode",
        0x0F: "TFTP Backup IP Address",
        0x10: "Set MMI Password",
        0x11: "Set PC Port Status",
        0x12: "Record RTP Authorization",
        0x13: "Security Flags",
        0x14: "ARP Spoofing",
        0x15: "Session Param",
        0x16: "Stable Mode",
        0x17: "DTMF Level",
        0x18: "Keep Talking",
        0x19: "BT Radio",
        0x1A: "Transparent Reboot",
        0x1B: "Set Skin Identifier",
        0x1C: "Set Language Identifier",
        0x1D: "Set Dialpad Rotation",
        0x1E: "Set USB Boost Charging",
        0x1F: "Set SSH Password",
        0x20: "DHCP Survivability",
        0x21: "USB Devices",
        0x22: "ALS Device",
        0x23: "Busy Light",
        0x24: "Audio Environment",
        0x25: "EEE Configuration",
        0x26: "LLDP Configuration",
        0x30: "MD5 Authentication",
    }


def test_ua3g_ip_device_routing_set_parameter_names_match_fixture_observations():
    """Valeurs recoupées avec les messages UA3G opcode 0x13 réels
    (ip=10 "Set Parameters Value") de ua3g_freeseating_ipv4/ipv6.ek.ndjson :
    22 identifiants distincts réellement observés sur les deux fixtures —
    3, 4, 5, 14, 15, 16, 17, 19, 20, 22, 23, 24, 25, 26, 27, 28, 30, 31, 32,
    33, 34, 35 (voir docs/roadmap.md) — tous résolvables dans la table."""
    for identifier in (
        3,
        4,
        5,
        14,
        15,
        16,
        17,
        19,
        20,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        30,
        31,
        32,
        33,
        34,
        35,
    ):
        assert identifier in UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES
    assert UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES[3] == "SNMP MIB2 SysContact"
    assert UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES[0x1A] == "Transparent Reboot"


def test_ua3g_ip_device_routing_freeseating_parameter_names_match_official_dissector_table():
    """ip_device_routing_cmd_freeseating_vals[] (packet-ua3g.c, table
    VALS() simple, pas de variante ``_ext``), champ répété
    "ua3g.ip.freeseating.parameter" — sous-commande 0x11 "Free Seating" de
    IP Device Routing. Seulement 4 entrées, contrairement aux 40 de
    UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES malgré la proximité
    structurelle de dissection."""
    assert UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES == {
        0x00: "Pseudo MAC Address",
        0x01: "Maincpu1",
        0x02: "Maincpu2",
        0x03: "Restart application",
    }


def test_ua3g_ip_device_routing_freeseating_parameter_names_match_fixture_observations():
    """Valeurs recoupées avec les messages UA3G opcode 0x13 réels (ip=17
    "Free Seating") de ua3g_freeseating_ipv4/ipv6.ek.ndjson : identifiants
    bruts observés [0, 0, 1, 1] (ipv4) et [0, 0, 1, 1, 2, 2] (ipv6) —
    doublement consécutif confirmé, comme pour SET_PARAMETER_NAMES."""
    for identifier in (0x00, 0x01, 0x02):
        assert identifier in UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES
    assert UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES[0] == "Pseudo MAC Address"
    assert UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES[1] == "Maincpu1"
    assert UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES[2] == "Maincpu2"
