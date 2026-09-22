#!/usr/bin/env python3
"""Tests de cohérence documentaire minimale.

Pas des tests fonctionnels du pont, mais un garde-fou pour éviter qu'un
document de référence ajouté au dépôt (ex: mapping métier NOE/UA3G ↔ HOMER)
se retrouve orphelin — non lié depuis le README/architecture — ou que le
commentaire de code qui le référence se désynchronise silencieusement d'un
renommage de fichier.
"""

from __future__ import annotations

import re
from pathlib import Path

from oxo_hep_bridge.cli import build_parser
from oxo_hep_bridge.config import (
    _CAPTURE_KEYS,
    _HEP_KEYS,
    _LOGGING_KEYS,
    _NORMALIZER_KEYS,
    Config,
)

REPO_ROOT = Path(__file__).parent.parent


def test_noe_ua3g_homer_mapping_doc_exists():
    doc = REPO_ROOT / "docs" / "noe-ua3g-homer-mapping.md"
    assert doc.exists(), "docs/noe-ua3g-homer-mapping.md est référencé ailleurs mais absent"
    content = doc.read_text(encoding="utf-8")
    # sections attendues de la synthèse
    assert "## 6. Bilan" in content
    assert "## 7. Lien avec `oxo-hep-bridge`" in content


def test_noe_ua3g_homer_mapping_doc_linked_from_readme():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "noe-ua3g-homer-mapping.md" in readme


def test_noe_ua3g_homer_mapping_doc_linked_from_architecture():
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "noe-ua3g-homer-mapping.md" in architecture


def test_semantics_module_references_mapping_doc():
    semantics = (REPO_ROOT / "src" / "oxo_hep_bridge" / "semantics.py").read_text(encoding="utf-8")
    assert "noe-ua3g-homer-mapping.md" in semantics


def test_ua3g_call_signaling_doc_exists():
    """Session 29 : `docs/ua3g-call-signaling-decroche-numerotation.md`
    (ajouté en session, daté 2026-08-29 dans son en-tête) n'était référencé
    nulle part hors d'une ligne de CHANGELOG.md, ni lié depuis le
    README/architecture.md ni listé dans `CLAUDE.md` — même défaut orphelin
    que celui déjà gardé pour `noe-ua3g-homer-mapping.md` ci-dessus (voir le
    piège correspondant dans CLAUDE.md : « un fichier de référence ajouté au
    dépôt doit être lié depuis le README/architecture.md, pas laissé
    orphelin »)."""
    doc = REPO_ROOT / "docs" / "ua3g-call-signaling-decroche-numerotation.md"
    assert doc.exists(), (
        "docs/ua3g-call-signaling-decroche-numerotation.md est référencé ailleurs mais absent"
    )
    content = doc.read_text(encoding="utf-8")
    assert "## 5. Commande à utiliser sur une vraie capture d'appel" in content


def test_ua3g_call_signaling_doc_linked_from_readme():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "ua3g-call-signaling-decroche-numerotation.md" in readme


def test_ua3g_call_signaling_doc_linked_from_architecture():
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "ua3g-call-signaling-decroche-numerotation.md" in architecture


def test_architecture_doc_documents_known_limitations():
    """Le constat empirique du §6ter du document de mapping (perte de
    contenu NOE sur les trames opcode UAUDP >= 16) ne doit pas rester
    enterré dans un document exploratoire : il doit remonter dans
    architecture.md, l'endroit où un opérateur cherche les limites du pont."""
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "## Limites connues" in architecture
    assert "opcode UAUDP 16-23" in architecture
    assert "noe-ua3g-homer-mapping.md#6ter" in architecture


def test_readme_links_known_limitations_section():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "architecture.md#limites-connues" in readme


