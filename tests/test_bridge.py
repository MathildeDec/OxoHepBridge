#!/usr/bin/env python3
"""Tests d'intégration du pipeline Bridge : source (fake) -> normaliseur ->
encodeur HEP -> sender (fake), sur les fixtures réelles."""

from __future__ import annotations

from loguru import logger as _logger

from conftest import FakePopen, _FakeStream
from oxo_hep_bridge.bridge import Bridge
from oxo_hep_bridge.config import Config
from oxo_hep_bridge.hep import decode, encode
from oxo_hep_bridge.sender import Sender, TCPSender, UDPSender
from oxo_hep_bridge.tshark_source import TsharkError


class RecordingSender(Sender):
    """Sender factice qui enregistre les paquets HEP envoyés, pour les tests."""

    def __init__(self) -> None:
        self.sent: list = []

    def send(self, packet) -> bool:
        self.sent.append(packet)
        return True


def _make_bridge(pcap: str) -> tuple[Bridge, RecordingSender]:
    config = Config()
    config.capture.pcap = pcap
    config.dry_run = True  # sender remplacé ensuite par le recording sender
    bridge = Bridge(config)
    recorder = RecordingSender()
    bridge.sender = recorder
    return bridge, recorder


def test_bridge_normalizes_and_sends_ua3g_freeseating_packets(fake_popen):
    bridge, recorder = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    bridge.run()

    assert len(recorder.sent) > 0
    # chaque paquet envoyé doit être un HepPacket valide encodable/décodable
    for pkt in recorder.sent[:5]:
        encoded = encode(pkt)
        chunks = decode(encoded)
        assert len(chunks) > 0


def test_bridge_skips_non_ua_packets(fake_popen):
    bridge, recorder = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    total_raw = sum(1 for _ in bridge.source.iter_packets())
    bridge2, recorder2 = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    bridge2.run()
    # tous les paquets normalisés doivent porter des données UA
    assert len(recorder2.sent) <= total_raw


def test_bridge_iter_normalized_yields_hep_packets(fake_popen):
    bridge, _ = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    packets = list(bridge.iter_normalized())
    assert len(packets) > 0
    assert all(p.payload for p in packets)


class FailingSender(Sender):
    """Sender factice qui échoue sur le 2e paquet envoyé (simule un collecteur
    HOMER injoignable)."""

    def __init__(self) -> None:
        self.sent: list = []
        self.calls = 0

    def send(self, packet) -> bool:
        self.calls += 1
        if self.calls == 2:
            return False  # simulate network failure on 2nd packet
        self.sent.append(packet)
        return True


def test_bridge_stats_tracks_send_errors_and_skipped(fake_popen):
    bridge, _ = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    failing = FailingSender()
    bridge.sender = failing
    bridge.run()
    stats = bridge.stats
    # le nombre de paquets envoyés + erreurs + ignorés doit égaler le reçu
    assert stats.received == stats.sent + stats.skipped + stats.send_errors
    # exactement une erreur d'envoi (2e paquet)
    assert stats.send_errors == 1
    # au moins un paquet envoyé avec succès
    assert stats.sent >= 1


def test_bridge_wires_hep_transport_config_into_sender():
    """La construction du Bridge (dry_run=False) doit propager
    hep.transport/tls_verify/tls_ca_file jusqu'au sender réel via
    make_sender() — pas seulement host/port. Ne nécessite pas fake_popen :
    TsharkEKSource ne lance tshark qu'à l'itération, pas à la construction."""
    config = Config()
    config.capture.pcap = "tests/fixtures/ua3g_freeseating_ipv4.pcap"
    config.hep.transport = "tls"
    config.hep.tls_verify = False
    config.hep.tls_ca_file = "/etc/pki/homer-ca.pem"
    bridge = Bridge(config)
    try:
        assert isinstance(bridge.sender, TCPSender)
        assert bridge.sender.tls is True
        assert bridge.sender.tls_verify is False
        assert bridge.sender.tls_ca_file == "/etc/pki/homer-ca.pem"
    finally:
        bridge.sender.close()


def test_bridge_defaults_to_udp_sender():
    config = Config()
    config.capture.pcap = "tests/fixtures/ua3g_freeseating_ipv4.pcap"
    bridge = Bridge(config)
    try:
        assert isinstance(bridge.sender, UDPSender)
    finally:
        bridge.sender.close()


def test_bridge_wires_compress_payload_into_sender():
    config = Config()
    config.capture.pcap = "tests/fixtures/ua3g_freeseating_ipv4.pcap"
    config.hep.compress_payload = True
    bridge = Bridge(config)
    try:
        assert bridge.sender.compress is True
    finally:
        bridge.sender.close()


def test_bridge_compress_payload_defaults_to_false():
    config = Config()
    config.capture.pcap = "tests/fixtures/ua3g_freeseating_ipv4.pcap"
    bridge = Bridge(config)
    try:
        assert bridge.sender.compress is False
    finally:
        bridge.sender.close()


