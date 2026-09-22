#!/usr/bin/env python3
"""Tests de la gestion des signaux d'arrêt (SIGINT + SIGTERM) dans cli.main().

Contexte : le pont tourne en production comme service systemd (voir
systemd/oxo-hep-bridge.service, Type=simple, pas de KillSignal custom).
`systemctl stop`/un redémarrage de service envoie SIGTERM par défaut, pas
SIGINT. Avant ce correctif, seul SIGINT (Ctrl-C) déclenchait un arrêt propre
(fermeture du subprocess tshark, de la socket UDP, arrêt du keepalive,
résumé de stats) : un `systemctl stop` tuait le process sans rien de tout
ça. Ces tests valident que SIGTERM suit désormais exactement le même chemin
que SIGINT, sans dépendre d'un envoi réel de signal OS (ce qui tuerait le
process de test si le correctif venait à régresser) : on capture le handler
installé par main() pendant l'exécution et on vérifie son comportement
directement.
"""

from __future__ import annotations

import signal

import pytest

from oxo_hep_bridge import cli


class _FakeBridge:
    """Remplace Bridge dans cli.main() pour ne pas dépendre de tshark/pcap réel."""

    captured_handlers: dict[int, object] = {}
    run_return: int = 0
    run_side_effect: BaseException | None = None

    def __init__(self, config) -> None:  # noqa: D401 - signature imposée par cli.main()
        self.config = config

    def run(self) -> int:
        # Capture les handlers installés par main() pendant que run() est actif,
        # pour les tests qui inspectent l'état sans dépendre d'un vrai signal OS.
        type(self).captured_handlers = {
            signal.SIGINT: signal.getsignal(signal.SIGINT),
            signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        }
        if type(self).run_side_effect is not None:
            raise type(self).run_side_effect
        return type(self).run_return


@pytest.fixture(autouse=True)
def _reset_fake_bridge():
    _FakeBridge.captured_handlers = {}
    _FakeBridge.run_return = 0
    _FakeBridge.run_side_effect = None
    yield
    _FakeBridge.captured_handlers = {}
    _FakeBridge.run_return = 0
    _FakeBridge.run_side_effect = None


@pytest.fixture
def patched_bridge(monkeypatch):
    monkeypatch.setattr(cli, "Bridge", _FakeBridge)
    return _FakeBridge


def test_sigint_and_sigterm_handlers_installed_during_run(patched_bridge):
    """Pendant bridge.run(), SIGINT et SIGTERM doivent pointer vers le même
    handler personnalisé (pas le handler par défaut ni SIG_DFL)."""
    rc = cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])

    assert rc == 0
    sigint_handler = patched_bridge.captured_handlers[signal.SIGINT]
    sigterm_handler = patched_bridge.captured_handlers[signal.SIGTERM]
    assert sigint_handler is not None
    assert sigint_handler is not signal.SIG_DFL
    assert sigint_handler is not signal.SIG_IGN
    # Les deux signaux doivent partager exactement le même handler.
    assert sigint_handler is sigterm_handler


def test_installed_handler_raises_keyboardinterrupt(patched_bridge):
    """Le handler installé pour SIGINT/SIGTERM doit lever KeyboardInterrupt,
    ce qui déclenche l'arrêt propre dans le bloc except de main()."""
    cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])

    handler = patched_bridge.captured_handlers[signal.SIGTERM]
    with pytest.raises(KeyboardInterrupt):
        handler(signal.SIGTERM, None)


def test_sigterm_like_shutdown_returns_130(patched_bridge):
    """Si run() est interrompu par KeyboardInterrupt (ce que provoque le
    handler SIGTERM), main() doit retourner 130 comme pour Ctrl-C."""
    patched_bridge.run_side_effect = KeyboardInterrupt
    rc = cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])
    assert rc == 130


def test_original_signal_handlers_restored_after_run(patched_bridge):
    """Une fois main() terminé, les handlers SIGINT/SIGTERM d'origine (ceux
    en place avant l'appel) doivent être restaurés, pour ne pas laisser un
    handler orphelin actif après un run (utile en tests, en usage bibliothèque,
    ou pour des appels successifs à main() dans le même process)."""
    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])

    assert signal.getsignal(signal.SIGINT) == original_sigint
    assert signal.getsignal(signal.SIGTERM) == original_sigterm


def test_original_handlers_restored_even_on_fatal_exception(patched_bridge):
    """La restauration des handlers doit avoir lieu même si run() lève une
    exception inattendue (pas seulement KeyboardInterrupt)."""
    original_sigterm = signal.getsignal(signal.SIGTERM)
    patched_bridge.run_side_effect = RuntimeError("boom")

    rc = cli.main(["--pcap", "/tmp/does-not-need-to-exist.pcap", "--dry-run"])

    assert rc == 1
    assert signal.getsignal(signal.SIGTERM) == original_sigterm
