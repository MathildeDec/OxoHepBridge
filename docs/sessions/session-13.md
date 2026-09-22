# Session 13 — 2026-08-28

### Contexte de la session
Le point ouvert « aucune source officielle ALE » (`docs/roadmap.md`,
section « Reporté sciemment ») était bloqué faute de documentation
Alcatel-Lucent Enterprise accessible. Cette session dispose du **code
source du dissecteur Wireshark officiel** pour UAUDP/NOE
(`packet-uaudp.c`, `packet-noe.c`, `packet-ua3g.c`, `packet-ua.h`,
`packet-uaudp.h`, `packet-uasip.c` — copyright Alcatel-Lucent Enterprise,
Lars Ruoff <lars.ruoff@alcatel-lucent.com>, upstream Wireshark, GPL v2+),
fourni par l'utilisateur. Cela lève **partiellement** le point ouvert : ces
fichiers donnent un **dictionnaire de nommage protocolaire officiel**
(valeur numérique → libellé), pas un mapping vers des événements d'appel
SIP (INVITE/BYE/...) — cette seconde partie reste hors de portée, voir
détail plus bas et `docs/noe-ua3g-homer-mapping.md` §6bis.

### Ajouté
- Nouveau module `src/oxo_hep_bridge/ua_opcode_names.py` : dictionnaires
  `UAUDP_OPCODE_NAMES` (8 entrées), `NOE_CLASS_NAMES` (38), `NOE_METHOD_NAMES`
  (7), `NOE_SERVER_NAMES` (2), `NOE_EVENT_NAMES` (71, dont `EVT_ONHOOK`/
  `EVT_OFFHOOK`), `NOE_ERRCODE_NAMES` (22), `NOE_PROPERTY_NAMES` (144), et
  `decode_name()`. Tables **extraites programmatiquement** (script Python
  ad hoc parsant les `#define`/`enum` et les tableaux `value_string` du
  source fourni) plutôt que recopiées à la main, pour éviter toute erreur de
  transcription — script non conservé dans le repo (usage ponctuel de
  génération), le résultat figé fait foi.
  - Volontairement pas de table pour `packet-ua3g.c` (>4500 lignes, pas de
    table `value_string` unique exploitable de la même façon sans risque
    d'erreur de portée) — voir le docstring du module.
  - `NOE_PROPERTY_NAMES` est un espace de nommage global côté dissecteur
    (un entier donné renvoie toujours le même libellé, indépendamment de la
    classe) — vérifié dans la construction du tableau source, pas de table
    par-classe dans le dissecteur lui-même.
- `semantics.py` : nouvelle fonction `annotate_noe_event()` et ajout de
  champs `*_name` optionnels dans la payload JSON — `uaudp.opcode_name`,
  et par événement NOE `class_name`/`method_name`/`server_name`/
  `event_name`/`errcode_name`/`property_name`. Ajoutés **en plus** des
  valeurs numériques existantes, jamais à leur place ; jamais de valeur
  inventée (`decode_name()` retourne `None` si non résolvable, et le champ
  `*_name` n'est alors simplement pas ajouté) ; n'écrase jamais un champ
  `*_name` déjà présent dans l'événement source.
- **Vérification par recoupement avec des données réelles** (pas seulement
  des valeurs synthétiques) : les tables ont été confrontées aux captures
  d'exemple du projet (`tests/fixtures/ua3g_freeseating_ipv4.ek.ndjson` et
  les deux autres fixtures) — ex. `class=128` → "FrameBox", `method=2` →
  "SetProperty", `server=21` → "Call Server", `property=40` → "visible",
  cohérent avec un SetProperty "visible" sur une FrameBox observé dans la
  capture. Rejoué sur les 3 fixtures complètes : 100% des opcodes UAUDP et
  classes/méthodes NOE présents dans les captures se résolvent en libellé
  officiel (993 paquets UAUDP, 410 événements NOE sur la capture IPv6).
- 13 nouveaux tests dans `tests/test_ua_opcode_names.py` : contenu exact
  des tables (recopié depuis le source pour détecter toute régression de
  génération), résolution sur le cas réel recoupé ci-dessus, non-écrasement
  d'un champ `*_name` déjà présent, absence de nom inventé sur valeur non
  résolvable (`opcode=99`, `class="not-a-class"`), intégration bout-en-bout
  via `normalize()`. 237 tests au total (224 précédents + 13 nouveaux ; 1
  skip conditionnel IPv6 inchangé).
- Documentation : `docs/noe-ua3g-homer-mapping.md` (nouvelle section §6bis
  documentant ce qui est désormais sourcé vs ce qui reste ouvert),
  `docs/roadmap.md` (item mis à jour : nommage protocolaire fait, mapping
  d'événement d'appel toujours reporté — raison affinée), `README.md`
  (mention des champs `*_name` dans la description de la payload),
  `docs/architecture.md` (renvoi vers le nouveau module).

### Non fait — délibérément hors périmètre de cette session
- **Mapping vers des événements d'appel SIP** (INVITE/BYE/180/200...) :
  `EVT_ONHOOK`/`EVT_OFFHOOK` (désormais nommés) sont des événements
  **poste** (décroché/raccroché du combiné), pas des événements de
  signalisation d'appel au sens SIP — le tableau conceptuel de
  `docs/noe-ua3g-homer-mapping.md` §3 reste une lecture humaine, pas un
  mapping codé en dur, pour les mêmes raisons qu'avant (pas de trafic OXO
  réel pour valider la corrélation temporelle objectid NOE ↔ Call-ID SIP).
- Pas de table pour UA3G (voir plus haut).
- Intégration Docker HOMER/heplify-server : toujours hors périmètre, aucun
  nouvel élément cette session ne change ce constat (nécessite une
  instance HOMER réelle, network désactivé dans ce sandbox — voir Note de
  méthode ci-dessous).

### Note de méthode (limite de cet environnement de développement)
- Sandbox sans accès réseau (`pip install pytest` a échoué explicitement,
  vérifié) : `pytest` n'a pas pu être installé pour exécuter la suite via
  la commande standard. Contournement : stub minimal de `loguru` (le seul
  import bloquant hors stdlib pour `normalizer.py`/`tshark_source.py`) et
  exécution directe des fonctions `test_*` en dehors du framework pytest
  (les tests qui dépendent d'une fixture pytest — `FakePopen`, `capsys`,
  etc. — n'ont pas pu être rejoués ainsi et ont été laissés de côté pour
  cette vérification manuelle, sans lien avec les changements de cette
  session qui ne touchent ni `conftest.py` ni ces fixtures). Les 13
  nouveaux tests ne dépendent d'aucune fixture et ont donc pu être
  intégralement exécutés et vérifiés un par un. Les tables elles-mêmes ont
  été validées par un chemin indépendant : rejeu complet des 3 fixtures
  réelles du projet à travers le pipeline `parse_ek_line` → `flatten_layers`
  → `normalize` → décodage JSON, avec les valeurs résolues imprimées et
  relues manuellement (voir détail dans le message de livraison).
  Impossible de lancer HOMER11 réellement dans ce sandbox (`docker`/réseau
  indisponibles) — le code source fourni (`homer-homer11.zip`) a été
  parcouru en lecture mais n'a rien fait apparaître qui change la
  conclusion existante sur la corrélation inter-protocoles (hors périmètre
  technique du pont, voir `docs/noe-ua3g-homer-mapping.md` §4.B).