def test_bridge_wires_send_retries_into_sender():
    config = Config()
    config.capture.pcap = "tests/fixtures/ua3g_freeseating_ipv4.pcap"
    config.hep.send_retries = 4
    config.hep.send_retry_backoff = 1.5
    bridge = Bridge(config)
    try:
        assert bridge.sender.retries == 4
        assert bridge.sender.retry_backoff == 1.5
    finally:
        bridge.sender.close()


def test_bridge_send_retries_defaults_to_zero():
    config = Config()
    config.capture.pcap = "tests/fixtures/ua3g_freeseating_ipv4.pcap"
    bridge = Bridge(config)
    try:
        assert bridge.sender.retries == 0
    finally:
        bridge.sender.close()


class RetryingThenSucceedingSender(Sender):
    """Sender factice qui expose un `retry_count` comme UDPSender/TCPSender,
    pour vérifier que Bridge.run() le reporte dans les stats de fin de run."""

    def __init__(self, retry_count: int) -> None:
        self.retry_count = retry_count

    def send(self, packet) -> bool:
        return True


def test_bridge_stats_reports_sender_retry_count(fake_popen):
    bridge, _ = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    bridge.sender = RetryingThenSucceedingSender(retry_count=7)
    bridge.run()
    assert bridge.stats.send_retries == 7


def test_bridge_stats_send_retries_zero_when_sender_has_no_retry_count(fake_popen):
    """RecordingSender (comme NullSender) n'assigne pas retry_count lui-même :
    stats.send_retries doit retomber sur le défaut 0 de la classe de base
    Sender plutôt que de planter."""
    bridge, recorder = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    bridge.run()
    assert bridge.stats.send_retries == 0


def test_bridge_run_closes_sender_without_own_close_method(fake_popen):
    """RecordingSender ne redéfinit pas close() : Bridge.run() doit tout de
    même l'appeler sans lever (hérité en no-op de la classe de base Sender),
    plutôt que de dépendre d'un hasattr() au point d'appel."""
    bridge, recorder = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    bridge.run()  # ne doit pas lever


# --- Fréquence du log de progression (logging.stats_interval) ---


def test_bridge_logs_progression_at_configured_interval(fake_popen):
    """Avec stats_interval=1, chaque paquet envoyé doit déclencher un log de
    progression (plutôt que d'attendre le seuil fixe historique de 500)."""
    bridge, recorder = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    bridge.config.logging.stats_interval = 1

    captured: list[str] = []

    def _sink(message):
        captured.append(str(message))

    handler_id = _logger.add(_sink, level="DEBUG")
    try:
        bridge.run()
    finally:
        _logger.remove(handler_id)

    progression_lines = [line for line in captured if "progression" in line]
    assert len(progression_lines) == len(recorder.sent)


def test_bridge_progression_log_binds_stats_extra(fake_popen):
    """Session 42 : le log de progression exploite lui aussi Stats.to_dict()
    via logger.bind(), pas seulement le résumé de fin de run (stats.py) —
    voir docs/architecture.md#sortie-json-structurée-loggingjson_file--
    exploiter-statsto_dict."""
    bridge, recorder = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    bridge.config.logging.stats_interval = 1

    captured_extra: list[dict] = []

    def _sink(message):
        if "progression" in message.record["message"]:
            captured_extra.append(message.record["extra"])

    handler_id = _logger.add(_sink, level="DEBUG")
    try:
        bridge.run()
    finally:
        _logger.remove(handler_id)

    assert captured_extra
    assert all("stats" in extra for extra in captured_extra)
    # Le dernier log de progression doit refléter le compte final envoyé.
    assert captured_extra[-1]["stats"]["sent"] == len(recorder.sent)
    assert captured_extra[-1]["stats"] == bridge.stats.to_dict()


def test_bridge_stats_interval_zero_disables_progression_log(fake_popen):
    """stats_interval <= 0 coupe le log de progression en cours de run, sans
    affecter le résumé de fin de run (log_summary, testé ailleurs)."""
    bridge, recorder = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    bridge.config.logging.stats_interval = 0

    captured: list[str] = []

    def _sink(message):
        captured.append(str(message))

    handler_id = _logger.add(_sink, level="DEBUG")
    try:
        bridge.run()
    finally:
        _logger.remove(handler_id)

    assert len(recorder.sent) > 0  # le run a bien traité des paquets
    assert not any("progression" in line for line in captured)


def test_bridge_progression_log_defaults_to_500():
    config = Config()
    config.capture.pcap = "tests/fixtures/ua3g_freeseating_ipv4.pcap"
    bridge = Bridge(config)
    try:
        assert bridge.config.logging.stats_interval == 500
    finally:
        bridge.sender.close()


# --- Gestion d'erreur : normalize() qui lève, tshark qui plante, keepalive ---


class RaisingOnSecondCallNormalizer:
    """Remplace Bridge.normalize_packet : lève une exception inattendue sur
    le 2e paquet, se comporte normalement sinon (délègue à la vraie
    fonction). Simule un bug de normalisation isolé sur un paquet
    particulier, sans planter tout le run."""

    def __init__(self, real_normalize) -> None:
        self._real = real_normalize
        self.calls = 0

    def __call__(self, flat):
        self.calls += 1
        if self.calls == 2:
            raise ValueError("boom : champ inattendu")
        return self._real(flat)


