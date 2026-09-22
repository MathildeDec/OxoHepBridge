# Protocole de session — oxo-hep-bridge

Importé par [`CLAUDE.md`](../CLAUDE.md) (`@docs/session-protocol.md`) : chargé
automatiquement à chaque démarrage de session, pas besoin de l'ouvrir à la main.

## Convention de session

Une session = **une seule tâche**, choisie dans `docs/roadmap.md` (section
« À faire — réalisable sans dépendance externe »). Ce fichier joue ici le
rôle d'un `features.md` : c'est la référence pour savoir ce qui reste à
faire, dans quel ordre, et pourquoi certains items sont volontairement
reportés.

**Si cette section est vide** (cas actuel depuis plusieurs sessions), ne
pas rester sans rien produire : exécuter réellement la chaîne d'outillage
(`pytest`/`mypy`/`ruff`, voir « Commandes » ci-dessous) si le réseau/l'outillage
sont disponibles dans le sandbox, et vérifier empiriquement les
affirmations documentaires existantes (docstrings, tableaux de doc,
commentaires) contre le comportement réel du code — en rejouant le
pipeline sur les fixtures réelles plutôt qu'en relisant seulement le code.
C'est ainsi que les sessions 17, 18 et 19 ont chacune trouvé un défaut réel
(CI absente du dépôt, docstring désynchronisé, tableau de chunks HEP
inexact) malgré une suite de tests déjà verte à 99%+ de couverture.

Toute modification (feature ou correction documentaire) doit suivre le
même triptyque, dans la même session :
1. **Tests automatisés** sur fixtures/mocks (`tests/fixtures/*.ek.ndjson`,
   `FakePopen`) — jamais de dépendance à un `tshark` ou un collecteur HOMER
   réel pour `make test`.
2. **Documentation à jour** : `README.md`, `docs/architecture.md`, et
   `docs/hep-chunks.md` pour tout nouveau chunk HEP.
3. **Entrée `CHANGELOG.md` datée**, avec une section « Contexte de la
   session » qui explique pourquoi cette tâche a été choisie (surtout
   quand elle vient d'une vérification empirique plutôt que du backlog).

Après toute modification, mettre à jour le décompte de tests dans
`docs/roadmap.md` (section « Fait ») avec le chiffre **réellement observé**
par une exécution de la suite — pas recompté à la main (cause de plusieurs
corrections passées, voir CHANGELOG sessions 16/17).
