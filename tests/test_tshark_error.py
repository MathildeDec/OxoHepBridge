#!/usr/bin/env python3
"""Tests de gestion d'erreur du subprocess tshark : code de sortie non nul
doit lever TsharkError, plutôt que d'être ignoré silencieusement."""

from __future__ import annotations

from conftest import FakePopen, _FakeStream
from oxo_hep_bridge.tshark_source import TsharkEKSource, TsharkError


def test_tshark_nonzero_exit_raises_error(monkeypatch):
    """Si tshark se termine avec un code non nul et qu'on n'a pas interrompu
    nous-même le flux, TsharkError doit être levée."""

    class FakePopenError(FakePopen):
        """Fake tshark qui meurt immédiatement avec un code d'erreur."""

        def __init__(self, cmd, stdout=None, stderr=None, text=None, bufsize=None):
            super().__init__(cmd, stdout=stdout, stderr=stderr, text=text, bufsize=bufsize)
            # tshark a planté : pas de stdout, code d'erreur
            self._stdout = _FakeStream([])
            self.returncode = 1

        def poll(self):
            return 1  # déjà terminé en erreur

    monkeypatch.setattr("oxo_hep_bridge.tshark_source.subprocess.Popen", FakePopenError)

    source = TsharkEKSource(pcap="/tmp/fake.pcap")
    try:
        list(source.iter_packets())
        raise AssertionError("devrait avoir levé TsharkError")
    except TsharkError as exc:
        assert "code 1" in str(exc) or "1" in str(exc)


def test_tshark_normal_exit_does_not_raise(monkeypatch):
    """Un code de sortie 0 (succès normal après consommation du flux) ne lève pas."""

    class FakePopenOk(FakePopen):
        pass

    monkeypatch.setattr("oxo_hep_bridge.tshark_source.subprocess.Popen", FakePopenOk)

    source = TsharkEKSource(pcap="/tmp/fake.pcap")
    # FakePopen lit la fixture correspondante si elle existe, sinon liste vide
    packets = list(source.iter_packets())
    assert isinstance(packets, list)
