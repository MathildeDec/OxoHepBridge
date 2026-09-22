#!/usr/bin/env python3
"""Tests de la configuration (config.py) : priorité CLI > env > TOML > défauts,
chargement du fichier TOML, non-écrasement par des variables absentes."""

from __future__ import annotations

from pathlib import Path

import pytest

from oxo_hep_bridge.config import Config, ConfigError, apply_env, apply_toml


@pytest.fixture
def toml_file(tmp_path: Path) -> Path:
    content = """
[capture]
interface = "eth1"
bpf = "udp port 9999"

[hep]
host = "10.0.0.5"
port = 9061
capture_agent_id = 3003
auth_key = "toml-secret"
transport = "tcp"
tls_verify = false
tls_ca_file = "/etc/pki/homer-ca.pem"

[normalizer]
correlation_field = "custom_field"

[logging]
level = "DEBUG"
"""
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_apply_toml_loads_all_sections(toml_file):
    config = Config()
    apply_toml(config, toml_file)

    assert config.capture.interface == "eth1"
    assert config.capture.bpf == "udp port 9999"
    assert config.hep.host == "10.0.0.5"
    assert config.hep.port == 9061
    assert config.hep.capture_agent_id == 3003
    assert config.hep.auth_key == "toml-secret"
    assert config.hep.transport == "tcp"
    assert config.hep.tls_verify is False
    assert config.hep.tls_ca_file == "/etc/pki/homer-ca.pem"
    assert config.normalizer.correlation_field == "custom_field"
    assert config.logging.level == "DEBUG"


def test_apply_toml_missing_file_is_silently_ignored(tmp_path):
    config = Config()
    apply_toml(config, tmp_path / "does-not-exist.toml")
    # config reste aux valeurs par défaut
    assert config.hep.host == "127.0.0.1"


def test_apply_env_overrides_toml_values(monkeypatch, toml_file):
    config = Config()
    apply_toml(config, toml_file)
    assert config.hep.host == "10.0.0.5"  # depuis le TOML

    monkeypatch.setenv("OXOHEP_HEP_HOST", "192.168.1.99")
    apply_env(config)
    assert config.hep.host == "192.168.1.99"  # env écrase TOML


def test_apply_env_does_not_override_when_var_absent(monkeypatch, toml_file):
    """Une variable d'environnement absente ne doit PAS écraser une valeur
    déjà positionnée par le TOML (ni par un défaut)."""
    config = Config()
    apply_toml(config, toml_file)

    monkeypatch.delenv("OXOHEP_HEP_PORT", raising=False)
    apply_env(config)
    # la valeur TOML doit être préservée puisque OXOHEP_HEP_PORT n'est pas définie
    assert config.hep.port == 9061


def test_config_load_applies_toml_then_env(monkeypatch, toml_file):
    monkeypatch.setenv("OXOHEP_HEP_PORT", "9999")
    config = Config.load(toml_path=toml_file)

    assert config.capture.interface == "eth1"  # depuis TOML, non touché par env
    assert config.hep.port == 9999  # env écrase TOML
    assert config.hep.host == "10.0.0.5"  # TOML, pas d'env défini pour ce champ


def test_config_defaults_when_no_toml_no_env():
    config = Config.load(toml_path=None)
    assert config.hep.host == "127.0.0.1"
    assert config.hep.port == 9060
    assert config.hep.capture_agent_id == 2001


def test_apply_env_dry_run_boolean_parsing(monkeypatch):
    config = Config()
    monkeypatch.setenv("OXOHEP_DRY_RUN", "true")
    apply_env(config)
    assert config.dry_run is True

    config2 = Config()
    monkeypatch.setenv("OXOHEP_DRY_RUN", "0")
    apply_env(config2)
    assert config2.dry_run is False


