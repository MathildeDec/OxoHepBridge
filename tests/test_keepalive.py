#!/usr/bin/env python3
"""Tests du keepalive HEP périodique (`keepalive.py`) :

- structure du paquet keepalive (chunk KEEPALIVE_TIMER + payload JSON)
- déclenchement périodique du `KeepaliveScheduler` sur un thread de fond
- non-démarrage quand l'intervalle est nul
- intégration dans `Bridge` : actif seulement en capture live (jamais en
  relecture pcap), respect du mode dry-run.
"""

from __future__ import annotations

import json
import struct
import time

from oxo_hep_bridge.bridge import Bridge
from oxo_hep_bridge.config import Config
from oxo_hep_bridge.hep import ChunkType, decode, encode
from oxo_hep_bridge.keepalive import KeepaliveScheduler, build_keepalive_packet
from oxo_hep_bridge.sender import Sender


class RecordingSender(Sender):
    """Sender factice qui enregistre les paquets HEP envoyés, pour les tests."""

    def __init__(self) -> None:
        self.sent: list = []

    def send(self, packet) -> bool:
        self.sent.append(packet)
        return True


def test_build_keepalive_packet_carries_keepalive_timer_chunk():
    packet = build_keepalive_packet(capture_agent_id=2001, interval=30, node_name="oxo-test-01")
    chunks = decode(encode(packet))

    ka_chunks = [
        payload
        for _vendor, chunk_type, payload in chunks
        if chunk_type == ChunkType.KEEPALIVE_TIMER
    ]
    assert len(ka_chunks) == 1
    assert struct.unpack(">H", ka_chunks[0])[0] == 30


def test_build_keepalive_packet_payload_is_json_marker():
    packet = build_keepalive_packet(capture_agent_id=2001, interval=30, node_name="oxo-test-01")
    chunks = decode(encode(packet))

    payload_chunks = [
        payload for _vendor, chunk_type, payload in chunks if chunk_type == ChunkType.PAYLOAD
    ]
    assert len(payload_chunks) == 1
    data = json.loads(payload_chunks[0].decode("utf-8"))
    assert data["type"] == "keepalive"
    assert data["node_name"] == "oxo-test-01"
    assert data["capture_agent_id"] == 2001
    assert data["interval_seconds"] == 30


def test_build_keepalive_packet_without_node_name():
    packet = build_keepalive_packet(capture_agent_id=42, interval=10)
    chunks = decode(encode(packet))
    chunk_types = {chunk_type for _vendor, chunk_type, _payload in chunks}
    assert ChunkType.NODE_NAME not in chunk_types
    assert ChunkType.KEEPALIVE_TIMER in chunk_types


def test_build_keepalive_packet_has_no_correlation_id_chunk():
    """Contrairement à un paquet de trafic normalisé (`normalize()` calcule
    toujours un `correlation_id` via `build_correlation_id()`, jamais vide),
    le paquet keepalive ne représente aucun flux réel (adresses 0.0.0.0:0,
    voir architecture.md) et n'a donc rien à corréler. `docs/hep-chunks.md`
    affirmait à tort que le chunk CORRELATION_ID (0x0011) était « toujours
    présent » sans distinguer ce cas — corrigé côté doc, garde-fou ici pour
    empêcher toute régression silencieuse dans un sens comme dans l'autre."""
    packet = build_keepalive_packet(capture_agent_id=2001, interval=30, node_name="oxo-test-01")
    assert packet.correlation_id is None

    chunks = decode(encode(packet))
    chunk_types = {chunk_type for _vendor, chunk_type, _payload in chunks}
    assert ChunkType.CORRELATION_ID not in chunk_types


def test_scheduler_disabled_when_interval_is_zero():
    recorder = RecordingSender()
    scheduler = KeepaliveScheduler(sender=recorder, interval=0, capture_agent_id=1)
    assert scheduler.enabled is False

    scheduler.start()  # doit être un no-op
    time.sleep(0.05)
    scheduler.stop()

    assert recorder.sent == []


def test_scheduler_sends_periodically_and_stops_cleanly():
    recorder = RecordingSender()
    scheduler = KeepaliveScheduler(
        sender=recorder, interval=0.05, capture_agent_id=2001, node_name="n1"
    )
    assert scheduler.enabled is True

    scheduler.start()
    time.sleep(0.23)
    scheduler.stop()

    # ~4 cycles en 0.23s à 0.05s d'intervalle ; on tolère la variance de scheduling
    assert scheduler.sent_count >= 2
    assert len(recorder.sent) == scheduler.sent_count
    for packet in recorder.sent:
        assert packet.keepalive_timer == 0.05

    # après stop(), plus aucun envoi
    count_after_stop = scheduler.sent_count
    time.sleep(0.15)
    assert scheduler.sent_count == count_after_stop


class FailingSender(Sender):
    """Sender factice qui échoue systématiquement, pour vérifier que le
    scheduler journalise l'échec sans planter (voir _run())."""

    def __init__(self) -> None:
        self.attempts = 0

    def send(self, packet) -> bool:
        self.attempts += 1
        return False


def test_scheduler_logs_warning_and_continues_on_send_failure():
    """Un échec d'envoi keepalive (collecteur injoignable) ne doit ni faire
    planter le thread de fond ni interrompre les cycles suivants."""
    failing = FailingSender()
    scheduler = KeepaliveScheduler(sender=failing, interval=0.05, capture_agent_id=1)

    scheduler.start()
    time.sleep(0.17)
    scheduler.stop()

    assert failing.attempts >= 2
    assert scheduler.sent_count == 0  # jamais incrémenté sur échec


def test_scheduler_start_is_idempotent():
    recorder = RecordingSender()
    scheduler = KeepaliveScheduler(sender=recorder, interval=0.05, capture_agent_id=1)
    scheduler.start()
    first_thread = scheduler._thread
    scheduler.start()  # ne doit pas relancer un second thread
    assert scheduler._thread is first_thread
    scheduler.stop()
    scheduler.stop()  # idempotent, ne doit pas lever


def _make_bridge(pcap: str, keepalive_interval: int = 0) -> Bridge:
    config = Config()
    config.capture.pcap = pcap
    config.dry_run = True
    config.hep.keepalive_interval = keepalive_interval
    return Bridge(config)


def test_bridge_never_starts_keepalive_in_pcap_mode(fake_popen):
    """Même avec un intervalle configuré, une relecture pcap ne doit jamais
    déclencher de keepalive (le run se termine avant tout intervalle utile)."""
    bridge = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap", keepalive_interval=60)
    recorder = RecordingSender()
    bridge.sender = recorder
    bridge.keepalive.sender = recorder
    bridge.run()

    assert bridge.keepalive.sent_count == 0


def test_bridge_keepalive_disabled_by_default(fake_popen):
    bridge = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    assert bridge.keepalive.enabled is False


def test_bridge_keepalive_uses_configured_hep_identity(fake_popen):
    config = Config()
    config.capture.pcap = "tests/fixtures/ua3g_freeseating_ipv4.pcap"
    config.dry_run = True
    config.hep.keepalive_interval = 60
    config.hep.capture_agent_id = 4242
    config.hep.node_name = "oxo-besancon-02"
    bridge = Bridge(config)

    assert bridge.keepalive.capture_agent_id == 4242
    assert bridge.keepalive.node_name == "oxo-besancon-02"
    assert bridge.keepalive.interval == 60
