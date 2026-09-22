#!/usr/bin/env python3
"""Tests du module sd_notify (`sdnotify.py`) :

- `SdNotifier` : no-op silencieux sans `NOTIFY_SOCKET`, envoi effectif d'un
  datagramme Unix vers le chemin configuré (chemin filesystem et espace de
  noms abstrait), tolérance à un échec d'envoi (chemin invalide).
- `resolve_watchdog_interval()` : lecture de `WATCHDOG_USEC`/`WATCHDOG_PID`.
- `WatchdogScheduler` : déclenchement périodique à la moitié de l'intervalle,
  no-op quand désactivé, arrêt propre, idempotence de `start()`/`stop()`.
"""

from __future__ import annotations

import os
import socket
import time

import pytest

from oxo_hep_bridge.sdnotify import SdNotifier, WatchdogScheduler, resolve_watchdog_interval

# --- SdNotifier ---


def test_notifier_disabled_without_socket_path():
    notifier = SdNotifier(socket_path=None)
    assert notifier.enabled is False
    assert notifier.ready() is False
    assert notifier.stopping() is False
    assert notifier.watchdog() is False
    assert notifier.status("hello") is False


def test_notifier_reads_notify_socket_env_by_default(monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    notifier = SdNotifier()
    assert notifier.enabled is True
    assert notifier.socket_path == "/run/systemd/notify"


def test_notifier_explicit_socket_path_overrides_env(monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", "/should/not/be/used")
    notifier = SdNotifier(socket_path="/explicit/path")
    assert notifier.socket_path == "/explicit/path"


def test_notifier_sends_ready_over_real_unix_socket(tmp_path):
    """Vérifie le datagramme réellement émis, via une vraie socket Unix
    (pas de dépendance à un vrai systemd — juste AF_UNIX de la stdlib)."""
    sock_path = str(tmp_path / "notify.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.bind(sock_path)
    listener.settimeout(2.0)
    try:
        notifier = SdNotifier(socket_path=sock_path)
        assert notifier.ready() is True
        data, _addr = listener.recvfrom(4096)
        assert data == b"READY=1"

        assert notifier.stopping() is True
        data, _addr = listener.recvfrom(4096)
        assert data == b"STOPPING=1"

        assert notifier.watchdog() is True
        data, _addr = listener.recvfrom(4096)
        assert data == b"WATCHDOG=1"

        assert notifier.status("en cours de traitement") is True
        data, _addr = listener.recvfrom(4096)
        assert data == b"STATUS=en cours de traitement"
    finally:
        listener.close()


def test_notifier_supports_abstract_namespace_socket():
    """systemd utilise parfois un chemin d'espace de noms abstrait Linux
    (préfixé par '@'), sans entrée dans le filesystem."""
    abstract_name = f"oxo-hep-bridge-test-{os.getpid()}"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.bind("\0" + abstract_name)
    listener.settimeout(2.0)
    try:
        notifier = SdNotifier(socket_path="@" + abstract_name)
        assert notifier.ready() is True
        data, _addr = listener.recvfrom(4096)
        assert data == b"READY=1"
    finally:
        listener.close()


def test_notifier_send_failure_is_caught_and_returns_false():
    """Un chemin de socket qui n'existe pas ne doit jamais lever, juste
    logger un avertissement et retourner False (best-effort, pas fatal)."""
    notifier = SdNotifier(socket_path="/tmp/oxo-hep-bridge-does-not-exist.sock")
    assert notifier.ready() is False


# --- resolve_watchdog_interval ---


def test_resolve_watchdog_interval_absent_returns_none():
    assert resolve_watchdog_interval(env={}) is None


def test_resolve_watchdog_interval_converts_microseconds_to_seconds():
    assert resolve_watchdog_interval(env={"WATCHDOG_USEC": "30000000"}) == 30.0


def test_resolve_watchdog_interval_non_numeric_returns_none():
    assert resolve_watchdog_interval(env={"WATCHDOG_USEC": "not-a-number"}) is None


def test_resolve_watchdog_interval_zero_or_negative_returns_none():
    assert resolve_watchdog_interval(env={"WATCHDOG_USEC": "0"}) is None
    assert resolve_watchdog_interval(env={"WATCHDOG_USEC": "-5"}) is None


def test_resolve_watchdog_interval_matching_pid_is_used():
    env = {"WATCHDOG_USEC": "10000000", "WATCHDOG_PID": str(os.getpid())}
    assert resolve_watchdog_interval(env=env) == 10.0


def test_resolve_watchdog_interval_mismatched_pid_returns_none():
    other_pid = os.getpid() + 1
    env = {"WATCHDOG_USEC": "10000000", "WATCHDOG_PID": str(other_pid)}
    assert resolve_watchdog_interval(env=env) is None


def test_resolve_watchdog_interval_reads_real_environ_by_default(monkeypatch):
    monkeypatch.setenv("WATCHDOG_USEC", "5000000")
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    assert resolve_watchdog_interval() == 5.0


# --- WatchdogScheduler ---


class RecordingNotifier(SdNotifier):
    """SdNotifier factice qui compte les pings watchdog envoyés."""

    def __init__(self) -> None:
        super().__init__(socket_path="unused")
        self.watchdog_calls = 0

    @property
    def enabled(self) -> bool:  # toujours "actif" pour le test, sans vraie socket
        return True

    def watchdog(self) -> bool:  # noqa: D401 - override de test
        self.watchdog_calls += 1
        return True


def test_scheduler_disabled_when_interval_is_none():
    notifier = RecordingNotifier()
    scheduler = WatchdogScheduler(notifier, None)
    assert scheduler.enabled is False

    scheduler.start()  # doit être un no-op
    time.sleep(0.05)
    scheduler.stop()

    assert notifier.watchdog_calls == 0


def test_scheduler_disabled_when_notifier_disabled():
    notifier = SdNotifier(socket_path=None)  # enabled=False
    scheduler = WatchdogScheduler(notifier, 0.05)
    assert scheduler.enabled is False


def test_scheduler_pings_at_half_the_watchdog_interval():
    notifier = RecordingNotifier()
    scheduler = WatchdogScheduler(notifier, 0.1)  # notification toutes les 0.05s
    assert scheduler.enabled is True
    assert scheduler._notify_every == 0.05

    scheduler.start()
    time.sleep(0.23)
    scheduler.stop()

    # ~4 cycles en 0.23s à 0.05s d'intervalle ; on tolère la variance de scheduling
    assert notifier.watchdog_calls >= 2

    # après stop(), plus aucun envoi
    count_after_stop = notifier.watchdog_calls
    time.sleep(0.15)
    assert notifier.watchdog_calls == count_after_stop


def test_scheduler_start_is_idempotent():
    notifier = RecordingNotifier()
    scheduler = WatchdogScheduler(notifier, 0.05)
    scheduler.start()
    first_thread = scheduler._thread
    scheduler.start()  # ne doit pas relancer un second thread
    assert scheduler._thread is first_thread
    scheduler.stop()
    scheduler.stop()  # idempotent, ne doit pas lever


def test_run_raises_runtime_error_if_notify_every_is_none():
    """Garde explicite (session 40, remplace un ancien `assert` supprimable
    sous `python -O`) : `_run()` n'est normalement jamais appelé avec
    `_notify_every` à `None` (`enabled`/`start()` l'en empêchent), mais si
    l'invariant était un jour violé, il doit lever `RuntimeError` plutôt que
    de planter plus loin sur `self._stop_event.wait(None)`. Appelé
    directement ici (sans thread) : l'exception est donc synchrone,
    contrairement à un usage normal via `start()`."""
    notifier = RecordingNotifier()
    scheduler = WatchdogScheduler(notifier, None)  # _notify_every reste None
    with pytest.raises(RuntimeError, match="_notify_every"):
        scheduler._run()