def test_apply_env_overrides_transport_and_tls_options(monkeypatch, toml_file):
    """TOML pose transport=tcp/tls_verify=false/tls_ca_file=..., l'environnement
    doit pouvoir écraser chacun des trois indépendamment (y compris repasser
    tls_verify à True, contrairement au flag CLI --hep-tls-insecure qui est à
    sens unique)."""
    config = Config()
    apply_toml(config, toml_file)
    assert config.hep.transport == "tcp"
    assert config.hep.tls_verify is False

    monkeypatch.setenv("OXOHEP_HEP_TRANSPORT", "tls")
    monkeypatch.setenv("OXOHEP_HEP_TLS_VERIFY", "true")
    monkeypatch.setenv("OXOHEP_HEP_TLS_CA_FILE", "/run/secrets/homer-ca.pem")
    apply_env(config)

    assert config.hep.transport == "tls"
    assert config.hep.tls_verify is True
    assert config.hep.tls_ca_file == "/run/secrets/homer-ca.pem"


def test_apply_env_tls_verify_boolean_parsing(monkeypatch):
    config = Config()
    monkeypatch.setenv("OXOHEP_HEP_TLS_VERIFY", "false")
    apply_env(config)
    assert config.hep.tls_verify is False

    config2 = Config()
    monkeypatch.setenv("OXOHEP_HEP_TLS_VERIFY", "1")
    apply_env(config2)
    assert config2.hep.tls_verify is True


def test_apply_env_does_not_override_transport_when_var_absent(monkeypatch, toml_file):
    config = Config()
    apply_toml(config, toml_file)

    monkeypatch.delenv("OXOHEP_HEP_TRANSPORT", raising=False)
    apply_env(config)
    assert config.hep.transport == "tcp"  # valeur TOML préservée


def test_config_defaults_transport_to_udp_with_verification():
    config = Config.load(toml_path=None)
    assert config.hep.transport == "udp"
    assert config.hep.tls_verify is True
    assert config.hep.tls_ca_file is None


def test_apply_toml_loads_compress_payload(tmp_path):
    content = "[hep]\ncompress_payload = true\n"
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text(content, encoding="utf-8")

    config = Config()
    apply_toml(config, path)
    assert config.hep.compress_payload is True


def test_apply_env_overrides_compress_payload(monkeypatch):
    config = Config()
    assert config.hep.compress_payload is False

    monkeypatch.setenv("OXOHEP_HEP_COMPRESS_PAYLOAD", "true")
    apply_env(config)
    assert config.hep.compress_payload is True

    monkeypatch.setenv("OXOHEP_HEP_COMPRESS_PAYLOAD", "false")
    apply_env(config)
    assert config.hep.compress_payload is False


def test_apply_env_does_not_override_compress_payload_when_var_absent(monkeypatch, tmp_path):
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text("[hep]\ncompress_payload = true\n", encoding="utf-8")

    config = Config()
    apply_toml(config, path)

    monkeypatch.delenv("OXOHEP_HEP_COMPRESS_PAYLOAD", raising=False)
    apply_env(config)
    assert config.hep.compress_payload is True  # valeur TOML préservée


def test_config_defaults_compress_payload_to_false():
    config = Config.load(toml_path=None)
    assert config.hep.compress_payload is False


# --- Retry/backoff sur échec d'envoi (hep.send_retries/hep.send_retry_backoff) --


def test_apply_toml_loads_send_retries(tmp_path):
    content = "[hep]\nsend_retries = 3\nsend_retry_backoff = 1.5\n"
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text(content, encoding="utf-8")

    config = Config()
    apply_toml(config, path)
    assert config.hep.send_retries == 3
    assert config.hep.send_retry_backoff == 1.5


def test_apply_env_overrides_send_retries(monkeypatch):
    config = Config()
    monkeypatch.setenv("OXOHEP_HEP_SEND_RETRIES", "5")
    monkeypatch.setenv("OXOHEP_HEP_SEND_RETRY_BACKOFF", "2.0")
    apply_env(config)
    assert config.hep.send_retries == 5
    assert config.hep.send_retry_backoff == 2.0


