#!/usr/bin/env python3
"""Tests de l'encodeur/décodeur HEPv3 (hep.py).

Validation contre la spec HEP3 rev12 et l'implémentation de référence
heplify-server/decoder.go :
  - magic "HEP3" présent
  - longueur totale annoncée == longueur réelle
  - chunks round-trip via decode()
  - valeurs encodées correctes (IPv4, ports, timestamps, payload)
"""

from __future__ import annotations

import gzip
import struct

import pytest

from oxo_hep_bridge.hep import (
    CHUNK_HEADER_FMT,
    HEP3_MAGIC,
    IPV6,
    PACKET_HEADER_FMT,
    PACKET_HEADER_SIZE,
    PROTO_UDP,
    ChunkType,
    HepPacket,
    ProtoType,
    decode,
    encode,
)


def test_encode_starts_with_hep3_magic():
    pkt = HepPacket(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        timestamp_usec=0,
        capture_agent_id=2001,
        payload=b'{"hello":"world"}',
        correlation_id="abc",
    )
    encoded = encode(pkt)
    assert encoded[:4] == HEP3_MAGIC


def test_encode_total_length_matches_actual_bytes():
    pkt = HepPacket(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        timestamp_usec=0,
        capture_agent_id=2001,
        payload=b'{"hello":"world"}',
        correlation_id="abc",
    )
    encoded = encode(pkt)
    total_len = struct.unpack(">H", encoded[4:6])[0]
    assert total_len == len(encoded)


def test_encode_decode_round_trip_preserves_chunks():
    pkt = HepPacket(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        timestamp_usec=123456,
        capture_agent_id=2001,
        proto_type=ProtoType.LOG,
        payload=b'{"hello":"world"}',
        correlation_id="abc",
    )
    encoded = encode(pkt)
    chunks = decode(encoded)

    types = [ct for _, ct, _ in chunks]
    assert ChunkType.IPV4_SRC in types
    assert ChunkType.IPV4_DST in types
    assert ChunkType.SRC_PORT in types
    assert ChunkType.DST_PORT in types
    assert ChunkType.TIMESTAMP_SEC in types
    assert ChunkType.TIMESTAMP_USEC in types
    assert ChunkType.PROTOCOL_TYPE in types
    assert ChunkType.CAPTURE_AGENT_ID in types
    assert ChunkType.PAYLOAD in types
    assert ChunkType.CORRELATION_ID in types


def test_encode_specific_chunk_values():
    pkt = HepPacket(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        timestamp_usec=0,
        capture_agent_id=2001,
        proto_type=ProtoType.LOG,
        payload=b'{"hello":"world"}',
        correlation_id="abc",
    )
    chunks = decode(encode(pkt))
    by_type = {ct: payload for _, ct, payload in chunks}

    assert by_type[ChunkType.IPV4_SRC] == bytes([10, 0, 0, 1])
    assert by_type[ChunkType.IPV4_DST] == bytes([10, 0, 0, 2])
    assert struct.unpack(">H", by_type[ChunkType.SRC_PORT])[0] == 5060
    assert struct.unpack(">I", by_type[ChunkType.TIMESTAMP_SEC])[0] == 1700000000
    assert by_type[ChunkType.PAYLOAD] == b'{"hello":"world"}'
    assert by_type[ChunkType.CORRELATION_ID] == b"abc"
    assert struct.unpack(">B", by_type[ChunkType.PROTOCOL_TYPE])[0] == ProtoType.LOG
    assert struct.unpack(">I", by_type[ChunkType.CAPTURE_AGENT_ID])[0] == 2001


def test_encode_ipv6_src_dst():
    pkt = HepPacket(
        ip_family=IPV6,
        ip_proto=PROTO_UDP,
        src_ip="2001:db8::1",
        dst_ip="2001:db8::2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        capture_agent_id=2001,
        payload=b"payload-v6",
    )
    chunks = decode(encode(pkt))
    types = [ct for _, ct, _ in chunks]
    assert ChunkType.IPV6_SRC in types
    assert ChunkType.IPV6_DST in types
    assert ChunkType.IPV4_SRC not in types


def test_decode_rejects_bad_magic():
    with pytest.raises(ValueError, match="HEP3"):
        decode(b"XXXX" + b"\x00\x10" + b"\x00" * 10)


def test_decode_rejects_length_mismatch():
    with pytest.raises(ValueError, match="Longueur totale"):
        decode(HEP3_MAGIC + struct.pack(">H", 999) + b"\x00" * 10)


def test_decode_rejects_packet_shorter_than_header():
    with pytest.raises(ValueError, match="trop court"):
        decode(b"\x00\x01\x02")


