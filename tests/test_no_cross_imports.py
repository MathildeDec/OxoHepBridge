#!/usr/bin/env python3
"""Garde-fou : le graphe des imports internes de `src/oxo_hep_bridge/` doit
rester acyclique.

`ruff` (règle `I`, tri des imports) ne détecte PAS les cycles d'imports —
aucune règle native pour ça. Le graphe est donc reconstruit ici par analyse
`ast` (pas par une liste tenue à la main, qui se désynchroniserait au premier
nouvel import) puis validé acyclique par un parcours en profondeur classique
(couleurs blanc/gris/noir).

Le détecteur lui-même est vérifié positivement sur un graphe avec un cycle
volontaire (`test_detector_flags_a_real_cycle`) avant d'être appliqué au
projet réel (`test_package_has_no_circular_imports`) — même discipline que
les autres garde-fous du projet qui prouvent qu'ils détecteraient une vraie
régression (voir `tests/conftest.py::FakePopen`, `tests/test_docs.py`).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "src" / "oxo_hep_bridge"


def _internal_imports(tree: ast.Module, package: str) -> set[str]:
    """Modules du même package importés par `tree` (noms courts, sans le
    préfixe de package)."""
    deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(package):
            deps.add(node.module.rsplit(".", 1)[-1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(package):
                    deps.add(alias.name.rsplit(".", 1)[-1])
    return deps


def build_import_graph(src_dir: Path, package: str) -> dict[str, set[str]]:
    """Construit `{module: {modules internes importés}}` par analyse `ast`
    de chaque fichier `.py` de `src_dir` (hors `__init__.py`, qui ne doit
    lui-même rien importer en interne dans ce projet)."""
    graph: dict[str, set[str]] = {}
    for path in src_dir.glob("*.py"):
        if path.stem == "__init__":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        graph[path.stem] = _internal_imports(tree, package)
    return graph


def find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """Retourne un cycle (liste de noms de modules) s'il en existe un dans
    `graph`, sinon `None`. DFS classique à 3 couleurs :
    blanc (non visité) / gris (en cours de visite) / noir (terminé)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(graph, WHITE)
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GRAY
        path.append(node)
        for dep in graph.get(node, ()):
            if dep not in graph:
                continue  # dépendance externe au graphe étudié, ignorée
            if color[dep] == GRAY:
                cycle_start = path.index(dep)
                return [*path[cycle_start:], dep]
            if color[dep] == WHITE:
                found = visit(dep)
                if found is not None:
                    return found
        path.pop()
        color[node] = BLACK
        return None

    for module in graph:
        if color[module] == WHITE:
            cycle = visit(module)
            if cycle is not None:
                return cycle
    return None


def test_detector_flags_a_real_cycle():
    """Le détecteur doit repérer un cycle volontaire avant d'être appliqué
    au projet réel — sinon un `find_cycle()` qui renverrait toujours `None`
    donnerait une fausse confiance au test suivant."""
    cyclic_graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": set()}
    cycle = find_cycle(cyclic_graph)
    assert cycle is not None
    # Le cycle détecté doit effectivement boucler sur lui-même
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}


def test_detector_accepts_an_acyclic_graph():
    acyclic_graph = {"a": {"b", "c"}, "b": {"c"}, "c": set()}
    assert find_cycle(acyclic_graph) is None


def test_package_has_no_circular_imports():
    graph = build_import_graph(SRC_DIR, "oxo_hep_bridge")
    # Le graphe ne doit pas être vide : sinon ce test validerait n'importe
    # quoi silencieusement si la découverte des fichiers venait à casser.
    assert len(graph) >= 10
    cycle = find_cycle(graph)
    assert cycle is None, f"cycle d'imports détecté : {' -> '.join(cycle)}" if cycle else None