def test_apply_env_does_not_override_send_retries_when_var_absent(monkeypatch, tmp_path):
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text("[hep]\nsend_retries = 3\n", encoding="utf-8")

    config = Config()
    apply_toml(config, path)

    monkeypatch.delenv("OXOHEP_HEP_SEND_RETRIES", raising=False)
    apply_env(config)
    assert config.hep.send_retries == 3  # valeur TOML préservée


def test_config_defaults_send_retries_to_zero():
    config = Config.load(toml_path=None)
    assert config.hep.send_retries == 0
    assert config.hep.send_retry_backoff == 0.5


# --- Fréquence du log de progression (logging.stats_interval) ---


def test_apply_toml_loads_stats_interval(tmp_path):
    content = "[logging]\nstats_interval = 50\n"
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text(content, encoding="utf-8")

    config = Config()
    apply_toml(config, path)
    assert config.logging.stats_interval == 50


def test_apply_env_overrides_stats_interval(monkeypatch):
    config = Config()
    monkeypatch.setenv("OXOHEP_STATS_INTERVAL", "25")
    apply_env(config)
    assert config.logging.stats_interval == 25


def test_apply_env_does_not_override_stats_interval_when_var_absent(monkeypatch, tmp_path):
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text("[logging]\nstats_interval = 50\n", encoding="utf-8")

    config = Config()
    apply_toml(config, path)

    monkeypatch.delenv("OXOHEP_STATS_INTERVAL", raising=False)
    apply_env(config)
    assert config.logging.stats_interval == 50  # valeur TOML préservée


def test_config_defaults_stats_interval_to_500():
    config = Config.load(toml_path=None)
    assert config.logging.stats_interval == 500


# --- Sortie JSON structurée (logging.json_file) -----------------------------


def test_apply_toml_loads_json_file(tmp_path):
    content = '[logging]\njson_file = "/var/log/oxo-hep-bridge/stats.json"\n'
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text(content, encoding="utf-8")

    config = Config()
    apply_toml(config, path)
    assert config.logging.json_file == "/var/log/oxo-hep-bridge/stats.json"


def test_apply_env_overrides_json_file(monkeypatch):
    config = Config()
    monkeypatch.setenv("OXOHEP_LOG_JSON_FILE", "/tmp/stats.json")
    apply_env(config)
    assert config.logging.json_file == "/tmp/stats.json"


def test_apply_env_does_not_override_json_file_when_var_absent(monkeypatch, tmp_path):
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text('[logging]\njson_file = "/var/log/stats.json"\n', encoding="utf-8")

    config = Config()
    apply_toml(config, path)

    monkeypatch.delenv("OXOHEP_LOG_JSON_FILE", raising=False)
    apply_env(config)
    assert config.logging.json_file == "/var/log/stats.json"  # valeur TOML préservée


def test_config_defaults_json_file_to_none():
    config = Config.load(toml_path=None)
    assert config.logging.json_file is None


# --- Validation du TOML : table/clé inconnue (typo) -------------------------
#
# apply_toml() ignorait jusqu'ici silencieusement toute table ou clé absente
# de la liste attendue (boucles `if "..." in table` dans _apply_toml_capture()/
# _apply_toml_hep()/apply_toml()) : une faute de frappe dans
# config/oxo-hep-bridge.toml laissait le run démarrer avec les valeurs par
# défaut du champ visé, sans aucun avertissement. Ces tests couvrent les deux
# cas fautifs (clé inconnue sous une table connue, table/clé de premier
# niveau inconnue) sur les quatre tables (capture/hep/normalizer/logging),
# plus les cas où le TOML reste valide (rien ne doit régresser).


def test_apply_toml_unknown_key_under_hep_raises(tmp_path):
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text('[hep]\nhots = "10.0.0.5"\n', encoding="utf-8")  # typo: hots

    config = Config()
    with pytest.raises(ConfigError, match="hots"):
        apply_toml(config, path)


