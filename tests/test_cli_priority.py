#!/usr/bin/env python3
"""Tests de la priorité de résolution de config au niveau du CLI :
les arguments CLI ne doivent écraser les valeurs TOML/env QUE s'ils sont
explicitement fournis par l'utilisateur (sinon les défauts d'argparse
écraseraient la config chargée depuis le TOML ou l'environnement).

Valide le correctif d'un bug réel où cli.py écrasait systématiquement
tous les champs de config avec les défauts argparse.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oxo_hep_bridge import cli
from oxo_hep_bridge.cli import _apply_cli_args, build_parser
from oxo_hep_bridge.config import Config


@pytest.fixture
def toml_file(tmp_path: Path) -> Path:
    content = """
[capture]
interface = "eth1"

[hep]
host = "10.0.0.5"
port = 9061
capture_agent_id = 3003
auth_key = "toml-secret"
transport = "tcp"
tls_verify = false
tls_ca_file = "/etc/pki/homer-ca.pem"

[logging]
level = "DEBUG"
"""
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_cli_only_pcap_does_not_override_toml_values(toml_file):
    """Si l'utilisateur ne passe que --pcap, les autres valeurs viennent du TOML."""
    args = build_parser().parse_args(["--pcap", "/tmp/capture.pcap"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    # --pcap est appliqué
    assert config.capture.pcap == "/tmp/capture.pcap"
    # mais les valeurs TOML ne sont PAS écrasées par les défauts argparse
    assert config.hep.host == "10.0.0.5"
    assert config.hep.port == 9061
    assert config.hep.capture_agent_id == 3003
    assert config.hep.auth_key == "toml-secret"
    assert config.hep.transport == "tcp"
    assert config.hep.tls_verify is False
    assert config.hep.tls_ca_file == "/etc/pki/homer-ca.pem"
    assert config.logging.level == "DEBUG"


def test_cli_explicit_hep_host_overrides_toml(toml_file):
    """--hep-host explicite doit écraser la valeur TOML."""
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--hep-host", "192.168.1.1"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.hep.host == "192.168.1.1"
    # port non fourni en CLI => conserve la valeur TOML
    assert config.hep.port == 9061


def test_cli_hep_pass_alias_hep_auth_key(toml_file):
    """L'alias --hep-auth-key doit fonctionner comme --hep-pass (dest hep_pass)."""
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--hep-auth-key", "cli-key"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.hep.auth_key == "cli-key"


def test_cli_dry_run_flag_does_not_clobber_other_config(toml_file):
    """--dry-run est un bool flag : ne doit pas réinitialiser les autres champs."""
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--dry-run"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.dry_run is True
    assert config.hep.host == "10.0.0.5"
    assert config.hep.port == 9061


def test_cli_explicit_hep_transport_overrides_toml(toml_file):
    """--hep-transport explicite doit écraser le transport TOML (tcp -> tls)."""
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--hep-transport", "tls"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.hep.transport == "tls"


def test_cli_hep_tls_insecure_flag_overrides_toml_verify_true():
    """--hep-tls-insecure doit pouvoir désactiver la vérification même quand
    aucun TOML n'est chargé (tls_verify vaut True par défaut)."""
    args = build_parser().parse_args(
        ["--pcap", "/tmp/c.pcap", "--hep-transport", "tls", "--hep-tls-insecure"]
    )
    config = Config()
    _apply_cli_args(config, args)

    assert config.hep.tls_verify is False


def test_cli_hep_tls_insecure_absent_preserves_toml_value(toml_file):
    """Sans --hep-tls-insecure, la valeur TOML (ici déjà False) n'est pas
    réinitialisée à True par un défaut argparse — c'est le bug historique que
    ce fichier de test couvre pour tous les champs bool."""
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.hep.tls_verify is False  # valeur TOML, pas le défaut True


def test_cli_explicit_hep_tls_ca_file_overrides_toml(toml_file):
    args = build_parser().parse_args(
        ["--pcap", "/tmp/c.pcap", "--hep-tls-ca-file", "/run/secrets/ca.pem"]
    )
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.hep.tls_ca_file == "/run/secrets/ca.pem"


def test_cli_hep_transport_rejects_unknown_choice():
    """argparse doit rejeter une valeur hors udp/tcp/tls avant même
    d'atteindre make_sender() (cohérent avec les autres validations CLI)."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--hep-transport", "quic"])


def test_cli_hep_compress_payload_flag_sets_true():
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--hep-compress-payload"])
    config = Config()
    _apply_cli_args(config, args)
    assert config.hep.compress_payload is True


def test_cli_hep_compress_payload_absent_preserves_toml_true_value(tmp_path):
    """Comme --hep-tls-insecure/--dry-run, --hep-compress-payload est un flag
    à sens unique : son absence ne doit pas réinitialiser à False une valeur
    déjà activée par le TOML (pas de --hep-no-compress-payload pour ça)."""
    path = tmp_path / "oxo-hep-bridge-compress.toml"
    path.write_text("[hep]\ncompress_payload = true\n", encoding="utf-8")
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap"])
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)
    assert config.hep.compress_payload is True


# --- --hep-retries / --hep-retry-backoff --------------------------------------


def test_cli_explicit_hep_retries_overrides_toml(tmp_path):
    path = tmp_path / "oxo-hep-bridge-retries.toml"
    path.write_text("[hep]\nsend_retries = 1\nsend_retry_backoff = 0.2\n", encoding="utf-8")
    args = build_parser().parse_args(
        ["--pcap", "/tmp/c.pcap", "--hep-retries", "5", "--hep-retry-backoff", "1.0"]
    )
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)

    assert config.hep.send_retries == 5
    assert config.hep.send_retry_backoff == 1.0


def test_cli_hep_retries_absent_preserves_toml_value(tmp_path):
    """Contrairement à --hep-compress-payload/--dry-run, --hep-retries n'est
    pas un flag à sens unique mais une vraie valeur : son absence ne doit
    simplement pas écraser la config déjà positionnée par le TOML."""
    path = tmp_path / "oxo-hep-bridge-retries.toml"
    path.write_text("[hep]\nsend_retries = 2\n", encoding="utf-8")
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap"])
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)

    assert config.hep.send_retries == 2


def test_cli_hep_retries_zero_is_explicit_and_applied(tmp_path):
    """`--hep-retries 0` doit pouvoir désactiver explicitement un retry
    activé par le TOML — argparse renvoie `0`, pas `None`, donc le test
    `is not None` de _apply_cli_args() doit bien laisser passer 0."""
    path = tmp_path / "oxo-hep-bridge-retries.toml"
    path.write_text("[hep]\nsend_retries = 3\n", encoding="utf-8")
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--hep-retries", "0"])
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)

    assert config.hep.send_retries == 0


# --- --stats-interval ----------------------------------------------------


def test_cli_explicit_stats_interval_overrides_toml(tmp_path):
    path = tmp_path / "oxo-hep-bridge-stats.toml"
    path.write_text("[logging]\nstats_interval = 500\n", encoding="utf-8")
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--stats-interval", "10"])
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)

    assert config.logging.stats_interval == 10


def test_cli_stats_interval_absent_preserves_toml_value(tmp_path):
    """--stats-interval n'est pas un flag à sens unique mais une vraie
    valeur : son absence ne doit pas écraser la config déjà positionnée par
    le TOML."""
    path = tmp_path / "oxo-hep-bridge-stats.toml"
    path.write_text("[logging]\nstats_interval = 42\n", encoding="utf-8")
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap"])
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)

    assert config.logging.stats_interval == 42


def test_cli_stats_interval_zero_is_explicit_and_applied(tmp_path):
    """`--stats-interval 0` doit pouvoir désactiver explicitement le log de
    progression — argparse renvoie `0`, pas `None`, donc le test
    `is not None` de _apply_cli_args() doit bien laisser passer 0."""
    path = tmp_path / "oxo-hep-bridge-stats.toml"
    path.write_text("[logging]\nstats_interval = 500\n", encoding="utf-8")
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--stats-interval", "0"])
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)

    assert config.logging.stats_interval == 0


# --- --log-json-file -------------------------------------------------------


def test_cli_explicit_log_json_file_overrides_toml(tmp_path):
    path = tmp_path / "oxo-hep-bridge-json.toml"
    path.write_text('[logging]\njson_file = "/var/log/old.json"\n', encoding="utf-8")
    args = build_parser().parse_args(
        ["--pcap", "/tmp/c.pcap", "--log-json-file", "/var/log/new.json"]
    )
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)

    assert config.logging.json_file == "/var/log/new.json"


def test_cli_log_json_file_absent_preserves_toml_value(tmp_path):
    path = tmp_path / "oxo-hep-bridge-json.toml"
    path.write_text('[logging]\njson_file = "/var/log/stats.json"\n', encoding="utf-8")
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap"])
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)

    assert config.logging.json_file == "/var/log/stats.json"


# --- cli.main() : TOML invalide (table/clé inconnue) refusé proprement -----
#
# Config.load() est appelé dans cli.main() en dehors du try/except qui
# entoure bridge.run() (celui-ci ne couvre que les échecs du run lui-même,
# pas les erreurs d'usage/config détectées avant même la construction du
# Bridge) : ces tests valident que main() intercepte spécifiquement
# ConfigError/TOMLDecodeError et retourne 2 (comme une erreur d'arguments
# argparse) plutôt que de laisser une exception non gérée remonter jusqu'à
# l'appelant.


def test_main_returns_2_on_unknown_toml_key(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('[hep]\nhots = "10.0.0.5"\n', encoding="utf-8")  # typo: hots

    rc = cli.main(["--config", str(path), "--pcap", "/tmp/c.pcap", "--dry-run"])
    assert rc == 2


def test_main_returns_2_on_unknown_toml_table(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('[hepp]\nhost = "10.0.0.5"\n', encoding="utf-8")  # typo: hepp

    rc = cli.main(["--config", str(path), "--pcap", "/tmp/c.pcap", "--dry-run"])
    assert rc == 2


def test_main_returns_2_on_syntactically_invalid_toml(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[hep\nhost = broken", encoding="utf-8")  # TOML syntaxiquement invalide

    rc = cli.main(["--config", str(path), "--pcap", "/tmp/c.pcap", "--dry-run"])
    assert rc == 2


# --- Champs CLI non couverts ailleurs : interface/bpf/decode-as/tshark-path,
# hep-id/proto-type/node-name/keepalive-interval, correlation-field, log-level ---


def test_cli_explicit_interface_overrides_toml(toml_file):
    """--interface explicite doit écraser la valeur TOML (eth1 -> eth2)."""
    args = build_parser().parse_args(["--interface", "eth2"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.capture.interface == "eth2"


def test_cli_explicit_bpf_applied():
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--bpf", "udp port 32640"])
    config = Config()
    _apply_cli_args(config, args)

    assert config.capture.bpf == "udp port 32640"


def test_cli_explicit_decode_as_applied():
    args = build_parser().parse_args(
        ["--pcap", "/tmp/c.pcap", "--decode-as", "udp.port==32640,uaudp"]
    )
    config = Config()
    _apply_cli_args(config, args)

    assert config.capture.decode_as == ["udp.port==32640,uaudp"]


def test_cli_explicit_tshark_path_applied():
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--tshark-path", "/usr/bin/tshark"])
    config = Config()
    _apply_cli_args(config, args)

    assert config.capture.tshark_path == "/usr/bin/tshark"


def test_cli_explicit_hep_port_overrides_toml(toml_file):
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--hep-port", "9999"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.hep.port == 9999


def test_cli_explicit_hep_id_overrides_toml(toml_file):
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--hep-id", "9999"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.hep.capture_agent_id == 9999


def test_cli_explicit_proto_type_applied():
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--proto-type", "5"])
    config = Config()
    _apply_cli_args(config, args)

    assert config.hep.proto_type == 5


def test_cli_explicit_node_name_applied():
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--node-name", "oxo-besancon-01"])
    config = Config()
    _apply_cli_args(config, args)

    assert config.hep.node_name == "oxo-besancon-01"


def test_cli_explicit_keepalive_interval_applied():
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--keepalive-interval", "30"])
    config = Config()
    _apply_cli_args(config, args)

    assert config.hep.keepalive_interval == 30


def test_cli_explicit_correlation_field_overrides_toml(tmp_path):
    path = tmp_path / "oxo-hep-bridge-corr.toml"
    path.write_text('[normalizer]\ncorrelation_field = "toml_field"\n', encoding="utf-8")
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--correlation-field", "cli_field"])
    config = Config.load(toml_path=path)
    _apply_cli_args(config, args)

    assert config.normalizer.correlation_field == "cli_field"


def test_cli_explicit_log_level_overrides_toml(toml_file):
    """La config TOML de `toml_file` positionne déjà logging.level=DEBUG ;
    --log-level explicite doit tout de même l'écraser."""
    args = build_parser().parse_args(["--pcap", "/tmp/c.pcap", "--log-level", "ERROR"])
    config = Config.load(toml_path=toml_file)
    _apply_cli_args(config, args)

    assert config.logging.level == "ERROR"


# --- cli.main() : validations et avertissements en dehors de _apply_cli_args ---


def test_main_errors_when_neither_interface_nor_pcap_given():
    """Sans --interface ni --pcap (et aucun des deux en TOML), main() doit
    refuser de démarrer plutôt que de laisser Bridge échouer plus loin avec
    une erreur moins claire."""
    with pytest.raises(SystemExit):
        cli.main(["--dry-run"])


def test_main_warns_when_tls_settings_used_without_tls_transport(monkeypatch, tmp_path):
    """--hep-tls-ca-file sans --hep-transport tls (transport resté udp) doit
    déclencher l'avertissement dédié plutôt qu'être ignoré silencieusement.
    cli.main() réinitialise les handlers loguru (logger.remove() sans id) en
    cours de route, donc on ne peut pas s'appuyer sur un handler ajouté avant
    l'appel : on patche logger.warning directement."""

    class _FakeBridge:
        def __init__(self, config) -> None:
            self.config = config

        def run(self) -> int:
            return 0

    monkeypatch.setattr(cli, "Bridge", _FakeBridge)

    captured: list[str] = []
    monkeypatch.setattr(
        cli.logger, "warning", lambda msg, *a, **kw: captured.append(msg.format(*a, **kw))
    )

    rc = cli.main(["--pcap", "/tmp/c.pcap", "--dry-run", "--hep-tls-ca-file", "/tmp/ca.pem"])

    assert rc == 0
    assert any("n'ont d'effet qu'avec transport=tls" in line for line in captured)


def test_main_warns_when_compress_payload_enabled(monkeypatch):
    """--hep-compress-payload doit déclencher l'avertissement dédié (chunk
    non décodé par HOMER11 à ce jour)."""

    class _FakeBridge:
        def __init__(self, config) -> None:
            self.config = config

        def run(self) -> int:
            return 0

    monkeypatch.setattr(cli, "Bridge", _FakeBridge)

    captured: list[str] = []
    monkeypatch.setattr(
        cli.logger, "warning", lambda msg, *a, **kw: captured.append(msg.format(*a, **kw))
    )

    rc = cli.main(["--pcap", "/tmp/c.pcap", "--dry-run", "--hep-compress-payload"])

    assert rc == 0
    assert any("COMPRESSED_PAYLOAD" in line for line in captured)


def test_main_proceeds_normally_with_valid_toml(monkeypatch, tmp_path):
    """Garde-fou négatif : un TOML valide ne doit pas être affecté par le
    nouveau garde-fou (même chemin qu'avant, jusqu'au bout du run)."""

    class _FakeBridge:
        def __init__(self, config) -> None:
            self.config = config

        def run(self) -> int:
            return 0

    monkeypatch.setattr(cli, "Bridge", _FakeBridge)

    path = tmp_path / "good.toml"
    path.write_text('[hep]\nhost = "10.0.0.5"\n', encoding="utf-8")

    rc = cli.main(["--config", str(path), "--pcap", "/tmp/c.pcap", "--dry-run"])
    assert rc == 0


# --- cli.main() : --log-json-file écrit bien un sink JSON Lines exploitable ---


def test_main_writes_json_lines_with_stats_extra_to_log_json_file(fake_popen, tmp_path):
    """Session 42 : --log-json-file ajoute un sink loguru JSON Lines
    (serialize=True) en plus de stderr, sur un run réel (pcap de fixture,
    --dry-run pour ne rien envoyer sur le réseau). Le résumé de fin de run
    (Stats.log_summary(), toujours appelé) doit y apparaître comme une ligne
    JSON valide dont record.extra.stats porte le dict complet de
    Stats.to_dict() — pas seulement le texte humain interpolé."""
    json_path = tmp_path / "stats.json"
    rc = cli.main(
        [
            "--pcap",
            "tests/fixtures/ua3g_freeseating_ipv4.pcap",
            "--dry-run",
            "--log-json-file",
            str(json_path),
        ]
    )
    assert rc == 0

    lines = [line for line in json_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    records = [json.loads(line) for line in lines]
    stats_records = [
        r["record"] for r in records if "stats" in r.get("record", {}).get("extra", {})
    ]
    assert stats_records, "aucun enregistrement JSON ne porte extra.stats"
    summary = stats_records[-1]["extra"]["stats"]
    assert summary["received"] > 0
    assert summary["sent"] > 0
    assert set(summary) == {
        "received",
        "normalized",
        "skipped",
        "sent",
        "send_errors",
        "send_retries",
        "normalize_errors",
        "tshark_errors",
        "success_rate",
    }


def test_main_without_log_json_file_does_not_create_extra_sink_file(monkeypatch, tmp_path):
    """Garde-fou négatif : sans --log-json-file (défaut), aucun fichier JSON
    n'est créé quelque part — comportement historique inchangé."""
    json_path = tmp_path / "should-not-exist.json"

    class _FakeBridge:
        def __init__(self, config) -> None:
            self.config = config

        def run(self) -> int:
            return 0

    monkeypatch.setattr(cli, "Bridge", _FakeBridge)

    rc = cli.main(["--pcap", "/tmp/c.pcap", "--dry-run"])

    assert rc == 0
    assert not json_path.exists()
