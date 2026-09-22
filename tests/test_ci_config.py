#!/usr/bin/env python3
"""Tests de cohérence du outillage CI (mypy + seuil de couverture).

Pas des tests fonctionnels du pont : un garde-fou pour éviter qu'une future
modification de `.github/workflows/ci.yml` ou de `pyproject.toml` retire
silencieusement le contrôle de type statique ou le seuil de couverture
minimal (docs/roadmap.md, section « Durcissement CI ») sans que personne ne
s'en aperçoive avant la prochaine régression — ce garde-fou tourne en local
(`make test`) et pas seulement dans la CI qu'il vérifie.

Vérifications texte simple (pas de parsing YAML complet, pour ne pas ajouter
PyYAML comme dépendance de dev juste pour ce test) — même esprit que les
vérifications de `test_docs.py` sur le contenu Markdown.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def _ci_workflow_text() -> str:
    return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_ci_runs_mypy():
    """La CI doit exécuter mypy, en complément de ruff check/format —
    sans quoi une régression de typage passerait inaperçue jusqu'au
    prochain run manuel. Depuis la migration à uv (session 44), les
    commandes CI passent par `uv run <outil>` plutôt qu'un appel direct au
    binaire du venv — voir `test_ci_uses_uv_run_for_tool_invocations`
    ci-dessous pour le garde-fou correspondant."""
    workflow = _ci_workflow_text()
    assert "mypy" in workflow
    # doit être une étape distincte, pas juste une mention en commentaire
    assert "run: uv run mypy" in workflow


def test_ci_enforces_a_coverage_threshold():
    """La CI doit faire échouer le job si la couverture retombe sous un
    seuil minimal — pas seulement afficher le pourcentage."""
    workflow = _ci_workflow_text()
    assert "--cov-fail-under=" in workflow


def test_ci_and_makefile_use_the_same_coverage_threshold():
    """Le seuil de couverture de la CI (`ci.yml`) et celui de la commande de
    développement (`make test-cov`) ne doivent pas diverger silencieusement —
    sans quoi un dev verrait `make test-cov` passer localement puis la CI
    échouer (ou l'inverse) sur le même seuil supposé identique."""
    workflow = _ci_workflow_text()
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    def _extract_threshold(text: str) -> str:
        marker = "--cov-fail-under="
        start = text.index(marker) + len(marker)
        end = start
        while end < len(text) and (text[end].isdigit() or text[end] == "."):
            end += 1
        return text[start:end]

    assert _extract_threshold(workflow) == _extract_threshold(makefile)


def test_mypy_config_present_and_scoped_to_typed_code():
    """`[tool.mypy]` doit cibler le package installable + `tools/` (déjà
    entièrement annotés) — pas `tests/`, où des senders/faux objets de test
    assignés à un attribut typé sur la classe de base casseraient le typage
    sans bénéfice réel (voir docs/architecture.md)."""
    config = _pyproject()
    mypy_config = config.get("tool", {}).get("mypy")
    assert mypy_config is not None, "[tool.mypy] absent de pyproject.toml"
    files = mypy_config.get("files", [])
    assert "src/oxo_hep_bridge" in files
    assert "tools" in files
    assert not any("test" in f for f in files)


def test_mypy_config_disallows_untyped_defs():
    """Le contrôle de type ne doit pas se contenter de vérifier le code déjà
    annoté (mypy en mode permissif par défaut) : `disallow_untyped_defs`
    fait échouer le check si une nouvelle fonction est ajoutée sans
    annotations dans le périmètre couvert."""
    config = _pyproject()
    mypy_config = config["tool"]["mypy"]
    assert mypy_config.get("disallow_untyped_defs") is True


def test_dev_dependencies_include_mypy():
    """`mypy` doit être installable via `uv sync --extra dev` (ex-`pip
    install -e ".[dev]"` avant la migration à uv, session 44) — sans quoi
    `make dev`/`make typecheck` échoue avec un mypy introuvable."""
    config = _pyproject()
    dev_deps = config["project"]["optional-dependencies"]["dev"]
    assert any(dep.startswith("mypy") for dep in dev_deps)


def test_makefile_exposes_a_typecheck_target():
    """`make typecheck` doit exister, au même titre que `make lint`/`make
    test`, pour rester cohérent avec la façon dont le reste du projet
    expose ses vérifications (voir README.md, section Tests)."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "typecheck:" in makefile
    assert "MYPY" in makefile


def test_ci_uses_uv_run_for_tool_invocations():
    """Migration à uv (session 44) : la CI doit installer uv via l'action
    officielle `astral-sh/setup-uv`, synchroniser l'environnement avec
    `uv sync` (extra `dev`) et invoquer chaque outil via `uv run <outil>`
    plutôt qu'un appel direct au binaire — sans quoi les commandes CI
    dépendraient implicitement d'un venv déjà activé, contrairement à
    l'esprit de `uv run` (résolution automatique de l'environnement)."""
    workflow = _ci_workflow_text()
    assert "astral-sh/setup-uv" in workflow
    assert "uv sync" in workflow
    assert "uv run ruff check" in workflow
    assert "uv run ruff format --check" in workflow
    assert "uv run pytest" in workflow


def test_ci_syncs_dependencies_from_a_locked_lockfile():
    """`uv sync --locked` doit être utilisé en CI (pas juste `uv sync`) :
    sans `--locked`, un `uv.lock` désynchronisé de `pyproject.toml` serait
    silencieusement régénéré en CI au lieu de faire échouer le job — le
    même écart passerait alors inaperçu en local (`make dev` échouerait
    différemment) et en CI (mise à jour muette du lock)."""
    workflow = _ci_workflow_text()
    assert "uv sync --locked" in workflow


def test_makefile_uses_uv_for_all_tool_invocations():
    """Migration à uv (session 44) : plus d'appel direct à
    `.venv/bin/<outil>` dans le Makefile — RUFF/MYPY/PYTEST/PY doivent
    tous passer par `uv run`, et `dev`/`install` par `uv sync`/`uv run
    pre-commit install`. Garde-fou contre une régression qui
    réintroduirait un chemin de binaire codé en dur (fragile si le venv
    est recréé ailleurs que `.venv`)."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "UV ?= uv" in makefile
    assert "uv sync" in makefile
    for var in ("RUFF", "MYPY", "PYTEST", "PY"):
        line = next(
            (line for line in makefile.splitlines() if line.startswith(f"{var} ?=")),
            None,
        )
        assert line is not None, f"variable {var} absente du Makefile"
        assert "$(UV) run" in line, f"{var} ne passe pas par '$(UV) run' : {line!r}"