def test_apply_toml_unknown_key_under_capture_raises(tmp_path):
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text('[capture]\ninterfce = "eth0"\n', encoding="utf-8")  # typo: interfce

    config = Config()
    with pytest.raises(ConfigError, match="interfce"):
        apply_toml(config, path)


def test_apply_toml_unknown_key_under_normalizer_raises(tmp_path):
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text('[normalizer]\ncorrelationfield = "x"\n', encoding="utf-8")

    config = Config()
    with pytest.raises(ConfigError, match="correlationfield"):
        apply_toml(config, path)


def test_apply_toml_unknown_key_under_logging_raises(tmp_path):
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text('[logging]\nlvl = "DEBUG"\n', encoding="utf-8")

    config = Config()
    with pytest.raises(ConfigError, match="lvl"):
        apply_toml(config, path)


def test_apply_toml_unknown_top_level_table_raises(tmp_path):
    """Typo dans le nom de la section elle-même (ex: [hepp] au lieu de [hep])."""
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text('[hepp]\nhost = "10.0.0.5"\n', encoding="utf-8")

    config = Config()
    with pytest.raises(ConfigError, match="hepp"):
        apply_toml(config, path)


def test_apply_toml_key_misplaced_outside_any_section_raises(tmp_path):
    """Clé écrite au premier niveau, sans en-tête [table] (oubli fréquent)."""
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text('host = "10.0.0.5"\nport = 9060\n', encoding="utf-8")

    config = Config()
    with pytest.raises(ConfigError, match="host"):
        apply_toml(config, path)


def test_apply_toml_table_written_as_scalar_raises(tmp_path):
    """`hep = "..."` au lieu de `[hep]` : la table existe mais n'est pas un dict."""
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text('hep = "10.0.0.5"\n', encoding="utf-8")

    config = Config()
    with pytest.raises(ConfigError, match="table TOML"):
        apply_toml(config, path)


def test_apply_toml_valid_multi_table_file_does_not_raise(tmp_path):
    """Garde-fou négatif : un TOML valide sur toutes les tables ne doit
    jamais déclencher la validation, même avec les quatre sections remplies."""
    content = (
        '[capture]\ninterface = "eth0"\nbpf = "udp port 32640"\n'
        '[hep]\nhost = "10.0.0.5"\nport = 9061\ntransport = "tcp"\n'
        '[normalizer]\ncorrelation_field = "custom"\n'
        '[logging]\nlevel = "DEBUG"\nstats_interval = 10\n'
    )
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text(content, encoding="utf-8")

    config = Config()
    apply_toml(config, path)  # ne doit pas lever
    assert config.hep.host == "10.0.0.5"
    assert config.logging.stats_interval == 10


def test_apply_toml_empty_file_does_not_raise(tmp_path):
    """Un fichier TOML présent mais vide reste un cas valide (aucune section)."""
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text("", encoding="utf-8")

    config = Config()
    apply_toml(config, path)  # ne doit pas lever
    assert config.hep.host == "127.0.0.1"  # valeurs par défaut inchangées


# --- Champs TOML/env non couverts ailleurs : pcap, decode_as, tshark_path,
# proto_type, node_name, keepalive_interval, capture_agent_id (env), et
# Config.from_env() -----------------------------------------------------


def test_apply_toml_loads_capture_pcap_decode_as_tshark_path(tmp_path):
    content = (
        "[capture]\n"
        'pcap = "/data/capture.pcap"\n'
        'decode_as = ["udp.port==32640,uaudp"]\n'
        'tshark_path = "/opt/wireshark/bin/tshark"\n'
    )
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text(content, encoding="utf-8")

    config = Config()
    apply_toml(config, path)

    assert config.capture.pcap == "/data/capture.pcap"
    assert config.capture.decode_as == ["udp.port==32640,uaudp"]
    assert config.capture.tshark_path == "/opt/wireshark/bin/tshark"