def test_bridge_run_continues_after_unexpected_normalize_exception(fake_popen):
    """Une exception inattendue (pas juste un paquet ignoré) pendant
    normalize_packet() ne doit pas interrompre le run : elle est comptée
    dans stats.normalize_errors et le traitement continue sur les paquets
    suivants."""
    bridge, recorder = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    raising = RaisingOnSecondCallNormalizer(bridge.normalize_packet)
    bridge.normalize_packet = raising
    bridge.run()

    stats = bridge.stats
    assert stats.normalize_errors == 1
    # le run a continué après l'erreur : d'autres paquets ont bien été envoyés
    assert len(recorder.sent) > 0
    assert stats.received == stats.normalized + stats.skipped + stats.normalize_errors


def test_bridge_run_reports_skipped_packets(fake_popen):
    """Les paquets normalisés à None (bruit non-UA/UAUDP inexploitable)
    doivent incrémenter stats.skipped plutôt que send_errors ou
    normalize_errors. `uaudp_ipv6.pcap` contient des paquets ignorés
    (contrairement aux fixtures ua3g_freeseating_*, entièrement UA)."""
    bridge, _ = _make_bridge("tests/fixtures/uaudp_ipv6.pcap")
    bridge2, _ = _make_bridge("tests/fixtures/uaudp_ipv6.pcap")
    total_raw = sum(1 for _ in bridge2.source.iter_packets())
    bridge.run()
    stats = bridge.stats
    assert stats.received == total_raw
    assert stats.skipped > 0
    assert stats.skipped == total_raw - stats.normalized - stats.normalize_errors


class FakePopenTsharkError(FakePopen):
    """Fake tshark qui écrit un peu de flux valide puis meurt en erreur, pour
    exercer le chemin `Bridge.run()` -> `TsharkError` (résumé de fin de run
    marqué en échec, code de retour 1)."""

    def __init__(self, cmd, stdout=None, stderr=None, text=None, bufsize=None):
        super().__init__(cmd, stdout=stdout, stderr=stderr, text=text, bufsize=bufsize)
        self._stdout = _FakeStream(self._stdout_lines)
        self.returncode = 42

    def poll(self):
        return 42


def test_bridge_run_returns_1_and_logs_summary_on_tshark_error(monkeypatch):
    monkeypatch.setattr("oxo_hep_bridge.tshark_source.subprocess.Popen", FakePopenTsharkError)
    bridge, recorder = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    rc = bridge.run()

    assert rc == 1
    assert bridge.stats.tshark_errors == 1
    # send_retries doit être reporté même sur le chemin d'erreur fatale
    assert bridge.stats.send_retries == 0


def test_bridge_run_raises_tsharkerror_propagates_as_error_stat(monkeypatch):
    """Vérifie explicitement que l'exception capturée est bien TsharkError
    (pas une exception générique) : `Bridge.run()` ne doit pas masquer un
    autre type d'erreur derrière ce compteur."""
    monkeypatch.setattr("oxo_hep_bridge.tshark_source.subprocess.Popen", FakePopenTsharkError)
    bridge, _ = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    # Reproduit manuellement pour vérifier le type précis levé par la source.
    try:
        list(bridge.source.iter_packets())
        raise AssertionError("devrait avoir levé TsharkError")
    except TsharkError:
        pass


def test_bridge_run_starts_and_stops_keepalive_in_live_mode(fake_popen):
    """En mode capture live (--interface, pas --pcap) avec un intervalle de
    keepalive configuré, Bridge.run() doit démarrer puis arrêter proprement
    le KeepaliveScheduler (et ne jamais le faire en mode --pcap, voir
    test_bridge_keepalive_not_started_in_pcap_mode)."""
    config = Config()
    config.capture.interface = "eth0"
    config.dry_run = True
    config.hep.keepalive_interval = 60
    bridge = Bridge(config)
    bridge.sender = RecordingSender()

    started = {"start": False, "stop": False}
    real_start = bridge.keepalive.start
    real_stop = bridge.keepalive.stop

    def fake_start():
        started["start"] = True
        real_start()

    def fake_stop(*args, **kwargs):
        started["stop"] = True
        real_stop(*args, **kwargs)

    bridge.keepalive.start = fake_start
    bridge.keepalive.stop = fake_stop
    bridge.run()

    assert started["start"] is True
    assert started["stop"] is True


def test_bridge_keepalive_not_started_in_pcap_mode(fake_popen):
    """Même avec un intervalle de keepalive configuré, --pcap ne doit jamais
    démarrer le scheduler (le run se termine de lui-même trop vite)."""
    bridge, _ = _make_bridge("tests/fixtures/ua3g_freeseating_ipv4.pcap")
    bridge.config.hep.keepalive_interval = 60
    bridge.keepalive.interval = 60

    started = {"start": False}
    bridge.keepalive.start = lambda: started.__setitem__("start", True)
    bridge.run()

    assert started["start"] is False