def test_decode_rejects_truncated_chunk_header():
    """Un paquet dont total_len annonce assez d'octets pour amorcer un chunk
    mais dont l'en-tête de ce chunk (6 octets) est lui-même tronqué doit être
    rejeté explicitement plutôt que de lever une struct.error opaque."""
    header = PACKET_HEADER_FMT.pack(HEP3_MAGIC, PACKET_HEADER_SIZE + 3)
    packet = header + b"\x00\x00\x00"  # 3 octets, pas assez pour un en-tête de chunk (6)
    with pytest.raises(ValueError, match="tronqué"):
        decode(packet)


def test_decode_rejects_invalid_chunk_length():
    """Un chunk dont chunk_len déborde du paquet (ou est inférieur à la
    taille minimale d'un en-tête de chunk) doit être rejeté explicitement."""
    bad_chunk_len = 3  # < CHUNK_HEADER_SIZE (6)
    chunk_header = CHUNK_HEADER_FMT.pack(0x0000, 0x0001, bad_chunk_len)
    header = PACKET_HEADER_FMT.pack(HEP3_MAGIC, PACKET_HEADER_SIZE + len(chunk_header))
    packet = header + chunk_header
    with pytest.raises(ValueError, match="Longueur de chunk invalide"):
        decode(packet)


def test_encode_rejects_ipv6_address_with_ipv4_family():
    """ip_family=IPV4 (défaut) avec une adresse IPv6 doit être rejeté
    explicitement plutôt que de produire un chunk incohérent."""
    pkt = HepPacket(
        src_ip="2001:db8::1",
        dst_ip="10.0.0.2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        capture_agent_id=2001,
        payload=b"x",
    )
    with pytest.raises(ValueError, match="IPv6 fournie"):
        encode(pkt)


def test_encode_rejects_ipv4_address_with_ipv6_family():
    pkt = HepPacket(
        ip_family=IPV6,
        src_ip="10.0.0.1",
        dst_ip="2001:db8::2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        capture_agent_id=2001,
        payload=b"x",
    )
    with pytest.raises(ValueError, match="IPv4 fournie"):
        encode(pkt)


def test_auth_key_optional_chunk_present_only_when_set():
    pkt = HepPacket(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        capture_agent_id=2001,
        payload=b"x",
        auth_key="secret",
    )
    chunks = decode(encode(pkt))
    types = [ct for _, ct, _ in chunks]
    assert ChunkType.AUTH_KEY in types

    # sans auth_key, le chunk doit être absent
    pkt_no_auth = HepPacket(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        capture_agent_id=2001,
        payload=b"x",
    )
    types_no_auth = [ct for _, ct, _ in decode(encode(pkt_no_auth))]
    assert ChunkType.AUTH_KEY not in types_no_auth


def test_encode_default_uses_plain_payload_chunk():
    """Sans `compress=True` (défaut), le chunk PAYLOAD (0x000F) est émis, pas
    COMPRESSED_PAYLOAD (0x0010) — comportement inchangé par rapport aux tests
    ci-dessus, vérifié explicitement ici pour ne pas régresser au moment
    d'ajouter la compression."""
    pkt = HepPacket(src_ip="10.0.0.1", dst_ip="10.0.0.2", capture_agent_id=1, payload=b"hello")
    types = [ct for _, ct, _ in decode(encode(pkt))]
    assert ChunkType.PAYLOAD in types
    assert ChunkType.COMPRESSED_PAYLOAD not in types


def test_encode_compress_true_emits_compressed_payload_chunk_only():
    """`compress=True` doit émettre COMPRESSED_PAYLOAD (0x0010) à la place de
    PAYLOAD (0x000F), jamais les deux — le collecteur détermine comment lire
    le payload uniquement d'après le chunk présent."""
    pkt = HepPacket(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        capture_agent_id=1,
        payload=b'{"uaudp":{"opcode":"4","sntseq":"10","expseq":"8"}}',
    )
    chunks = decode(encode(pkt, compress=True))
    types = [ct for _, ct, _ in chunks]
    assert ChunkType.COMPRESSED_PAYLOAD in types
    assert ChunkType.PAYLOAD not in types


def test_encode_compress_true_payload_is_valid_gzip_of_original():
    pkt = HepPacket(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        capture_agent_id=1,
        payload=b'{"uaudp":{"opcode":"4","sntseq":"10","expseq":"8"}}',
    )
    chunks = decode(encode(pkt, compress=True))
    by_type = {ct: payload for _, ct, payload in chunks}
    compressed = by_type[ChunkType.COMPRESSED_PAYLOAD]
    # signature gzip standard (RFC 1952)
    assert compressed[:2] == b"\x1f\x8b"
    assert gzip.decompress(compressed) == pkt.payload


