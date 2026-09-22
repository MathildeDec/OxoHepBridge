#!/usr/bin/env python3
"""Tests du normaliseur (normalizer.py) : tolérance aux champs manquants,
extraction multi-NOE, corrélations."""

from __future__ import annotations

import json

from oxo_hep_bridge.hep import IPV4, IPV6, ProtoType
from oxo_hep_bridge.normalizer import (
    build_correlation_id,
    extract_noe_events,
    normalize,
    pick,
)


def test_pick_returns_list_index_or_scalar():
    assert pick(["a", "b"], 1) == "b"
    assert pick("scalar") == "scalar"
    assert pick([], 0) is None


def test_normalize_tolerates_missing_ua_fields():
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5060",
        "udp_udp_dstport": "5061",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "uaudp_uaudp_opcode": "4",
    }
    pkt = normalize(flat, capture_agent_id=2001)
    assert pkt is not None
    assert pkt.src_ip == "10.0.0.1"
    assert pkt.dst_ip == "10.0.0.2"
    assert pkt.src_port == 5060
    assert pkt.dst_port == 5061
    assert pkt.ip_family == IPV4
    assert pkt.capture_agent_id == 2001


def test_normalize_uses_ipv6_when_present():
    flat = {
        "ipv6_ipv6_src": "2001:db8::1",
        "ipv6_ipv6_dst": "2001:db8::2",
        "udp_udp_srcport": "5060",
        "udp_udp_dstport": "5061",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "uaudp_uaudp_opcode": "4",
    }
    pkt = normalize(flat, capture_agent_id=2001)
    assert pkt is not None
    assert pkt.ip_family == IPV6
    assert pkt.src_ip == "2001:db8::1"


def test_normalize_extracts_multi_noe_events():
    flat = {
        "noe": [
            {"noe_noe_objectid": "4867", "noe_noe_class": "State"},
            {"noe_noe_objectid": "4864", "noe_noe_class": "State"},
        ]
    }
    events = extract_noe_events(flat)
    assert len(events) == 2


def test_normalize_extracts_single_noe_object():
    flat = {"noe": {"noe_noe_objectid": "4867"}}
    events = extract_noe_events(flat)
    assert len(events) == 1
    assert events[0]["noe_noe_objectid"] == "4867"


def test_normalize_returns_none_for_non_ua_packet():
    # paquet DHCP/TFTP capturé par erreur sur le même port -> pas de UA
    flat = {
        "ip_ip_src": "10.0.0.1",
        "udp_udp_srcport": "68",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
    }
    assert normalize(flat, capture_agent_id=2001) is None


def test_normalize_payload_includes_noe_list():
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5060",
        "udp_udp_dstport": "5061",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "noe": [
            {"noe_noe_objectid": "4867"},
            {"noe_noe_objectid": "4864"},
        ],
    }
    pkt = normalize(flat, capture_agent_id=2001)
    assert pkt is not None
    payload = json.loads(pkt.payload.decode("utf-8"))
    assert "noe" in payload
    assert len(payload["noe"]) == 2
    assert payload["noe"][0]["objectid"] == "4867"


def test_normalize_correlation_id_synthesized_from_ip_ports():
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5060",
        "udp_udp_dstport": "5061",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "uaudp_uaudp_opcode": "4",
    }
    pkt = normalize(flat, capture_agent_id=2001)
    assert pkt is not None
    assert pkt.correlation_id == "10.0.0.1:5060-10.0.0.2:5061"


def test_normalize_correlation_field_overrides_synthesis():
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5060",
        "udp_udp_dstport": "5061",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "uaudp_uaudp_opcode": "4",
        "ua_call_id": "call-abc",
    }
    pkt = normalize(flat, capture_agent_id=2001, correlation_field="ua_call_id")
    assert pkt is not None
    assert pkt.correlation_id == "call-abc"