def test_all_cli_options_documented_in_readme():
    """Session 20 : `--tshark-path` et `--correlation-field` existaient dans
    `cli.py` (et pour ce dernier, cité une seule fois dans architecture.md)
    sans jamais figurer dans le tableau d'options du README — trouvé en
    comparant `build_parser()` au tableau plutôt qu'en relisant le README
    seul. Garde-fou pour empêcher qu'une future option CLI reste
    non documentée dans le même tableau.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    parser = build_parser()
    # Seule l'option canonique (premier alias déclaré) de chaque argument est
    # exigée dans le tableau ; les alias secondaires (ex: --hep-auth-key pour
    # --hep-pass) et --help sont volontairement omis du README.
    canonical_options = {
        action.option_strings[0]
        for action in parser._actions
        if action.option_strings and action.option_strings[0].startswith("--")
    }
    missing = sorted(opt for opt in canonical_options if f"`{opt}`" not in readme)
    assert not missing, f"options CLI absentes du tableau README.md : {missing}"


def test_all_env_vars_documented_in_readme():
    """Session 26 : les 22 variables d'environnement `OXOHEP_*` appliquées par
    `config.apply_env()` sont réellement fonctionnelles (2e niveau de la
    priorité CLI > env > TOML > défaut, documentée dans le docstring de
    `config.py` et le commentaire d'en-tête de
    `config/oxo-hep-bridge.example.toml`) mais n'apparaissaient nulle part
    dans le tableau d'options du README — seules 4 d'entre elles étaient
    mentionnées, éparpillées dans `architecture.md`/`hep-chunks.md`. Trouvé
    en comparant les `env.get("OXOHEP_...")` réels de `apply_env()` au
    contenu du README, plutôt qu'en relisant ce dernier seul — même méthode
    que `test_all_cli_options_documented_in_readme` et
    `test_all_config_keys_documented_in_example_toml`. Garde-fou pour
    empêcher qu'une future variable d'environnement reste non documentée
    dans ce tableau.
    """
    config_source = (REPO_ROOT / "src" / "oxo_hep_bridge" / "config.py").read_text(encoding="utf-8")
    apply_env_body = config_source.split("def apply_env(")[1]
    env_vars = set(re.findall(r'env\.get\("(OXOHEP_[A-Z_]+)"\)', apply_env_body))
    assert env_vars, "aucune variable OXOHEP_* trouvée dans apply_env() — regex désynchronisée ?"
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    missing = sorted(var for var in env_vars if f"`{var}`" not in readme)
    assert not missing, f"variables d'environnement absentes du tableau README.md : {missing}"


def test_example_toml_is_loadable_config():
    """Le TOML d'exemple documente toutes les clés supportées, entièrement
    commentées par défaut. S'il devient syntaxiquement invalide (faute de
    frappe TOML lors d'un ajout de clé documentée), Config.load() lève une
    exception ici plutôt que de le découvrir en production."""
    example = REPO_ROOT / "config" / "oxo-hep-bridge.example.toml"
    assert example.exists()
    config = Config.load(toml_path=example)
    # Entièrement commenté : les valeurs par défaut du code doivent rester
    # actives (le fichier documente, mais n'active rien tout seul).
    assert config.hep.send_retries == 0
    assert config.hep.compress_payload is False


def test_all_config_keys_documented_in_example_toml():
    """Session 25 : `tshark_path` existait dans `_CAPTURE_KEYS` (donc une clé
    TOML valide et fonctionnelle, câblée jusqu'à `TsharkEKSource` — voir
    aussi `--tshark-path` côté CLI et `OXOHEP_TSHARK_PATH` côté env, ces deux
    derniers déjà documentés) sans jamais figurer dans
    `config/oxo-hep-bridge.example.toml`, le fichier censé documenter
    « toutes les clés supportées, entièrement commentées par défaut » (voir
    `test_example_toml_is_loadable_config` ci-dessus). Trouvé en comparant
    les frozensets `_XXX_KEYS` de `config.py` (la référence déjà utilisée par
    `Config` elle-même pour valider un TOML fourni par l'utilisateur) au
    contenu du TOML d'exemple, plutôt qu'en relisant ce dernier seul — même
    méthode que `test_all_cli_options_documented_in_readme` pour le README.
    Garde-fou pour empêcher qu'une future clé de config (CLI/TOML/env)
    reste non documentée dans ce fichier.
    """
    example_text = (REPO_ROOT / "config" / "oxo-hep-bridge.example.toml").read_text(
        encoding="utf-8"
    )
    all_keys = _CAPTURE_KEYS | _HEP_KEYS | _NORMALIZER_KEYS | _LOGGING_KEYS
    missing = sorted(key for key in all_keys if key not in example_text)
    assert not missing, f"clés de config absentes de config/oxo-hep-bridge.example.toml : {missing}"