def test_uv_lock_file_present_and_matches_pyproject_project():
    """`uv.lock` doit être présent (figé, committé) et référencer le même
    nom/version de projet que `pyproject.toml` — sinon un lock périmé ou
    généré pour un autre projet passerait inaperçu jusqu'à un `uv sync
    --locked` en échec (voir `test_ci_syncs_dependencies_from_a_locked_
    lockfile`)."""
    lock_path = REPO_ROOT / "uv.lock"
    assert lock_path.exists(), "uv.lock absent — généré par `uv lock`/`make lock`"
    lock_text = lock_path.read_text(encoding="utf-8")
    config = _pyproject()
    project = config["project"]
    assert f'name = "{project["name"]}"' in lock_text
    assert f'version = "{project["version"]}"' in lock_text


def test_install_script_bootstraps_uv():
    """`install.sh` doit installer `uv` s'il est absent (installeur
    officiel astral.sh) puis synchroniser l'environnement avec `uv sync
    --extra dev` — remplace l'ancien `python3 -m venv` + `pip install -e
    ".[dev]"` (migration session 44)."""
    install_sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "uv sync --extra dev" in install_sh
    assert "astral.sh/uv/install.sh" in install_sh


def test_no_leftover_pip_venv_bootstrap_commands():
    """Garde-fou anti-régression pour la migration à uv (session 44) :
    aucun des trois points d'entrée outillage (Makefile, install.sh, CI)
    ne doit plus bootstrapper l'environnement via `pip install -e` ou
    `python3 -m venv` — `uv sync` remplace les deux partout. `pip`/`venv`
    peuvent en revanche apparaître ailleurs dans le dépôt (docstrings de
    sessions passées, commentaires historiques) : ce garde-fou cible
    uniquement les commandes de bootstrap dans les trois fichiers
    d'entrée, pas une interdiction globale du mot."""
    for relpath in ("Makefile", "install.sh", ".github/workflows/ci.yml"):
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        assert 'pip install -e ".[dev]"' not in text, relpath
        assert "python3 -m venv" not in text, relpath
        assert "poetry" not in text.lower(), relpath


def test_makefile_lint_target_also_checks_formatting():
    """`make lint` doit vérifier le formatage (`ruff format --check`), pas
    seulement le lint (`ruff check`) — comme documenté dans le README
    (section Tests : « make lint  # ruff check + format --check »). Sans ce
    garde-fou, un fichier mal formaté passerait `make lint` en local puis
    ferait échouer l'étape équivalente de la CI (`ci.yml`)."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    lint_recipe = makefile.split("\nlint:", 1)[1].split("\n\n", 1)[0]
    assert "check ." in lint_recipe
    assert "format --check" in lint_recipe
