# Session 27 — 2026-09-06

### Contexte de la session
`docs/roadmap.md` § « À faire » toujours vide. En suivant la consigne de
`CLAUDE.md` (rejouer la chaîne d'outillage réelle plutôt que de rester sans
rien produire), `pytest --cov` a immédiatement révélé 3 échecs :
`tests/test_ci_config.py` ne trouvait pas `.github/workflows/ci.yml` —
`FileNotFoundError`. Vérification faite : le fichier est bien absent du
dépôt (pas de `.gitignore` qui l'exclurait), alors que `docs/roadmap.md` et
`CLAUDE.md` le documentent comme corrigé depuis la session 17. Régression
réelle (probablement perdue lors d'un transfert/export du dépôt), pas un
faux problème de sandbox.

### Corrigé
- Recréé `.github/workflows/ci.yml` (checkout, setup Python 3.11/3.12,
  `pip install -e ".[dev]"`, `ruff check`, `ruff format --check`, `mypy`,
  `pytest --cov=oxo_hep_bridge --cov-fail-under=80`) — cohérent avec les
  cibles `Makefile` (`lint`, `typecheck`, `test-cov`) et le seuil de
  couverture documenté dans le README, désormais vérifié par
  `tests/test_ci_config.py` plutôt que simplement documenté.
- Réseau et `tshark` tous deux disponibles dans ce sandbox (`apt-get
  install tshark` a fonctionné, comme en sessions 24/25) : suite complète
  rejouée après correctif — **322 tests au total** (321 passés + 1 skip
  conditionnel IPv6, aucun skip `tshark` cette fois puisqu'il était
  installé), couverture
  99,42 % (seuil CI 80 % respecté), `mypy`/`ruff check`/`ruff format
  --check` tous verts.

### Non fait sciemment (dépend d'une instance HOMER ou d'un trafic OXO réel)
- Intégration Docker HOMER/heplify-server, mapping métier complet des
  opcodes, corrélation d'appel avec état partagé.