def test_apply_toml_loads_proto_type_node_name_keepalive_interval(tmp_path):
    content = '[hep]\nproto_type = 5\nnode_name = "oxo-besancon-01"\nkeepalive_interval = 60\n'
    path = tmp_path / "oxo-hep-bridge.toml"
    path.write_text(content, encoding="utf-8")

    config = Config()
    apply_toml(config, path)

    assert config.hep.proto_type == 5
    assert config.hep.node_name == "oxo-besancon-01"
    assert config.hep.keepalive_interval == 60


def test_apply_env_overrides_capture_fields(monkeypatch):
    """OXOHEP_DECODE_AS scinde sur ';' (pas ',') pour préserver la virgule
    interne à chaque règle --decode-as (syntaxe tshark champ==valeur,proto) ;
    plusieurs règles se séparent par ';'."""
    config = Config()
    monkeypatch.setenv("OXOHEP_INTERFACE", "eth3")
    monkeypatch.setenv("OXOHEP_PCAP", "/data/capture.pcap")
    monkeypatch.setenv("OXOHEP_BPF", "udp port 32640")
    monkeypatch.setenv("OXOHEP_DECODE_AS", "udp.port==32640,uaudp")
    monkeypatch.setenv("OXOHEP_TSHARK_PATH", "/opt/wireshark/bin/tshark")
    apply_env(config)

    assert config.capture.interface == "eth3"
    assert config.capture.pcap == "/data/capture.pcap"
    assert config.capture.bpf == "udp port 32640"
    assert config.capture.decode_as == ["udp.port==32640,uaudp"]
    assert config.capture.tshark_path == "/opt/wireshark/bin/tshark"


def test_apply_env_decode_as_supports_multiple_rules_separated_by_semicolon(monkeypatch):
    config = Config()
    monkeypatch.setenv("OXOHEP_DECODE_AS", "udp.port==32640,uaudp;udp.port==32641,uaudp")
    apply_env(config)

    assert config.capture.decode_as == [
        "udp.port==32640,uaudp",
        "udp.port==32641,uaudp",
    ]


def test_apply_env_overrides_hep_id_proto_type_pass_node_name_keepalive(monkeypatch):
    config = Config()
    monkeypatch.setenv("OXOHEP_HEP_ID", "4242")
    monkeypatch.setenv("OXOHEP_PROTO_TYPE", "5")
    monkeypatch.setenv("OXOHEP_HEP_PASS", "env-secret")
    monkeypatch.setenv("OXOHEP_NODE_NAME", "oxo-besancon-02")
    monkeypatch.setenv("OXOHEP_KEEPALIVE_INTERVAL", "45")
    apply_env(config)

    assert config.hep.capture_agent_id == 4242
    assert config.hep.proto_type == 5
    assert config.hep.auth_key == "env-secret"
    assert config.hep.node_name == "oxo-besancon-02"
    assert config.hep.keepalive_interval == 45


def test_apply_env_overrides_correlation_field_and_log_level(monkeypatch):
    config = Config()
    monkeypatch.setenv("OXOHEP_CORRELATION_FIELD", "ua_call_id")
    monkeypatch.setenv("OXOHEP_LOG_LEVEL", "ERROR")
    apply_env(config)

    assert config.normalizer.correlation_field == "ua_call_id"
    assert config.logging.level == "ERROR"


def test_config_from_env_equivalent_to_load_without_toml(monkeypatch):
    """Config.from_env() est conservée pour compatibilité : doit se comporter
    exactement comme Config.load(toml_path=None) (env appliqué, pas de TOML)."""
    monkeypatch.setenv("OXOHEP_HEP_HOST", "10.9.9.9")
    config = Config.from_env()

    assert config.hep.host == "10.9.9.9"
    assert config.capture.pcap is None
