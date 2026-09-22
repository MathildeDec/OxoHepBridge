#!/usr/bin/env python3
"""Tests du parseur EK (tshark_source.py) : lignes d'action, aplatissement,
tolérance aux lignes malformées."""

from __future__ import annotations

import json
import subprocess
import threading

import pytest

from conftest import FakePopen, _FakeStream
from oxo_hep_bridge.tshark_source import TsharkEKSource, flatten_layers, parse_ek_line


def test_parse_ek_line_skips_bulk_index_action():
    line = '{"index":{"_index":"packets-2017-11-17"}}'
    assert parse_ek_line(line) is None


def test_parse_ek_line_skips_blank_line():
    assert parse_ek_line("") is None
    assert parse_ek_line("   \n") is None


def test_parse_ek_line_skips_malformed_json():
    assert parse_ek_line("{not valid json") is None


def test_parse_ek_line_extracts_layers():
    doc = {"timestamp": "123", "layers": {"uaudp": {"uaudp_uaudp_opcode": "4"}}}
    layers = parse_ek_line(json.dumps(doc))
    assert layers == {"uaudp": {"uaudp_uaudp_opcode": "4"}}


def test_flatten_layers_merges_all_protocols():
    layers = {
        "uaudp": {"uaudp_uaudp_opcode": "7"},
        "udp": {"udp_udp_srcport": "32640", "text": "Timestamps"},
    }
    flat = flatten_layers(layers)
    assert flat["uaudp_uaudp_opcode"] == "7"
    assert flat["udp_udp_srcport"] == "32640"
    assert "text" not in flat  # champ méta tshark, non pertinent


def test_flatten_layers_preserves_lists_for_noe():
    layers = {
        "ua": {
            "noe": [
                {"noe_noe_objectid": "4867"},
                {"noe_noe_objectid": "4864"},
            ]
        }
    }
    flat = flatten_layers(layers)
    assert isinstance(flat["noe"], list)
    assert len(flat["noe"]) == 2


def test_iter_packets_reads_real_fixture(fake_popen):
    """Vérifie que le pipeline lit une vraie fixture -T ek de bout en bout."""
    source = TsharkEKSource(pcap="tests/fixtures/ua3g_freeseating_ipv4.pcap")
    packets = list(source.iter_packets())
    assert len(packets) > 0
    # au moins un paquet doit porter des champs uaudp
    assert any(k.startswith("uaudp_uaudp_") for pkt in packets for k in pkt)


def test_build_cmd_includes_decode_as_and_bpf():
    source = TsharkEKSource(
        interface="eth0", bpf="udp port 32640", decode_as=["udp.port==32640,uaudp"]
    )
    cmd = source._build_cmd()
    assert "-i" in cmd and "eth0" in cmd
    assert "-f" in cmd and "udp port 32640" in cmd
    assert "-d" in cmd and "udp.port==32640,uaudp" in cmd
    assert "-T" in cmd and "ek" in cmd


def test_requires_interface_or_pcap():
    with pytest.raises(ValueError, match="interface ou pcap"):
        TsharkEKSource()


# --- parse_ek_line : cas limites non couverts ci-dessus ---------------------


def test_parse_ek_line_skips_non_object_json():
    """Une ligne JSON syntaxiquement valide mais qui n'est pas un objet
    (ex: une liste ou un scalaire nu) doit être ignorée plutôt que de faire
    planter le flattening en aval."""
    assert parse_ek_line("[1, 2, 3]") is None
    assert parse_ek_line('"just a string"') is None


def test_parse_ek_line_skips_document_without_layers_dict():
    """Un document JSON valide, sans lignes d'action bulk, mais dont
    `layers` est absent ou n'est pas un dict (ex: bruit tshark inattendu)
    doit être ignoré."""
    assert parse_ek_line('{"timestamp": "123"}') is None
    assert parse_ek_line('{"timestamp": "123", "layers": "not-a-dict"}') is None


def test_flatten_layers_skips_non_dict_protocol_values():
    """Un protocole dont la valeur n'est pas un dict (bruit tshark) doit
    être ignoré sans lever, plutôt que de faire planter .items()."""
    layers = {
        "uaudp": {"uaudp_uaudp_opcode": "7"},
        "weird_protocol": "not-a-dict",
    }
    flat = flatten_layers(layers)
    assert flat == {"uaudp_uaudp_opcode": "7"}


# --- _build_cmd : options non couvertes ci-dessus ---------------------------


def test_build_cmd_omits_dash_l_when_not_line_buffered():
    source = TsharkEKSource(pcap="/tmp/c.pcap", line_buffered=False)
    cmd = source._build_cmd()
    assert "-l" not in cmd


def test_build_cmd_includes_dash_e_for_each_field():
    source = TsharkEKSource(pcap="/tmp/c.pcap", fields=["uaudp.opcode", "noe.class"])
    cmd = source._build_cmd()
    assert cmd.count("-e") == 2
    assert "uaudp.opcode" in cmd
    assert "noe.class" in cmd


# --- iter_packets : arrêt propre du subprocess (terminate/kill/stderr) -----


class FakePopenSlowToExit(FakePopen):
    """Fake tshark qui met du temps à répondre à wait() (simule une capture
    live encore active) : le 1er wait() lève TimeoutExpired, terminate() est
    appelé, puis le 2e wait() réussit. Porte aussi des lignes stderr pour
    couvrir le drainage/log dédié."""

    def __init__(self, cmd, stdout=None, stderr=None, text=None, bufsize=None):
        super().__init__(cmd, stdout=stdout, stderr=stderr, text=text, bufsize=bufsize)
        self._stderr = _FakeStream(["tshark: avertissement de test", "encore une ligne"])
        self._wait_calls = 0

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls == 1:
            raise subprocess.TimeoutExpired(cmd="tshark", timeout=timeout)
        return 0

    def poll(self):
        return 0 if self._wait_calls >= 1 else None


