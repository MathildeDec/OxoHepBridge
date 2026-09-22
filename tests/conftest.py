#!/usr/bin/env python3
"""Fixtures partagées : un fake de subprocess.Popen pour tshark -T ek."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import oxo_hep_bridge.tshark_source as source_module
from oxo_hep_bridge.tshark_source import flatten_layers, parse_ek_line

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class _FakeStream:
    """Objet stream-like simulable par subprocess.Popen, avec close()."""

    def __init__(self, lines: list[str]) -> None:
        self._iter = iter(lines)

    def __iter__(self):
        return self._iter

    def close(self) -> None:
        pass


class FakePopen:
    """Mimique de subprocess.Popen pour tester le source EK sans tshark réel.

    Initialise stdout à partir d'un fichier NDJSON (sortie `tshark -T ek`).
    Implémente l'API minimale utilisée par TsharkEKSource.iter_packets()
    (y compris poll/terminate/kill/wait pour la logique d'arrêt propre).
    """

    def __init__(
        self,
        cmd: list[str],
        stdout=None,
        stderr=None,
        text=None,
        bufsize=None,
        returncode: int = 0,
    ):
        self.cmd = cmd
        self._stdout_lines: list[str] = []
        self._stdout = None
        self._stderr = None
        self.returncode = returncode
        self._terminated = False
        self._killed = False

        if stdout == subprocess.PIPE:
            self._stdout_lines = self._read_fixture(cmd)
            self._stdout = _FakeStream(self._stdout_lines)
        if stderr == subprocess.PIPE:
            self._stderr = _FakeStream([])

    def _read_fixture(self, cmd: list[str]) -> list[str]:
        """Trouve le fichier -r dans le cmd, et lit la fixture .ek.ndjson correspondante."""
        pcap_arg = None
        for i, arg in enumerate(cmd):
            if arg == "-r" and i + 1 < len(cmd):
                pcap_arg = cmd[i + 1]
                break
        if pcap_arg is None:
            return []
        fixture_name = Path(pcap_arg).stem + ".ek.ndjson"
        fixture_path = FIXTURES_DIR / fixture_name
        if not fixture_path.exists():
            return []
        return fixture_path.read_text(encoding="utf-8").splitlines()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def poll(self):
        # On simule que le processus se termine dès qu'il a fini d'écrire
        # toutes ses lignes stdout (consommées jusqu'à la fin par le consumer).
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self._terminated = True

    def kill(self):
        self._killed = True

    @property
    def stdout(self):
        return self._stdout

    @property
    def stderr(self):
        return self._stderr


@pytest.fixture
def fake_popen(monkeypatch):
    """Patches le module subprocess.Popen pour renvoyer un fake contrôlé par tests."""
    monkeypatch.setattr(source_module.subprocess, "Popen", FakePopen)
    return FakePopen


@pytest.fixture
def ua3g_freeseating_ipv4_flat_lines():
    """Premier document .ndjson de la fixture ua3g_freeseating_ipv4, aplati."""
    path = FIXTURES_DIR / "ua3g_freeseating_ipv4.ek.ndjson"
    lines = path.read_text(encoding="utf-8").splitlines()
    flats = []
    for line in lines:
        layers = parse_ek_line(line)
        if layers is not None:
            flats.append(flatten_layers(layers))
    return flats


@pytest.fixture
def ua3g_freeseating_ipv6_flat_lines():
    """Documents .ndjson de la fixture ua3g_freeseating_ipv6, aplatis.

    Contrairement à la fixture ipv4 (``ua3g_freeseating_ipv4_flat_lines``),
    seule celle-ci contient des messages UA3G opcode 0x13 "IP Device
    Routing" envoyés par le terminal (champ ``ua3g_ua3g_ip_cs``, valeurs 0
    "Init" et 2 "Get Parameters Value Response" observées) — nécessaire pour
    tester ``ip_cs_name`` sur données réelles plutôt que synthétiques.
    """
    path = FIXTURES_DIR / "ua3g_freeseating_ipv6.ek.ndjson"
    lines = path.read_text(encoding="utf-8").splitlines()
    flats = []
    for line in lines:
        layers = parse_ek_line(line)
        if layers is not None:
            flats.append(flatten_layers(layers))
    return flats


@pytest.fixture
def uaudp_ipv6_flat_lines():
    """Documents .ndjson de la fixture uaudp_ipv6, aplatis."""
    path = FIXTURES_DIR / "uaudp_ipv6.ek.ndjson"
    lines = path.read_text(encoding="utf-8").splitlines()
    flats = []
    for line in lines:
        layers = parse_ek_line(line)
        if layers is not None:
            flats.append(flatten_layers(layers))
    return flats
