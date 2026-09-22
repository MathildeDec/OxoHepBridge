# Architecture

## Vue d'ensemble

```
┌─────────────┐      NDJSON        ┌──────────────┐      dict       ┌─────────────┐
│   tshark    │ ─────────────────▶ │ TsharkEKSource│ ───────────────▶│  normalize  │
│  -T ek      │  (subprocess)      │ (parse+flatten)│  (flat fields) │             │
└─────────────┘                    └──────────────┘                  └──────┬──────┘
                                                                             │ HepPacket
                                                                             ▼
                                                                    ┌─────────────────┐
                                                                    │  encode (hep.py) │
                                                                    └────────┬────────┘
                                                                             │ bytes HEPv3
                                                                             ▼
                                                                    ┌─────────────────┐
                                                                    │  UDP/TCP/TLS    │
                                                                    │  Sender /       │
                                                                    │  NullSender     │
                                                                    └────────┬────────┘
                                                                             │ UDP, TCP ou TLS
                                                                             │ (IPv4 ou IPv6)
                                                                             ▼
                                                                    HOMER / heplify-server
```

## Choix techniques

### Pourquoi `tshark -T ek` en subprocess plutôt que pyshark

pyshark encapsule le même appel à `tshark` mais ajoute une couche asyncio et un
overhead d'analyse XML/JSON par objet qui complique le debugging et les tests
(mock plus difficile). L'appel direct au binaire via `subprocess.Popen` avec
`-T ek` (format NDJSON Elasticsearch Bulk) donne :

- un flux ligne par ligne facile à parser sans dépendance,
- un format déjà structuré (pas de parsing XML),
- un contrôle total sur le cycle de vie du processus (stderr non bloquant,
  arrêt propre).

### Format `-T ek` : particularités constatées

En observant les captures officielles Wireshark (`ua3g_freeseating_ipv4.pcap`,
`ua3g_freeseating_ipv6.pcap`, `uaudp_ipv6.pcap`), plusieurs propriétés du
format EK ont été identifiées empiriquement :

1. **Lignes appariées** : chaque paquet produit une ligne d'action bulk
   (`{"index": {...}}`) suivie d'une ligne document (`{"layers": {...}}`).
   `parse_ek_line()` ignore la première.
2. **Préfixage double** : chaque champ est nommé `<protocole>_<protocole>_<champ>`,
   par exemple `uaudp_uaudp_opcode` pour `uaudp.opcode`. Ceci uniquement quand
   **aucun** filtre `-e` n'est appliqué — avec `-e uaudp.opcode`, tshark bascule
   sur un préfixage simple (`uaudp_opcode`) sans la structure `layers`. C'est
   pourquoi `oxo-hep-bridge` ne restreint jamais les champs `-e` par défaut :
   la liste `CaptureConfig.fields` est vide.
3. **NOE en liste** : un paquet UA3G peut empiler plusieurs messages NOE ; ils
   apparaissent alors comme une liste d'objets sous la clé `noe` (top-level
   après aplatissement, provenant de `layers.ua.noe`).
4. **Décodage non automatique** : sur `uaudp_ipv6.pcap`, le port UDP observé
   (32640) n'est pas reconnu automatiquement par le dissecteur UAUDP — il faut
   forcer `--decode-as udp.port==32640,uaudp` pour que tshark expose les
   champs `uaudp_*`. Sans cela, le paquet reste classé `data` générique.

### Corrélation

Aucun identifiant de session natif n'est exposé par le dissecteur UAUDP dans
les fixtures observées. `build_correlation_id()` synthétise donc une clé
`src_ip:src_port-dst_ip:dst_port`, suffisante pour que HOMER regroupe les
paquets d'un même flux UDP. Un champ tshark plus stable (identifiant de poste,
d'appel) peut être fourni via `--correlation-field` s'il est disponible.

### Tolérance aux paquets non-UA

Le flux capturé sur un port UAUDP contient souvent du bruit (DHCP, TFTP, SMB)
que `normalize()` reconnaît et ignore (retourne `None`) plutôt que de générer
un paquet HEP vide.

### Keepalive HEP périodique

En capture live, le pont peut rester silencieux longtemps (nuit, PABX peu
chargé) sans que le collecteur puisse distinguer « pas de trafic » d'« agent
tombé ». `KeepaliveScheduler` (`keepalive.py`) tourne alors sur un thread
daemon séparé et envoie, toutes les `hep.keepalive_interval` secondes, un
`HepPacket` de signalement (`build_keepalive_packet`) via le même `Sender`
que le flux normal (respecte donc le mode `--dry-run`) :

- chunk générique `KEEPALIVE_TIMER` (0x000D) porteur de l'intervalle,
- payload JSON minimal `{"type": "keepalive", "node_name": ..., "capture_agent_id": ..., "interval_seconds": ...}`
  facilement filtrable côté collecteur,
- adresses IP/ports neutres (`0.0.0.0:0`) puisqu'aucun flux réel n'est représenté.

Désactivé par défaut (`keepalive_interval = 0`). `Bridge.run()` ne démarre le
scheduler qu'en capture live (`--interface`) : une relecture `--pcap` se
termine d'elle-même bien avant tout intervalle de keepalive raisonnable, un
keepalive n'y aurait pas de sens.

### Arrêt propre : SIGINT et SIGTERM

