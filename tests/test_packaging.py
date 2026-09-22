#!/usr/bin/env python3
"""Garde-fou sur l'archive de livraison (`tools/package.py`, `make package`).

`.github/workflows/ci.yml` a disparu à plusieurs reprises d'archives de
livraison passées (sessions 17, 27, puis 35 — voir docs/pitfalls.md) à
cause d'un motif d'exclusion « zip -x '*.git*' » tapé à la main qui matche
aussi ``.github/`` par sous-chaîne. Ce module construit une vraie archive
via ``tools.package.build_archive`` et inspecte son contenu réel, plutôt
que de relire le code d'exclusion à l'œil ou de faire confiance à la
documentation — même esprit que ``test_ci_config.py``/``test_docs.py``.
"""

from __future__ import annotations

import zipfile

from tools.package import build_archive


def _archive_names(tmp_path, name: str = "delivery-test.zip") -> list[str]:
    output = build_archive(tmp_path / name)
    with zipfile.ZipFile(output) as archive:
        return archive.namelist()


def test_build_archive_includes_github_workflows(tmp_path):
    """Régression directe des sessions 17/27/35 : le workflow CI doit être
    présent dans l'archive produite."""
    names = _archive_names(tmp_path)
    assert ".github/workflows/ci.yml" in names


def test_build_archive_includes_tracking_and_doc_files(tmp_path):
    """Les fichiers de suivi (roadmap/CLAUDE.md/CHANGELOG/pitfalls) et le
    code source ne doivent pas non plus être perdus — l'archive doit
    rester une copie complète du dépôt, pas seulement le workflow CI."""
    names = _archive_names(tmp_path)
    for expected in (
        "CLAUDE.md",
        "CHANGELOG.md",
        "docs/roadmap.md",
        "docs/pitfalls.md",
        "src/oxo_hep_bridge/ua_opcode_names.py",
        "tests/test_packaging.py",
        "pyproject.toml",
        "uv.lock",
    ):
        assert expected in names


def test_build_archive_excludes_dev_caches_and_bytecode(tmp_path):
    """Les répertoires de cache d'outillage et les .pyc n'ont rien à faire
    dans une archive de livraison — présents dans l'arbre de travail de ce
    sandbox au moment du test (pytest/ruff/mypy viennent de tourner)."""
    names = _archive_names(tmp_path)
    assert not any(".pytest_cache" in n for n in names)
    assert not any("__pycache__" in n for n in names)
    assert not any(n.endswith(".pyc") for n in names)


def test_build_archive_does_not_bundle_itself_when_output_under_source(tmp_path):
    """L'archive ne doit jamais s'inclure elle-même si le fichier de
    sortie se trouve sous ``source_root`` — y compris hors de tout
    dossier déjà exclu par nom (``dist/`` notamment), sans quoi
    l'exclusion ne tiendrait que par coïncidence de nommage plutôt que
    par une vraie protection contre l'auto-inclusion."""
    (tmp_path / "README.md").write_text("contenu de test", encoding="utf-8")
    output = tmp_path / "self-test.zip"
    build_archive(output, source_root=tmp_path)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
    assert "README.md" in names
    assert "self-test.zip" not in names
