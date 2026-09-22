#!/usr/bin/env python3
"""Tests du chunk auth_key (0x000E) : présent si auth_key est positionné,
absent sinon. Vérifie la conformité avec HEP3 rev12 / heplify-server."""

from oxo_hep_bridge.hep import ChunkType, decode, encode
from oxo_hep_bridge.normalizer import normalize


def _make_flat():
    return {
        "ip_ip_dst": "10.1.1.1",
        "ip_ip_src": "10.1.1.2",
        "udp_udp_dstport": ["32640"],
        "udp_udp_srcport": ["5060"],
        "timestamp": ["2026-01-01T00:00:00.000000000Z"],
        "uaudp_uaudp_opcode": ["1"],
    }


def test_auth_key_chunk_emitted_when_key_set():
    packet = normalize(_make_flat(), capture_agent_id=1, auth_key="my-secret")
    assert packet is not None
    data = encode(packet)
    # auth key = chunk type 0x000E, len 13 (6 header + 9 "my-secret"), value "my-secret"
    assert b"\x00\x0e\x00\x0fmy-secret" in data


def test_no_auth_key_chunk_when_not_set():
    packet = normalize(_make_flat(), capture_agent_id=1, auth_key=None)
    assert packet is not None
    # Robuste : on parse réellement les chunks HEP (vendor_id, chunk_type,
    # payload) et on vérifie qu'aucun chunk de type auth_key (0x000E) n'est
    # présent, plutôt que de chercher un octet brut qui pourrait apparaître
    # par coïncidence dans la payload JSON encodée.
    chunks = decode(encode(packet))
    chunk_types = {chunk_type for _vendor, chunk_type, _payload in chunks}
    assert ChunkType.AUTH_KEY not in chunk_types


def test_auth_key_chunk_present_via_decode():
    packet = normalize(_make_flat(), capture_agent_id=1, auth_key="my-secret")
    assert packet is not None
    chunks = decode(encode(packet))
    auth_chunks = [p for _v, t, p in chunks if t == ChunkType.AUTH_KEY]
    assert len(auth_chunks) == 1
    assert auth_chunks[0] == b"my-secret"