def test_iter_packets_terminates_slow_tshark_and_logs_stderr(monkeypatch):
    """Si tshark ne répond pas immédiatement à wait() après épuisement de
    stdout, iter_packets() doit appeler terminate() puis réussir sur le
    2e wait(), et journaliser les dernières lignes stderr capturées."""
    monkeypatch.setattr("oxo_hep_bridge.tshark_source.subprocess.Popen", FakePopenSlowToExit)
    source = TsharkEKSource(pcap="tests/fixtures/ua3g_freeseating_ipv4.pcap")
    packets = list(source.iter_packets())  # ne doit pas lever
    assert isinstance(packets, list)


class FakePopenNeedsKill(FakePopen):
    """Fake tshark qui ne répond ni à wait() ni à terminate() : les deux
    premiers wait() lèvent TimeoutExpired, kill() est alors appelé, et le
    3e wait() (après kill) réussit."""

    def __init__(self, cmd, stdout=None, stderr=None, text=None, bufsize=None):
        super().__init__(cmd, stdout=stdout, stderr=stderr, text=text, bufsize=bufsize)
        self._stderr = _FakeStream([])
        self._wait_calls = 0
        self.killed = False

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls <= 2:
            raise subprocess.TimeoutExpired(cmd="tshark", timeout=timeout)
        return 0

    def kill(self):
        self.killed = True
        super().kill()


def test_iter_packets_kills_tshark_when_terminate_also_times_out(monkeypatch):
    """Si même terminate() ne suffit pas (2e wait() en timeout aussi),
    iter_packets() doit escalader vers kill()."""
    monkeypatch.setattr("oxo_hep_bridge.tshark_source.subprocess.Popen", FakePopenNeedsKill)
    source = TsharkEKSource(pcap="tests/fixtures/ua3g_freeseating_ipv4.pcap")
    packets = list(source.iter_packets())  # ne doit pas lever
    assert isinstance(packets, list)


class FakePopenNoStdout(FakePopen):
    """Fake tshark dont `stdout` reste `None` malgré `stdout=PIPE` demandé —
    cas normalement impossible en pratique (Popen honore toujours cette
    demande), pour vérifier la garde explicite de `iter_packets()`."""

    def __init__(self, cmd, stdout=None, stderr=None, text=None, bufsize=None):
        super().__init__(cmd, stdout=stdout, stderr=stderr, text=text, bufsize=bufsize)
        self._stdout = None


def test_iter_packets_raises_runtime_error_if_stdout_is_none(monkeypatch):
    """Garde explicite (session 40, remplace un ancien `assert` supprimable
    sous `python -O`) : si `proc.stdout` est `None` malgré `stdout=PIPE` —
    cas normalement impossible —, `iter_packets()` doit lever
    `RuntimeError` plutôt que de planter plus loin avec une erreur
    confuse (`TypeError` sur `for line in None`)."""
    monkeypatch.setattr("oxo_hep_bridge.tshark_source.subprocess.Popen", FakePopenNoStdout)
    source = TsharkEKSource(pcap="tests/fixtures/ua3g_freeseating_ipv4.pcap")
    with pytest.raises(RuntimeError, match="proc.stdout"):
        list(source.iter_packets())


class FakePopenNoStderr(FakePopen):
    """Même principe que `FakePopenNoStdout`, côté `stderr` cette fois."""

    def __init__(self, cmd, stdout=None, stderr=None, text=None, bufsize=None):
        super().__init__(cmd, stdout=stdout, stderr=stderr, text=text, bufsize=bufsize)
        self._stderr = None


def test_drain_stderr_raises_runtime_error_if_stderr_is_none(monkeypatch):
    """Même garde côté `stderr`, exercée dans le thread daemon de drainage
    (`_drain_stderr`) plutôt que dans le flux principal — une exception
    non gérée dans un thread ne se propage pas à l'appelant : capturée ici
    via `threading.excepthook` plutôt que `pytest.raises` autour de
    `iter_packets()` (qui, lui, ne lève pas : seul le thread de fond est
    affecté, `stdout` reste normal dans ce fake)."""
    monkeypatch.setattr("oxo_hep_bridge.tshark_source.subprocess.Popen", FakePopenNoStderr)
    caught: list[BaseException] = []
    original_hook = threading.excepthook
    threading.excepthook = lambda args: caught.append(args.exc_value)
    try:
        source = TsharkEKSource(pcap="tests/fixtures/ua3g_freeseating_ipv4.pcap")
        packets = list(source.iter_packets())  # stdout normal, ne doit pas lever ici
    finally:
        threading.excepthook = original_hook

    assert isinstance(packets, list)
    assert len(caught) == 1
    assert isinstance(caught[0], RuntimeError)
    assert "proc.stderr" in str(caught[0])


def test_iter_packets_reraises_on_generator_exit_without_tshark_error(fake_popen):
    """Un `break` côté appelant (GeneratorExit à la fermeture du générateur)
    ne doit jamais être requalifié en TsharkError, même si le processus fake
    a un code de retour non nul par ailleurs — c'est une interruption
    volontaire, pas une panne."""
    source = TsharkEKSource(pcap="tests/fixtures/ua3g_freeseating_ipv4.pcap")
    gen = source.iter_packets()
    next(gen)  # démarre l'itération
    gen.close()  # déclenche GeneratorExit dans le générateur