def test_normalize_timestamp_parses_tshark_iso8601():
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "uaudp_uaudp_opcode": "4",
    }
    pkt = normalize(flat, capture_agent_id=2001)
    assert pkt is not None
    # 9 avril 2018, approximativement 15h UTC
    assert pkt.timestamp_sec > 1520000000
    assert 0 <= pkt.timestamp_usec < 1000000


def test_normalize_default_proto_type_is_log():
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "uaudp_uaudp_opcode": "4",
    }
    pkt = normalize(flat, capture_agent_id=2001)
    assert pkt is not None
    assert pkt.proto_type == ProtoType.LOG


def test_build_correlation_id_handles_missing_ports():
    flat = {"ip_ip_src": "10.0.0.1", "ip_ip_dst": "10.0.0.2"}
    cid = build_correlation_id(flat)
    assert cid == "10.0.0.1:0-10.0.0.2:0"


def test_correlation_id_canonical_same_both_directions():
    """La corrélation stateless doit produire le même identifiant que le sens
    du flux soit A→B ou B→A (endpoints triés)."""
    forward = {
        "ip_ip_src": "10.0.0.5",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5060",
        "udp_udp_dstport": "32640",
    }
    reverse = {
        "ip_ip_src": "10.0.0.2",
        "ip_ip_dst": "10.0.0.5",
        "udp_udp_srcport": "32640",
        "udp_udp_dstport": "5060",
    }
    assert build_correlation_id(forward) == build_correlation_id(reverse)


def test_semantic_payload_structure_has_uanoe_and_endpoints():
    """Le payload sémantique doit contenir les sections uaudp, endpoints,
    correlation_id et, si présent, noe (sans le double préfixe noe_noe_)."""
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5060",
        "udp_udp_dstport": "32640",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "uaudp_uaudp_opcode": "4",
        "uaudp_uaudp_sntseq": "10",
        "uaudp_uaudp_expseq": "8",
        "frame_frame_number": "1",
        "ip_ip_ttl": "64",
        "noe": [{"noe_noe_objectid": "4867", "noe_noe_class": "State"}],
    }
    pkt = normalize(flat, capture_agent_id=2001)
    assert pkt is not None
    payload = json.loads(pkt.payload.decode("utf-8"))
    assert "uaudp" in payload
    assert payload["uaudp"]["opcode"] == "4"
    assert payload["uaudp"]["sntseq"] == "10"
    assert "endpoints" in payload
    assert payload["endpoints"]["src"]["ip"] == "10.0.0.1"
    assert "correlation_id" in payload
    # noe doit être nettoyé du double préfixe
    assert "noe" in payload
    assert payload["noe"][0]["objectid"] == "4867"
    assert "noe_noe_objectid" not in payload["noe"][0]
    assert "raw_selected" in payload
    assert payload["raw_selected"]["frame_frame_number"] == "1"


def test_semantic_payload_includes_qos_on_init_packet():
    """Sur les paquets d'initialisation (opcode 0), les métriques QoS
    (version, window_size, mtu, qos_ip_tos) doivent être extraites."""
    flat = {
        "ip_ip_src": "10.0.0.1",
        "ip_ip_dst": "10.0.0.2",
        "udp_udp_srcport": "5060",
        "udp_udp_dstport": "32640",
        "frame_frame_time_epoch": "2018-04-09T15:14:54.770911000Z",
        "uaudp_uaudp_opcode": "0",
        "uaudp_uaudp_version": ["2"],
        "uaudp_uaudp_window_size": ["256"],
        "uaudp_uaudp_mtu": ["1500"],
        "uaudp_uaudp_qos_ip_tos": ["0x60"],
    }
    pkt = normalize(flat, capture_agent_id=2001)
    assert pkt is not None
    payload = json.loads(pkt.payload.decode("utf-8"))
    assert "qos" in payload
    assert payload["qos"]["version"] == "2"
    assert payload["qos"]["window_size"] == "256"
    assert payload["qos"]["mtu"] == "1500"
