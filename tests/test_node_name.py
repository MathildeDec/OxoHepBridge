#!/usr/bin/env python3
"""Tests du chunk node_name (0x0013) : présent si node_name est positionné,
absent sinon. Comme pour auth_key, on valide via decode() plutôt que par
recherche d'octets bruts."""

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


def test_node_name_chunk_present_when_set():
    packet = normalize(_make_flat(), capture_agent_id=1, node_name="oxo-besancon-01")
    assert packet is not None
    chunks = decode(encode(packet))
    node_chunks = [p for _v, t, p in chunks if t == ChunkType.NODE_NAME]
    assert len(node_chunks) == 1
    assert node_chunks[0] == b"oxo-besancon-01"


def test_node_name_chunk_absent_when_not_set():
    packet = normalize(_make_flat(), capture_agent_id=1, node_name=None)
    assert packet is not None
    chunks = decode(encode(packet))
    chunk_types = {chunk_type for _vendor, chunk_type, _payload in chunks}
    assert ChunkType.NODE_NAME not in chunk_types