def test_encode_compress_true_with_empty_payload_round_trips():
    pkt = HepPacket(src_ip="10.0.0.1", dst_ip="10.0.0.2", capture_agent_id=1, payload=b"")
    chunks = decode(encode(pkt, compress=True))
    by_type = {ct: payload for _, ct, payload in chunks}
    assert gzip.decompress(by_type[ChunkType.COMPRESSED_PAYLOAD]) == b""


def test_encode_compress_true_reduces_size_for_repetitive_payload():
    """Pas une garantie universelle (petits payloads : l'en-tête gzip peut
    coûter plus que le gain), mais un payload JSON répétitif représentatif de
    `semantics.py` doit bien compresser — sinon la fonctionnalité n'apporte
    rien en pratique."""
    payload = (b'{"uaudp":{"opcode":"4","sntseq":"10","expseq":"8"}}' * 20) + b'"padding":"x"}'
    pkt = HepPacket(src_ip="10.0.0.1", dst_ip="10.0.0.2", capture_agent_id=1, payload=payload)
    plain_size = len(encode(pkt))
    compressed_size = len(encode(pkt, compress=True))
    assert compressed_size < plain_size


def test_minimal_packet_header_size():
    """Un paquet sans payload ni optionnels a au moins l'en-tête + les chunks obligatoires."""
    pkt = HepPacket(src_ip="0.0.0.0", dst_ip="0.0.0.0", capture_agent_id=1, payload=b"")
    encoded = encode(pkt)
    assert len(encoded) > PACKET_HEADER_SIZE
    # 10 chunks obligatoires * (6 + payload) + 6 octets d'en-tête
    assert len(decode(encoded)) >= 10


def test_field_chunks_matches_actual_encode_order():
    """`HepPacket._FIELD_CHUNKS` se déclare comme l'ordre canonique des chunks
    obligatoires à l'encodage, « reproductible pour les tests » — mais
    jusqu'à cette session, n'était référencé nulle part ailleurs dans le
    projet (ni par `encode()`, qui construit la même séquence indépendamment
    à la main, ni par aucun test). Trouvé en cherchant `_FIELD_CHUNKS` dans
    tout le dépôt, même méthode que pour les autres constantes « source de
    vérité » du projet (ex: `_CAPTURE_KEYS` dans `test_docs.py`). Ce test
    rend la promesse du docstring réelle en comparant l'ordre effectif des
    chunks en sortie de `encode()` à `_FIELD_CHUNKS`, en IPv4 et en IPv6
    (seuls `src_ip`/`dst_ip` changent de chunk type entre les deux)."""
    base_map = {
        "ip_protocol_family": ChunkType.IP_PROTOCOL_FAMILY,
        "ip_protocol_id": ChunkType.IP_PROTOCOL_ID,
        "src_port": ChunkType.SRC_PORT,
        "dst_port": ChunkType.DST_PORT,
        "timestamp_sec": ChunkType.TIMESTAMP_SEC,
        "timestamp_usec": ChunkType.TIMESTAMP_USEC,
        "protocol_type": ChunkType.PROTOCOL_TYPE,
        "capture_agent_id": ChunkType.CAPTURE_AGENT_ID,
    }
    n = len(HepPacket._FIELD_CHUNKS)

    ipv4_map = {**base_map, "src_ip": ChunkType.IPV4_SRC, "dst_ip": ChunkType.IPV4_DST}
    pkt_v4 = HepPacket(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        timestamp_usec=123,
        capture_agent_id=2001,
        payload=b"x",
    )
    actual_v4 = [ct for _, ct, _ in decode(encode(pkt_v4))][:n]
    assert actual_v4 == [ipv4_map[name] for name in HepPacket._FIELD_CHUNKS]

    ipv6_map = {**base_map, "src_ip": ChunkType.IPV6_SRC, "dst_ip": ChunkType.IPV6_DST}
    pkt_v6 = HepPacket(
        ip_family=IPV6,
        src_ip="2001:db8::1",
        dst_ip="2001:db8::2",
        src_port=5060,
        dst_port=5060,
        timestamp_sec=1700000000,
        timestamp_usec=123,
        capture_agent_id=2001,
        payload=b"x",
    )
    actual_v6 = [ct for _, ct, _ in decode(encode(pkt_v6))][:n]
    assert actual_v6 == [ipv6_map[name] for name in HepPacket._FIELD_CHUNKS]
