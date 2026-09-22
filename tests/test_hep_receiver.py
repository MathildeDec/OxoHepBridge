#!/usr/bin/env python3
"""Tests du harnais de réception HEPv3 standalone (tools/hep_receiver.py).

Valide en particulier la décompression du chunk COMPRESSED_PAYLOAD (0x0010,
gzip) introduit par `hep.encode(..., compress=True)` : le récepteur doit
pouvoir décoder aussi bien un paquet en clair (chunk PAYLOAD 0x000F) qu'un
paquet compressé, et retomber proprement sur une représentation hex plutôt
que de lever si le flux gzip est corrompu/tronqué.
"""

from __future__ import annotations

import gzip
import struct

from tools.hep_receiver import summarize_packet

from oxo_hep_bridge.hep import (
    CHUNK_HEADER_FMT,
    CHUNK_HEADER_SIZE,
    PACKET_HEADER_SIZE,
    ChunkType,
    HepPacket,
    encode,
)


def _packet(payload: bytes = b'{"uaudp":{"opcode":"4"}}') -> HepPacket:
    return HepPacket(
        src_ip="172.19.104.10",
        dst_ip="172.19.31.87",
        src_port=32640,
        dst_port=32512,
        timestamp_sec=1700000000,
        capture_agent_id=2001,
        payload=payload,
        correlation_id="abc",
        node_name="oxo-test-01",
    )


def test_summarize_packet_decodes_plain_payload():
    summary = summarize_packet(encode(_packet()))
    assert summary["fields"]["payload"] == '{"uaudp":{"opcode":"4"}}'
    assert "payload_compressed" not in summary["fields"]
    assert summary["payload_bytes"] == len(b'{"uaudp":{"opcode":"4"}}')


def test_summarize_packet_decodes_compressed_payload():
    payload = b'{"uaudp":{"opcode":"4","sntseq":"10","expseq":"8"}}'
    summary = summarize_packet(encode(_packet(payload), compress=True))

    assert summary["fields"]["payload"] == payload.decode("utf-8")
    assert summary["fields"]["payload_compressed"] is True
    # taille applicative (décompressée), pas la taille sur le fil
    assert summary["payload_bytes"] == len(payload)
    # la taille compressée effectivement reçue est conservée à part
    assert 0 < summary["fields"]["payload_wire_bytes"] < len(gzip.compress(payload)) + 32


def test_summarize_packet_compressed_payload_matches_plain_content():
    """Même contenu logique, compressé ou non : le résumé JSONL ne doit pas
    différer sur le fond, seulement sur l'indicateur de compression."""
    payload = b'{"noe":[{"objectid":"4867","class":"128","method":"2"}]}'
    plain = summarize_packet(encode(_packet(payload)))
    compressed = summarize_packet(encode(_packet(payload), compress=True))

    assert plain["fields"]["payload"] == compressed["fields"]["payload"]
    assert plain["src"] == compressed["src"]
    assert plain["dst"] == compressed["dst"]


def test_summarize_packet_falls_back_to_hex_on_corrupt_gzip():
    """Un chunk COMPRESSED_PAYLOAD corrompu/tronqué ne doit pas faire planter
    la réception du paquet (ni des suivants) — fallback hex, pas d'exception."""
    pkt = _packet(b"peu importe")
    encoded = bytearray(encode(pkt, compress=True))
    # corrompt le corps du chunk COMPRESSED_PAYLOAD en un flux gzip invalide
    # de même taille, pour rester sur un paquet HEP structurellement valide
    for _vendor, ctype, start, end in _decode_offsets(bytes(encoded)):
        if ctype == ChunkType.COMPRESSED_PAYLOAD:
            body_len = end - start
            encoded[start:end] = b"\x1f\x8b" + b"\x00" * (body_len - 2)

    summary = summarize_packet(bytes(encoded))
    assert isinstance(summary["fields"]["payload"], str)
    assert summary["fields"]["payload"].startswith("<gzip invalide")


def _decode_offsets(packet: bytes) -> list[tuple[int, int, int, int]]:
    """Variante de `hep.decode()` qui renvoie les offsets de chaque chunk
    plutôt que les payloads déjà extraits — utile pour corrompre un chunk en
    place dans un test sans reconstruire le paquet HEP à la main."""
    total_len = struct.unpack(">H", packet[4:6])[0]
    offsets = []
    offset = PACKET_HEADER_SIZE
    while offset < total_len:
        vendor, chunk_type, chunk_len = CHUNK_HEADER_FMT.unpack(
            packet[offset : offset + CHUNK_HEADER_SIZE]
        )
        offsets.append((vendor, chunk_type, offset + CHUNK_HEADER_SIZE, offset + chunk_len))
        offset += chunk_len
    return offsets
