#!/usr/bin/env python3
"""Tests de l'intégration sd_notify dans `cli.main()`.

Contexte : `cli.main()` doit signaler `READY=1` une fois la configuration
validée et `Bridge` construit, `STOPPING=1` avant de quitter (chemin normal,
signal ou exception), et démarrer/arrêter le `WatchdogScheduler` autour de
`bridge.run()` — sans dépendre d'un vrai `NOTIFY_SOCKET` systemd (une socket
Unix réelle, locale au test, sert de collecteur factice).
"""

from __future__ import annotations

import signal
import socket
import time

import pytest

from oxo_hep_bridge import cli


class _FakeBridge:
    """Remplace Bridge dans cli.main() (voir test_signal_handling.py)."""

    run_return: int = 0
    run_side_effect: BaseException | None = None

    def __init__(self, config) -> None:  # noqa: D401 - signature imposée par cli.main()
        self.config = config

    def run(self) -> int:
        if type(self).run_side_effect is not None:
            raise type(self).run_side_effect
        return type(self).run_return


@pytest.fixture(autouse=True)
def _reset_fake_bridge():
    _FakeBridge.run_return = 0
    _FakeBridge.run_side_effect = None
    yield
    _FakeBridge.run_return = 0
    _FakeBridge.run_side_effect = None


@pytest.fixture
def patched_bridge(monkeypatch):
    monkeypatch.setattr(cli, "Bridge", _FakeBridge)
    return _FakeBridge


@pytest.fixture
def notify_listener(tmp_path, monkeypatch):
    """Socket Unix factice servant de collecteur sd_notify pour le test,
    branchée via NOTIFY_SOCKET comme le ferait systemd."""
    sock_path = str(tmp_path / "notify.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.bind(sock_path)
    listener.settimeout(2.0)
    monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
    yield listener
    listener.close()


def _recv_all(listener: socket.socket) -> list[bytes]:
    messages = []
    listener.settimeout(0.2)
    try:
        while True:
            messages.append(listener.recvfrom(4096)[0])
    except TimeoutError:
        pass
    return messages


def test_main_sends_ready_then_stopping_on_clean_run(patched_bridge, notify_listener):
    rc = cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])

    assert rc == 0
    messages = _recv_all(notify_listener)
    assert messages == [b"READY=1", b"STOPPING=1"]


def test_main_sends_stopping_on_keyboard_interrupt(patched_bridge, notify_listener):
    patched_bridge.run_side_effect = KeyboardInterrupt
    rc = cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])

    assert rc == 130
    messages = _recv_all(notify_listener)
    assert messages == [b"READY=1", b"STOPPING=1"]


def test_main_sends_stopping_on_fatal_exception(patched_bridge, notify_listener):
    patched_bridge.run_side_effect = RuntimeError("boom")
    rc = cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])

    assert rc == 1
    messages = _recv_all(notify_listener)
    assert messages == [b"READY=1", b"STOPPING=1"]


def test_main_is_silent_without_notify_socket(patched_bridge, monkeypatch):
    """Hors service systemd (NOTIFY_SOCKET absente), aucune notification
    n'est tentée — comportement historique inchangé, aucune exception."""
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    rc = cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])
    assert rc == 0


def test_main_starts_and_stops_watchdog_around_run(patched_bridge, notify_listener, monkeypatch):
    """Avec WATCHDOG_USEC positionné, un ping WATCHDOG=1 doit apparaître
    entre READY=1 et STOPPING=1 sur un run suffisamment long."""
    monkeypatch.setenv("WATCHDOG_USEC", "60000")  # 60ms -> ping toutes les 30ms
    monkeypatch.delenv("WATCHDOG_PID", raising=False)

    class _SlowBridge(_FakeBridge):
        def run(self) -> int:
            time.sleep(0.15)
            return super().run()

    monkeypatch.setattr(cli, "Bridge", _SlowBridge)

    rc = cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])

    assert rc == 0
    messages = _recv_all(notify_listener)
    assert messages[0] == b"READY=1"
    assert messages[-1] == b"STOPPING=1"
    assert messages.count(b"WATCHDOG=1") >= 1


def test_signal_handlers_still_restored_with_sdnotify_active(patched_bridge, notify_listener):
    """La notification sd_notify ne doit pas casser la restauration des
    handlers SIGINT/SIGTERM d'origine (garde-fou de non-régression, voir
    test_signal_handling.py)."""
    original_sigterm = signal.getsignal(signal.SIGTERM)
    cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])
    assert signal.getsignal(signal.SIGTERM) == original_sigterm
