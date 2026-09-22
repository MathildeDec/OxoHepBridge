# Session 21 — 2026-09-05

### Contexte de la session
`docs/roadmap.md` § « À faire » toujours vide. Contrairement à la session
20, **aucun accès réseau dans ce sandbox** (`pip install -e ".[dev]"`
échoue faute de miroir PyPI, `pytest`/`mypy`/`ruff`/`loguru` indisponibles)
— situation identique à celle des sessions 12 et 16 mentionnée dans
`CLAUDE.md`. Conformément à la consigne (« vérifier empiriquement les
affirmations documentaires... si le réseau/l'outillage sont disponibles »,
sinon replier sur ce qui reste possible), le pipeline réel a été rejoué
à la main : un stub minimal pour la seule dépendance externe du projet
(`loguru`, jamais livré, ni commité) a été placé hors du dépôt pour
permettre l'import des modules `src/oxo_hep_bridge/*`, puis
`subprocess.Popen` a été patché comme le fait `FakePopen` de
`tests/conftest.py` pour rejouer `Bridge.run()` sur les fixtures
`.ek.ndjson` existantes.

### Corrigé
- **`README.md` § « Options principales » était incomplet** : `--tshark-path`
  et `--correlation-field` sont deux options CLI réelles et fonctionnelles
  (`cli.py`, `config.py`), mais absentes du tableau récapitulatif du README
  — `--correlation-field` n'était mentionné qu'une fois, en passant, dans
  `docs/architecture.md#corrélation`, et `--tshark-path` n'était documenté
  nulle part. Trouvé en comparant la liste des options de
  `cli.build_parser()` au tableau du README plutôt qu'en relisant le README
  seul. Les deux lignes ajoutées au tableau.
- `--tshark-path` n'avait aucun `help=` dans `cli.py` (seule option du
  fichier dans ce cas) — ajouté, sur le modèle des options voisines.

### Ajouté
- 1 nouveau test (`tests/test_docs.py::test_all_cli_options_documented_in_readme`) :
  compare programmatiquement chaque option canonique de `build_parser()`
  (hors alias secondaires comme `--hep-auth-key`, et hors `--help`) au
  tableau du README, pour empêcher qu'une future option CLI reste
  non documentée — même défaut de méthode que les corrections
  documentaires des sessions 17/18/19/20 (une affirmation ou une omission
  documentaire jamais revérifiée empiriquement contre le code réel).
  **Non exécuté via `pytest` faute d'outillage disponible dans ce
  sandbox** ; sa logique a été validée manuellement par un script Python
  direct reproduisant exactement l'assertion du test (voir ci-dessus),
  qui passe. Décompte de tests non mis à jour dans `docs/roadmap.md` en
  conséquence (313 + 1 = 314 attendus, à reconfirmer par une exécution
  réelle de la suite dès qu'un sandbox avec réseau sera disponible — même
  réserve que sessions 12/16).