`cli.main()` installe le même handler pour `SIGINT` (Ctrl-C, usage manuel en
terminal) et `SIGTERM` (signal par défaut de `systemctl stop`/`systemctl
restart` — voir `systemd/oxo-hep-bridge.service`, aucun `KillSignal` custom
n'y est défini). Le handler lève `KeyboardInterrupt` dans le thread principal,
ce qui remonte à travers `Bridge.run()` : le `finally` de `run()` arrête le
keepalive et ferme le sender (socket UDP), puis `main()` logge un message
d'arrêt et retourne le code `130`. Les handlers d'origine (ceux en place avant
l'appel à `main()`) sont restaurés dans un `finally` dédié, que l'arrêt soit
propre, brutal (exception inattendue) ou déclenché par un signal.

Avant ce mécanisme, seul `SIGINT` était intercepté : un `systemctl stop`
tuait le process avec le signal par défaut sans laisser `tshark`, la socket
d'envoi ou le thread de keepalive se terminer proprement, et sans résumé de
stats de fin de run.

Un seul chemin de fermeture existe pour chaque ressource, jamais dupliqué
entre plusieurs déclencheurs possibles : le `finally` de `Bridge.run()`
arrête le keepalive et ferme le sender, et le `finally` dédié de `main()`
notifie `STOPPING=1` à systemd, arrête le watchdog et restaure les handlers
de signaux d'origine — que l'arrêt vienne de `SIGINT`, de `SIGTERM` ou d'une
exception inattendue.

### Résolution du collecteur HEP : IPv4, IPv6, DNS

`UDPSender` (`sender.py`) ne fixe plus la famille de socket à `AF_INET` : au
premier envoi, `--hep-host` est résolu via `socket.getaddrinfo()`, qui couvre
uniformément un littéral IPv4, un littéral IPv6 (y compris avec zone id) et
un nom d'hôte DNS résolvant vers l'une ou l'autre famille. La socket est
ouverte avec la famille retournée (`AF_INET`/`AF_INET6`) et le `sockaddr`
résolu est réutilisé pour les envois suivants, jusqu'à fermeture.

Avant ce changement, un `--hep-host` IPv6 littéral (ex: collecteur HOMER
joint uniquement par son adresse IPv6) faisait échouer silencieusement
chaque `sendto()` (`OSError: Address family not supported by protocol`),
compté comme erreur d'envoi sans qu'aucun message n'explique la cause — la
socket `AF_INET` refusait toute adresse IPv6.

En cas d'échec (résolution DNS ou envoi réseau), la socket est refermée et
la résolution retentée au prochain envoi plutôt que de rester bloquée sur
une adresse/famille figée pour tout le run — utile en cas de bascule DNS
(nouveau pod/IP côté collecteur) ou de panne réseau transitoire.

### Transport HEP : UDP, TCP, TLS

`heplify-server` expose trois listeners indépendants pour recevoir du HEP :
UDP (comportement historique), TCP en clair et TCP+TLS — chacun sur une
adresse/port configurable côté collecteur. `--hep-transport` (`udp` par
défaut, ou `tcp`/`tls`) choisit lequel `oxo-hep-bridge` utilise pour
atteindre `heplify-server`. Ce choix est indépendant du protocole du trafic
OXO capturé (le chunk HEP « IP protocol ID », voir
[hep-chunks.md](hep-chunks.md), continue de refléter UDP puisque UAUDP
lui-même est transporté en UDP entre le PABX et les postes) : il ne
concerne que le dernier saut, entre `oxo-hep-bridge` et le collecteur.

- **`udp`** (défaut) : `UDPSender` (`sender.py`) crée puis met en cache une
  socket au premier envoi, comme `TCPSender`, mais sans poignée de main
  (UDP est sans connexion). La socket est néanmoins `connect()`ée dès sa
  création — sans effet réseau immédiat pour UDP, mais cela permet au
  noyau de remonter un `ConnectionRefusedError` (ICMP « port unreachable »)
  sur un envoi ultérieur si le port distant est fermé, ce qu'une socket UDP
  non connectée ignore silencieusement (vérifié empiriquement, session
  39/40 : voir `tests/test_sender.py`). Nuance à connaître : cette
  détection n'est jamais immédiate, l'ICMP mettant un aller-retour à
  revenir — c'est le paquet *suivant* qui échoue, pas celui qui a
  effectivement déclenché la coupure côté collecteur.
- **`tcp`** : `TCPSender` (`sender.py`) ouvre une connexion au premier envoi
  et la réutilise pour tous les paquets suivants — comme la socket UDP mise
  en cache par `UDPSender`, mais avec une vraie poignée de main TCP cette
  fois. Aucun framing supplémentaire n'est ajouté côté client : chaque
  paquet HEPv3 encodé porte déjà sa longueur totale dans les 6 premiers
  octets de son en-tête (`hep.py`, `PACKET_HEADER_FMT`), ce qui suffit à
  délimiter les paquets sur le flux — ils sont donc envoyés tels quels, à la
  suite les uns des autres, sur la connexion persistante. `TCP_NODELAY` est
  activé sur la socket brute dès `_connect()`, juste après `connect()` (et
  avant l'éventuel enrobage TLS, voir ci-dessous) : l'algorithme de Nagle,
  actif par défaut, retarderait sinon l'émission de chaque petit paquet HEP
  en attendant un accusé de réception ou d'accumuler assez de données pour
  un segment plein — un compromis pensé pour un flux d'écriture continu,
  sans intérêt ici puisque chaque paquet est déjà envoyé seul via
  `sendall()` (implémenté en session 41, voir `tests/test_sender.py`).
- **`tls`** : identique à `tcp`, avec la connexion enveloppée dans un
  contexte TLS client (`ssl.SSLContext` de la stdlib — aucune dépendance
  ajoutée) avant le premier envoi. Vérification du certificat serveur (nom
  d'hôte + chaîne de confiance) activée par défaut via
  `ssl.create_default_context()`, avec CA système ou personnalisée
  (`--hep-tls-ca-file`, chargée via `load_verify_locations`).
  `--hep-tls-insecure` (`tls_verify = false` en TOML) désactive
  explicitement cette vérification — pensé pour un labo contre un
  `heplify-server` à certificat auto-signé, jamais recommandé en
  production : sans elle, un attaquant en position d'interception pourrait
  se faire passer pour le collecteur sans être détecté. Comme `--dry-run`,
  c'est un flag CLI à sens unique : sa présence force `tls_verify` à False,
  son absence préserve ce que le TOML/l'environnement ont déjà positionné
  (pas de `--hep-tls-secure` pour réactiver depuis la CLI une vérification
  désactivée ailleurs).

Pour `tcp` et `tls`, un échec de connexion, de poignée de main TLS
(certificat invalide, nom d'hôte qui ne correspond pas) ou d'envoi referme
la connexion et la retente au prochain paquet — même politique de
résilience sans état que pour UDP. La socket TCP brute, si elle a été créée
avant qu'un tel échec survienne, est explicitement refermée par
`_connect()` avant de propager l'exception : elle ne fuit jamais.

`--hep-tls-ca-file`/`tls_verify = false` n'ont d'effet qu'avec
`transport = "tls"` ; les positionner sans activer ce transport produit un
avertissement au démarrage (`cli.py`) plutôt qu'un échec silencieux.

### Retry avec backoff exponentiel sur échec d'envoi

Avant cette fonctionnalité, un échec d'envoi (UDP/TCP/TLS) — même transitoire,
type coupure réseau de quelques centaines de millisecondes ou saturation
ponctuelle du buffer socket — coûtait irrémédiablement le paquet HEP en
cours : il n'était jamais réémis, seulement compté dans `stats.send_errors`.
`--hep-retries N` (`hep.send_retries` en TOML/env, 0 par défaut = comportement
historique inchangé) fait retenter l'envoi jusqu'à `N` fois supplémentaires
avant d'abandonner, avec un backoff exponentiel entre chaque tentative
(`--hep-retry-backoff`, délai de base doublé à chaque essai : `0.5s, 1s,
2s...` pour la valeur par défaut).

La logique de retry est factorisée dans `sender.py:_send_with_retry()`,
partagée par `UDPSender` et `TCPSender` (même politique pour les deux
transports, y compris `tls` puisque `TCPSender` gère aussi TLS) :
`send_once()` et `close()` lui sont injectés en callables plutôt que de
dépendre d'un sender concret, pour rester testable isolément sans mocker
de socket. `time.sleep` est lui aussi injectable (paramètre `sleep` du
constructeur) — les tests unitaires y substituent une simple liste pour
vérifier la séquence de délais sans ralentir la suite.

`retry_count`, cumulé sur la durée de vie du sender (pas remis à zéro entre
deux paquets), est reporté dans `stats.send_retries` en fin de run par
`Bridge.run()` — via `self.sender.retry_count`, qui vaut `0` par défaut sur
la classe de base `Sender` (voir plus bas, section « Contrôle de type
statique (mypy) ») : `NullSender` (dry-run) hérite de ce défaut sans le
redéfinir, puisqu'il ne peut pas échouer et qu'un retry n'y aurait aucun
sens — `make_sender()` ne lui transmet donc pas `retries`/`retry_backoff`.
Un paquet qui échoue puis finit par réussir grâce
au retry n'incrémente PAS `stats.send_errors` — seul l'échec définitif après
épuisement des tentatives le fait — mais `stats.send_retries` > 0 reste
visible dans le résumé de fin de run (`Stats.log_summary()`) même sans
erreur, pour distinguer un run parfaitement propre d'un run qui a dû
composer avec des coupures brèves mais s'en est remis.

En cas d'échec, la socket/connexion est systématiquement refermée avant de
retenter (`close()` puis reconnexion complète au prochain essai) — même
logique que la résilience sans état déjà en place pour les échecs simples :
une résolution DNS qui a changé ou une adresse différente côté collecteur
doit pouvoir être reprise en compte à la prochaine tentative plutôt que de
rester bloquée sur une socket/famille figée.

### Compression du payload (chunk 0x0010)

`hep.py:encode(pkt, compress=True)` remplace le chunk `PAYLOAD` (0x000F) par
`COMPRESSED_PAYLOAD` (0x0010, `pkt.payload` compressé via `gzip.compress()`)
— jamais les deux chunks ensemble, c'est la présence de l'un ou l'autre qui
indique au collecteur comment lire le payload. `compress` se propage depuis
`config.hep.compress_payload` (`--hep-compress-payload` / TOML / env) jusqu'à
`make_sender()`, appliqué uniformément par `NullSender`, `UDPSender` et
`TCPSender` — y compris en dry-run, pour pouvoir valider l'encodage compressé
sans réseau.

**Non compatible avec HOMER11 en l'état** (vérifié en lisant
`src/decoder/decoder.go` et `hep.go` du projet HOMER11 : la liste des chunks
connus s'arrête à `NodeName` 0x0013, tout chunk inconnu — dont 0x0010 —
tombe dans un `default:` muet). Contrairement à `KEEPALIVE_TIMER` (0x000D,
également ignoré par HOMER11 mais sans conséquence puisque le payload JSON
keepalive reste porté par le chunk 0x000F, lui décodé), un payload compressé
non décodé par le collecteur est purement et simplement perdu. Voir le détail
dans [hep-chunks.md](hep-chunks.md#compression-du-payload-chunk-0x0010).
`cli.py` avertit explicitement au démarrage si l'option est activée, pour ne
pas laisser cette perte silencieuse passer inaperçue.

### Fréquence du log de progression (`logging.stats_interval`)

La progression du run (« progression : N paquets envoyés... ») était jusqu'ici
loguée sur un seuil fixe codé en dur dans `Bridge.run()` (`stats.sent % 500
== 0`). Sur un flux à faible débit (PABX peu chargé, tests en environnement
de labo avec peu de trafic), ce seuil pouvait ne jamais être atteint avant la
fin du run — aucun signal intermédiaire pour vérifier que le pont progresse
réellement, seul le résumé final (`Stats.log_summary()`) restait disponible.

`logging.stats_interval` (`--stats-interval` / `OXOHEP_STATS_INTERVAL` /
`[logging] stats_interval` en TOML, 500 par défaut = comportement historique
inchangé) rend ce seuil configurable. La condition dans `Bridge.run()` lit
`self.config.logging.stats_interval` à chaque itération plutôt qu'une
constante, avec une garde `interval > 0` : une valeur `<= 0` désactive
purement le log de progression intermédiaire, sans toucher au résumé de fin
de run qui reste, lui, toujours affiché (`Stats.log_summary()` est appelé
indépendamment de `stats_interval`). Placé dans `LoggingConfig` plutôt que
dans `HepConfig` : il s'agit d'un réglage de cadence de journalisation, pas
d'un paramètre du protocole HEP ou du transport.

### Sortie JSON structurée (`logging.json_file`) : exploiter `Stats.to_dict()`

`Stats.to_dict()` (`stats.py`) existait depuis plusieurs sessions, testé
pour lui-même (`test_stats.py::test_stats_to_dict_roundtrip`) mais jamais
consommé par `bridge.py`/`cli.py` — dernier candidat vérifié de
`docs/roadmap.md` (session 39), implémenté en session 42.

Deux pistes avaient été identifiées : (a) un sink JSON loguru
(`logger.add(sink, serialize=True)`, doc à jour confirmée via Context7
`/delgan/loguru`) pour une ligne de résumé en JSON, ou (b) un fichier de
stats périodique style « textfile collector » Prometheus/node_exporter,
écrit indépendamment de loguru. Choix retenu : (a) seule — pas de fichier
Prometheus séparé. Justification : `to_dict()` produit déjà un dict prêt à
sérialiser, et loguru sait nativement lier des données structurées à un
enregistrement de log via `logger.bind(clé=valeur)` — un sink ajouté avec
`serialize=True` sérialise alors tout le `record` en JSON, `extra` compris
(vérifié empiriquement : `record["extra"]["stats"]` contient exactement le
dict lié, voir `tests/test_stats.py`). Aucun code de sérialisation JSON à
écrire ni tester séparément ; le format Prometheus texte (types de métriques,
noms, labels) aurait demandé une implémentation et des tests dédiés pour un
bénéfice équivalent ici (pas de scraping Prometheus mentionné dans le besoin
d'origine).

Câblage, `logging.json_file` (`--log-json-file` / `OXOHEP_LOG_JSON_FILE` /
`[logging] json_file` en TOML, absent par défaut = comportement historique
inchangé) :
- `cli.py` ajoute un second sink loguru (`logger.add(path, serialize=True,
  level=...)`) si `json_file` est renseigné, en plus du sink `stderr`
  existant — toute la journalisation s'y retrouve dupliquée en JSON Lines
  (un objet par ligne), pas seulement les enregistrements liés à `Stats`.
- `Stats.log_summary()` (résumé de fin de run) et le log de progression de
  `Bridge.run()` (`logging.stats_interval`, voir ci-dessus) lient chacun
  `stats.to_dict()` à leur enregistrement via `logger.bind(stats=...)`
  avant d'appeler `logger.info()` — invisible côté texte humain (stderr,
  inchangé), mais présent sous `record["extra"]["stats"]` dès qu'un sink
  `serialize=True` est actif. Un seul appel à `to_dict()` par
  `log_summary()` (pas un par ligne de log qu'elle émet), le dict calculé
  étant réutilisé pour les deux `logger.bind()` possibles (résumé +
  détail).
- Aucun changement de comportement quand `json_file` est absent (défaut) :
  le sink supplémentaire n'est simplement jamais ajouté, `logger.bind()`
  reste un no-op visible côté texte (les clés liées n'apparaissent pas
  dans le format d'affichage stderr par défaut).

### Validation du TOML : table/clé inconnue rejetée explicitement

`apply_toml()` chargeait jusqu'ici le fichier TOML en testant, pour chaque
clé attendue, `if "clé" in table` dans `_apply_toml_capture()`/
`_apply_toml_hep()`/`apply_toml()` (sections `normalizer`/`logging`). Une
clé absente de cette liste — qu'elle soit une vraie typo (`hots` au lieu de
`host`) ou une clé placée hors de sa section `[table]` (`host = "..."` au
premier niveau au lieu de sous `[hep]`) — n'était tout simplement jamais lue :
ni erreur, ni avertissement, le champ visé restait à sa valeur par défaut et
le run démarrait quand même. Un `[hep] hots = "10.0.0.5"` dans
`config/oxo-hep-bridge.toml` laissait par exemple le pont continuer à
pointer vers `127.0.0.1` — une mauvaise configuration invisible sans relire
le TOML ligne à ligne face au code source.

`ConfigError` (nouvelle exception, `config.py`) est levée dans deux cas,
tous deux distincts d'un TOML syntaxiquement invalide (`tomllib.
TOMLDecodeError`, déjà propagée telle quelle sans changement) :

- une entrée de premier niveau du fichier n'appartient pas aux quatre
  tables connues (`capture`, `hep`, `normalizer`, `logging`) — couvre à la
  fois une section mal nommée (`[hepp]`) et une clé écrite hors de toute
  section (`host = "..."` au lieu de `[hep]\nhost = "..."`, TOML valide où
  `host` devient une entrée de premier niveau) ;
- une clé à l'intérieur d'une table connue n'appartient pas à l'ensemble des
  clés attendues pour cette table (`_CAPTURE_KEYS`/`_HEP_KEYS`/
  `_NORMALIZER_KEYS`/`_LOGGING_KEYS`, tenus à jour manuellement en miroir
  des blocs `_apply_toml_*()`).

`_validate_toml_table()` centralise ce contrôle (appelée une fois par table
dans `apply_toml()`, avant application des valeurs) et couvre aussi le cas
où la table elle-même n'est pas un dict TOML (`hep = "x"` plutôt que
`[hep]` : `isinstance(value, dict)` échoue avant même de regarder les clés).
Une liste explicite de clés connues a été préférée à une solution générique
par introspection des dataclasses (`fields(HepConfig)`, etc.) : les noms de
clé TOML (`snake_case`) correspondent presque toujours au nom du champ mais
pas systématiquement dans son intégralité au fil des futures clés — une
liste explicite reste plus simple à lire et à maintenir en miroir des
fonctions `_apply_toml_*()` existantes que d'introduire une couche de
mapping supplémentaire pour ce seul usage.

Côté `cli.py`, `main()` encadre l'appel à `Config.load()` d'un
`try`/`except` dédié (`ConfigError`, `tomllib.TOMLDecodeError`) — hors du
`try`/`except Exception` qui entoure `bridge.run()`, puisqu'il s'agit d'une
erreur d'usage/config détectée avant même la construction du `Bridge`, pas
d'un échec du run lui-même. Code de retour `2`, aligné sur les erreurs
d'arguments d'`argparse` (`build_parser().error()`) : dans les deux cas,
c'est une erreur d'usage, pas un échec du run.

### Notification systemd (`sd_notify`) et watchdog

`systemctl status` ne distingue pas, par défaut, un pont qui fonctionne
normalement d'un pont dont le thread de lecture tshark s'est bloqué en
silence : le process reste vivant (pas de code de sortie), donc le service
reste marqué actif indéfiniment, sans aucun signal de santé applicative.
`sdnotify.py` implémente le protocole `sd_notify` de systemd — un
datagramme texte envoyé sur la socket Unix `NOTIFY_SOCKET` — sans dépendance
à `libsystemd` ni au paquet PyPI `sdnotify` (seul `socket.AF_UNIX` de la
stdlib est nécessaire, dans le même esprit « pas de dépendance lourde » que
le reste du projet) :

- `SdNotifier` envoie `READY=1`, `STOPPING=1`, `WATCHDOG=1` et `STATUS=...`.
  No-op silencieux si `NOTIFY_SOCKET` n'est pas définie (hors service
  systemd, ou usage en CLI manuelle) — `cli.py` appelle `ready()`/
  `stopping()` inconditionnellement sans avoir à tester à chaque fois si le
  process tourne sous systemd, même contrat que `Sender.close()`
  (`sender.py`, no-op par défaut sur la classe de base) pour `NullSender`
  ailleurs dans le projet.
- `cli.main()` envoie `READY=1` juste avant `bridge.run()`, une fois la
  configuration validée et `Bridge` construit avec succès — c'est la
  définition de « démarrage terminé » retenue ici (le lancement du
  subprocess tshark, lui, a lieu à l'intérieur de `bridge.run()`).
  `STOPPING=1` est envoyé dans le `finally` qui entoure `bridge.run()`,
  donc sur les trois chemins de sortie (retour normal, `KeyboardInterrupt`
  sur SIGINT/SIGTERM, exception fatale) — évite un faux `failed` côté
  systemd pendant un arrêt volontaire qui prend quelques centaines de
  millisecondes (fermeture de la socket HEP, du subprocess tshark).
- `WatchdogScheduler` envoie `WATCHDOG=1` périodiquement sur un thread
  daemon (même style que `KeepaliveScheduler`), à **la moitié** de
  l'intervalle annoncé par systemd (`WATCHDOG_USEC`, dérivé de
  `WatchdogSec=` dans l'unité — marge de sécurité recommandée par la
  documentation `sd_notify(3)` pour tolérer un cycle de scheduling
  ponctuellement plus lent sans déclencher de redémarrage intempestif).
  `resolve_watchdog_interval()` lit `WATCHDOG_USEC`/`WATCHDOG_PID` (ce
  dernier vérifié contre le PID courant, comme recommandé par la
  documentation, pour ignorer un environnement hérité par un sous-process
  qui ne serait pas celui réellement surveillé). Retourne `None` — watchdog
  désactivé, comportement historique inchangé — si `WatchdogSec=` n'est pas
  configuré côté unité systemd, exactement comme `keepalive_interval = 0`
  désactive le keepalive HEP.

**Portée volontairement limitée**, documentée explicitement plutôt que
présentée comme une détection de blocage complète (même esprit que
l'avertissement sur `--hep-compress-payload`, voir
[hep-chunks.md](hep-chunks.md#compression-du-payload-chunk-0x0010)) : le
ping watchdog est envoyé par un thread indépendant, sur un simple timer —
il ne vérifie à aucun moment que la boucle principale de `Bridge.run()`
progresse réellement. Il détecte donc un process totalement figé
(interpréteur bloqué par un deadlock complet, segfault, process disparu —
et dans ce cas `Restart=on-failure`, déjà en place, redémarre le service),
mais **pas** un appel réseau individuellement bloqué (ex: `send()` TCP qui
ne revient jamais parce que le collecteur cesse de lire sans fermer la
connexion) tant que le thread watchdog, lui, continue de tourner
indépendamment. Un watchdog asservi à la progression réelle de la boucle nécessiterait un
heartbeat mis à jour à chaque itération de `Bridge.run()` — écarté ici : un
tel heartbeat resterait aussi silencieux pendant une période creuse
légitime (pas de trafic OXO, cf. keepalive HEP plus haut), rendant le seuil
de détection soit trop lâche pour être utile, soit à risque de redémarrer
un pont parfaitement sain mais simplement inactif.

Câblé côté unité systemd : `Type=notify` (au lieu de `Type=simple`, voir
`systemd/oxo-hep-bridge.service`) — systemd attend `READY=1` avant de
considérer le service comme démarré, plutôt que de le supposer
immédiatement à l'exécution d'`ExecStart`. `WatchdogSec=` reste commenté
dans le fichier d'unité fourni (opt-in explicite, pas de valeur imposée :
le bon seuil dépend du taux de trafic OXO attendu et de la marge
souhaitée).

### Contrôle de type statique (mypy)

`ruff check`/`ruff format` (lint + style) ne détectent pas une erreur de
type — ex: un attribut lu sur un objet qui ne l'expose pas dans certains
cas seulement, un paramètre positionné dans le mauvais ordre entre deux
appels de fonctions aux signatures proches. La CI (`.github/workflows/ci.yml`)
exécute donc `mypy` en complément, sur le code déjà entièrement annoté du
projet.

**Périmètre volontairement limité** à `src/oxo_hep_bridge` et `tools/`
(`[tool.mypy]` dans `pyproject.toml`, clé `files`) — pas `tests/` : les
fakes/mocks de test (`RecordingSender`, `FailingSender`...) assignent
délibérément une sous-classe concrète à un attribut dont le type statique
est la classe de base (`bridge.sender: Sender`), un pattern parfaitement
sain à l'exécution mais que mypy signalerait sans bénéfice réel pour ce
projet — durcir le typage des tests eux-mêmes n'est pas l'objectif ici,
seulement celui du code livré. `disallow_untyped_defs` est activé sur ce
périmètre réduit : toute nouvelle fonction ajoutée dans `src/oxo_hep_bridge`
ou `tools/` sans annotations fait donc échouer la CI, plutôt que de
dépendre de la discipline de chaque contribution.

Ce contrôle a mis en évidence un pattern existant que mypy ne peut pas
vérifier statiquement : `Bridge.run()` utilisait `hasattr(self.sender,
"close")` et `getattr(self.sender, "retry_count", 0)` parce que `NullSender`
et les senders factices de test n'exposaient ni l'un ni l'autre — mypy ne
fait pas de narrowing de type sur un `hasattr()` pour une classe nominale
(contrairement à un `isinstance()`), et aurait donc signalé `self.sender.close()`
comme un attribut potentiellement absent du type statique `Sender`. Corrigé
à la racine plutôt que contourné par un `# type: ignore` au point d'appel :
`Sender` (`sender.py`) déclare désormais `retry_count: int = 0` et
`close() -> None` (no-op) directement sur la classe de base, hérités tels
quels par `NullSender` et par tout sender factice de test qui ne les
redéfinit pas ; `UDPSender`/`TCPSender` continuent de les surcharger comme
avant. `Bridge.run()` appelle donc `self.sender.close()` et lit
`self.sender.retry_count` sans condition — le comportement à l'exécution
est inchangé (un no-op reste un no-op), mais le point d'appel n'a plus
besoin de connaître dynamiquement les sous-classes concrètes de `Sender`.

Seuil de couverture minimal (`--cov-fail-under=80`, appliqué à la fois par
la CI et par `make test-cov`) en complément : un plancher pour repérer une
régression de couverture (code ajouté sans test associé), pas un objectif à
atteindre — la suite existante (213+ tests avant ce durcissement) couvre
déjà large marge au-delà de ce seuil sur la plupart des modules.

### Gestion des dépendances et de l'environnement (uv)

Migration effectuée en session 44 : l'environnement de développement
(venv + dépendances) est géré par [uv](https://docs.astral.sh/uv/) plutôt
que par la combinaison manuelle `python3 -m venv` + `pip install -e
".[dev]"` utilisée jusque-là. Le projet n'a jamais utilisé Poetry — le
`[build-system]` de `pyproject.toml` (setuptools) est inchangé, uv est
agnostique du backend de build et se contente de résoudre/installer les
dépendances déclarées dans `[project]`/`[project.optional-dependencies]`.

Ce que uv change concrètement :

- **`uv.lock`** (committé au dépôt, inclus dans l'archive de livraison —
  voir `tests/test_packaging.py`) fige exactement les versions résolues
  de toutes les dépendances (directes et transitives), pour une
  installation reproductible d'une machine à l'autre — `pip install -e
  ".[dev]"` seul ne garantissait aucune version transitive figée.
- **`uv sync --extra dev`** (invoqué par `make dev`/`make install` et
  `install.sh`) crée `.venv` s'il n'existe pas encore et l'actualise sur
  l'état exact de `uv.lock`, en une seule commande — remplace les deux
  étapes séparées `python3 -m venv` puis `pip install`.
- **`uv run <outil>`** (utilisé par le `Makefile` et par la CI,
  `.github/workflows/ci.yml`) résout l'environnement du projet et exécute
  la commande dedans, sans avoir besoin d'activer `.venv` au préalable ni
  de coder en dur un chemin `.venv/bin/<outil>` — un venv activé
  manuellement (`source .venv/bin/activate`) reste possible et continue
  de fonctionner en parallèle, c'est une préférence de l'utilisateur, pas
  un choix exclusif.
- **CI** (`--locked`) : `uv sync --locked --extra dev` fait échouer le job
  si `uv.lock` n'est pas exactement synchronisé avec `pyproject.toml`,
  plutôt que de régénérer silencieusement le lock en CI — garde-fou
  équivalent en esprit au seuil de couverture (`--cov-fail-under=80`) ou
  au contrôle de type (`disallow_untyped_defs`) déjà en place : une
  dérive doit faire échouer la CI, pas être absorbée silencieusement.

`[project.optional-dependencies].dev` (ruff/mypy/pytest/pytest-cov/
pre-commit) reste la source déclarative des dépendances de développement,
inchangée dans sa structure — uv les installe via l'extra `dev` (`uv sync
--extra dev`) exactement comme `pip install -e ".[dev]"` le faisait
auparavant ; aucune dépendance n'a été ajoutée, retirée ou déplacée vers
un groupe `[dependency-groups]` séparé à l'occasion de cette migration.

### Séparation des modules et absence de dépendances circulaires

`src/oxo_hep_bridge/` sépare la logique métier (`bridge.py`, `normalizer.py`,
`semantics.py`, `hep.py`, `sender.py`, `keepalive.py`, `config.py`,
`stats.py`, `tshark_source.py`, `fields.py`, `ua_opcode_names.py`) de la
couche CLI (`cli.py`, uniquement `argparse` + orchestration d'appel) :
`cli.py` importe `bridge`/`config`/`sender`/`sdnotify`, jamais l'inverse.
Cette règle n'était vérifiée qu'à la lecture avant ce garde-fou.

`ruff` (règle `I`, tri des imports) ne détecte pas les cycles d'imports —
aucune règle native pour ça. Vérifié à la place par
`tests/test_no_cross_imports.py`, qui reconstruit le graphe réel des
imports internes par analyse `ast` (pas une liste tenue à la main, qui se
désynchroniserait au premier nouvel import) et le valide acyclique par un
parcours en profondeur (couleurs blanc/gris/noir) ; le détecteur lui-même
est d'abord vérifié positivement sur un graphe avec un cycle volontaire,
avant d'être appliqué au graphe réel du projet — même discipline que les
autres garde-fous « preuve que ça détecterait une vraie régression »
(`tests/conftest.py::FakePopen`, `tests/test_docs.py`).

Graphe actuel (aucune dépendance interne pour `config`, `fields`, `hep`,
`stats`, `tshark_source`, `sdnotify`, `ua_opcode_names` — ce sont les
modules « feuilles ») :

```
cli -> {bridge, config, sdnotify, sender}
bridge -> {config, hep, keepalive, normalizer, sender, stats, tshark_source}
normalizer -> {fields, hep, semantics}
semantics -> {fields, ua_opcode_names}
keepalive -> {hep, sender}
sender -> {hep}
```

### Aucun secret écrit sur disque par l'outil lui-même

`config.py` ne fait que lire (`Config.load()`) : il n'existe aucune fonction
de sauvegarde de configuration ou de secret dans le projet. `hep.auth_key`
(seule valeur sensible manipulée, la clé d'authentification HEP passée à
`heplify-server`) ne transite qu'en mémoire, de sa résolution
(CLI/`OXOHEP_HEP_PASS`/TOML) jusqu'au chunk HEP `AUTH_KEY` (0x000E) encodé
par `hep.py` — jamais réécrite dans un fichier par `oxo-hep-bridge` lui-même.
Une valeur passée en argument CLI (`--hep-pass`) reste néanmoins visible
dans l'historique du shell/`ps` : préférer `OXOHEP_HEP_PASS` ou le TOML pour
l'automatisation.

## Format HEPv3

Voir [hep-chunks.md](hep-chunks.md) pour le détail des chunks encodés.

## Nommage protocolaire officiel (`ua_opcode_names.py`)

`src/oxo_hep_bridge/ua_opcode_names.py` fournit des dictionnaires
valeur numérique → libellé officiel pour les opcodes UAUDP, les
classes/méthodes/serveurs/événements/erreurs/propriétés NOE, les opcodes
UA3G (`UA3G_OPCODE_SYS_NAMES`/`UA3G_OPCODE_TERM_NAMES` — deux tables
distinctes selon le sens du message, System→Terminal ou Terminal→Système,
déduit par port via `UAUDP_TERMINAL_DEFAULT_PORTS`), la sous-commande d'un
message UA3G opcode 0x13 « IP Device Routing »
(`UA3G_IP_DEVICE_ROUTING_SYS_NAMES`/`..._CS_NAMES`, champs tshark distincts
`ua3g.ip`/`ua3g.ip.cs` déjà auto-disambiguïsés par sens sans déduction par
port) et les identifiants de paramètre poste des sous-commandes 0x09/0x02
de ce même message (`UA3G_IP_DEVICE_ROUTING_PARAMETER_NAMES`, champs
répétés `ua3g.ip.get_param_req.parameter`/`ua3g.ip.cs.cmd02.parameter` —
une **liste** d'identifiants par message, résolue élément par élément par
`decode_names()` plutôt que `decode_name()`), ainsi que la sous-commande
0x0A « Set Parameters Value » de ce même message
(`UA3G_IP_DEVICE_ROUTING_SET_PARAMETER_NAMES`, champ répété
`ua3g.ip.set_param_req.parameter` — table dédiée et distincte de la
précédente malgré la proximité du nom de champ tshark ; porte elle aussi un
doublement consécutif de chaque identifiant côté dissecteur, comme
`ua3g.ip.cs.cmd02.parameter`, mais ici côté requête système), et la
sous-commande 0x11 « Free Seating » de ce même message
(`UA3G_IP_DEVICE_ROUTING_FREESEATING_PARAMETER_NAMES`, champ répété
`ua3g.ip.freeseating.parameter` — seulement 4 entrées, table dédiée et
distincte des deux précédentes, même motif de doublement consécutif
vérifié sur les fixtures réelles), extraits du
dissecteur Wireshark officiel Alcatel-Lucent Enterprise
(`packet-uaudp.c`/`packet-noe.c`/`packet-ua3g.c`, GPL v2+). `semantics.py`
les utilise via `decode_name()`/`decode_names()`/`annotate_noe_event()`/
`annotate_ua3g_message()` pour ajouter des champs `*_name`/`*_names`
optionnels dans la payload JSON (`uaudp.opcode_name`, `noe[].class_name`,
`ua3g[].opcode_name`, `ua3g[].ip_name`/`ip_cs_name`,
`ua3g[].ip_get_param_req_parameter_names`/`ip_cs_cmd02_parameter_names`/
`ip_set_param_req_parameter_names`/`ip_freeseating_parameter_names`, etc.)
— toujours en plus de la valeur
numérique existante, jamais à sa place, et jamais de nom inventé quand la
valeur n'est pas dans la table (pour un champ répété : liste alignée avec
`None` aux positions non résolvables, jamais un élément simplement
retiré).

**Garde-fou de complétude** (`tests/test_ua3g_ip_device_routing_completeness.py`,
session 38) : vérifie via un vrai `tshark` que toute valeur `ua3g.ip`/
`ua3g.ip.cs`/identifiant de paramètre réellement présente dans
`sample_captures/*.pcap` figure bien dans la table correspondante —
seule exception documentée et tolérée : l'identifiant `0x0C` sur
`ua3g.ip.get_param_req.parameter`/`ua3g.ip.cs.cmd02.parameter`, absent
aussi de la table officielle Wireshark amont (`ip_device_routing_cmd_
get_param_req_vals[]`, qui s'arrête à `0x0B`). Ignoré (skip) si `tshark`
n'est pas disponible, comme `test_real_tshark_integration.py`.

## Mapping métier NOE/UA3G ↔ SIP/HOMER

Voir [noe-ua3g-homer-mapping.md](noe-ua3g-homer-mapping.md), en particulier
le §6bis : le nommage protocolaire ci-dessus est désormais sourcé
officiellement, mais le mapping vers des **événements d'appel SIP**
(INVITE/BYE/...) reste volontairement non codé en dur dans `semantics.py` —
ce dissecteur documente le protocole poste↔OXE, pas la logique applicative
de traduction interne de l'OXE vers SIP, et aucun trafic OXO réel n'est
disponible pour valider cette seconde partie par déduction.

## Limites connues

- **Contenu NOE perdu sur les trames « canal local » (opcode UAUDP 16-23).**
  Sur la capture d'exemple `sample_captures/uaudp_ipv6.pcap`, 163 des 993
  trames uaudp (~16 %, et non ~12 % comme précédemment documenté — chiffre
  recalculé et figé par un test de garde-fou en session 20, voir CHANGELOG)
  portent un opcode ≥ 16 (motif observé : opcode de base
  0-7 **+ bit `0x10`**, `src_port == dst_port == 32640`, cf.
  [noe-ua3g-homer-mapping.md §6ter](noe-ua3g-homer-mapping.md#6ter-opcodes-uaudp-16-23-hypothèse-bit-0x10-à-valider)
  pour l'analyse empirique complète). `packet-uaudp.c` ne documente que les
  opcodes 0-7 (`uaudp_opcode_str[]`) ; au-delà, Wireshark affiche `Opcode:
  Unknown (N)` et **arrête la dissection** — aucune sous-couche `ua`/`noe`
  n'apparaît dans la sortie `tshark -T ek`, alors même que l'octet brut de
  la trame ressemble à un message NOE complet. Conséquence pour
  `oxo-hep-bridge` : ces paquets sont bien transmis à HOMER (le pont ne les
  ignore pas), mais comme une coquille quasi vide — `uaudp.opcode` /
  `uaudp.opcode_name` seuls, sans le contenu `noe[]` associé, puisque
  `extract_noe_events()` dépend entièrement de la couche que tshark produit
  en amont. Ce n'est pas un bug du pont mais une limite du dissecteur
  upstream ; aucun contournement n'est possible côté `oxo-hep-bridge` sans
  redécoder manuellement ce canal (non fait, hors périmètre actuel).
- **Mapping événement d'appel SIP non codé en dur**, volontairement — voir
  section précédente.
- **Corrélation intra-UA uniquement** (pas inter-protocoles UA↔SIP) — voir
  [noe-ua3g-homer-mapping.md §7](noe-ua3g-homer-mapping.md#7-lien-avec-oxo-hep-bridge).
- **Aucune séquence décroché → numérotation → sonnerie exploitable dans les
  captures d'exemple du dépôt.** Les vrais champs UA3G porteurs de cette
  information (`ua3g.unsolicited_msg.hook_status`, `ua3g.digit_dialed.digit_value`,
  `ua3g.key_number`) existent bien côté dissecteur upstream, mais dans les 3
  captures fournies ils sont soit absents, soit observés uniquement lors de
  l'enregistrement du poste au démarrage (`IP Device Routing: Init`), jamais
  lors d'un décroché en cours d'appel — voir
  [ua3g-call-signaling-decroche-numerotation.md](ua3g-call-signaling-decroche-numerotation.md)
  pour le détail par capture et la commande `tshark` à utiliser sur une
  vraie capture d'appel dès qu'elle sera disponible. Constat audité et
  reconfirmé exact contre un vrai `tshark` en session 45 (aucune
  correction nécessaire), désormais protégé par
  `tests/test_real_tshark_integration.py`
  (`test_ua3g_call_signaling_doc_*`) plutôt que documenté seulement en
  prose — même discipline que le §6ter de
  [noe-ua3g-homer-mapping.md](noe-ua3g-homer-mapping.md#6ter-opcodes-uaudp-16-23--hypothèse-bit-0x10-à-valider),
  protégé depuis la session 43.
