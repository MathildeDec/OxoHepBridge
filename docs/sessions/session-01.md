# Session 1 — 2026-08-25 → 2026-08-26

Fusion des trois premières entrées du CHANGELOG d'origine (mise en place
initiale du dépôt sous forme de version `0.1.0`, puis deux suites de
session le lendemain), regroupées ici car antérieures à l'adoption de la
numérotation explicite des sessions à partir de la session 2. Contenu
reproduit tel quel, sans reformulation.

## Version 0.1.0 — 2026-08-25

### Ajouté
- Encodeur/décodeur HEPv3 pur Python (`hep.py`) — tous les chunks obligatoires
  et les chunks optionnels (auth key, correlation ID).
- Source `tshark -T ek` via subprocess, avec parsing des particularités du
  format EK (lignes d'action bulk, préfixage double, NOE en liste).
- Normaliseur UAUDP/UA3G/NOE → `HepPacket`, tolérant aux champs manquants et
  au bruit (paquets DHCP/TFTP ignorés).
- Couche d'envoi UDP injectable, avec `NullSender` pour le mode dry-run.
- Mode capture live (`--interface`) et relecture hors-ligne (`--pcap`).
- Option `--decode-as` pour forcer le décodage des protocoles sur les ports
  non standards (nécessaire sur `uaudp_ipv6.pcap`).
- 33 tests automatisés avec `FakePopen` et fixtures issues des captures
  officielles Wireshark — aucun tshark requis pour exécuter la suite de tests.
- Script d'installation multi-distribution (Debian/Ubuntu via apt,
  Rocky/RHEL 9 via dnf + EPEL).
- Configuration via variables d'environnement (préfixe `OXOHEP_`).
- Fichier d'unité systemd avec capacités ciblées (`CAP_NET_RAW`).

---

## Suite de session — 2026-08-25

### Ajouté
- Payload sémantique structuré (`semantics.py`) : champs UAUDP (opcode, sntseq,
  expseq), endpoints (IP+port), métriques QoS extraites sur les paquets opcode 0
  (version, window_size, mtu, qos_ip_tos...), événements NOE (nettoyage du
  double préfixe `noe_noe_`), champs bruts sélectionnés (`raw_selected`).
- Corrélation stateless canonicalisée (`fields.build_correlation_id`) :
  A→B et B→A produisent désormais le même identifiant (endpoints triés).
- Chunk HEP `node_name` (0x0013) : configurable via TOML (`hep.node_name`),
  variable d'environnement `OXOHEP_NODE_NAME`, ou `--node-name` en CLI.
- Harnais de réception HEPv3 standalone (`tools/hep_receiver.py`) : écoute
  UDP, décode avec le même `decode()` que l'encodeur, sortie JSONL. Valide
  l'encodage de bout en bout sans instance HOMER réelle.
- Observabilité minimale (`stats.py`) : dataclass `Stats` (reçus, normalisés,
  envoyés, ignorés, erreurs d'envoi/normalisation/tshark, taux de succès) et
  journal de synthèse en fin de run, détaillé automatiquement si des erreurs
  sont détectées.
- `Sender.send()` retourne désormais un bool (succès/échec), capturé par le
  bridge pour alimenter les compteurs sans faire crasher le run sur une
  erreur réseau isolée.
- `Bridge.run()` capture `TsharkError` et les exceptions inattendues de
  `normalize()` sans interrompre le traitement des paquets suivants.
- Nouveaux tests couvrant les ajouts ci-dessus (payload sémantique, corrélation
  canonicalisée, node_name, stats, intégration bridge avec sender défaillant,
  décodage IPv4/IPv6 du harnais de réception) — 60 tests au total, stables
  sur exécutions répétées.

### Non fait sciemment (dépend d'une instance HOMER ou d'un trafic OXO réel)
- Keepalive HEP périodique, intégration Docker HOMER/heplify-server,
  mapping métier complet des opcodes, corrélation d'appel avec état partagé.

---

## Suite de session — 2026-08-26

### Ajouté
- Keepalive HEP périodique (`keepalive.py`) : en capture live, un
  `KeepaliveScheduler` envoie sur un thread de fond, toutes les
  `hep.keepalive_interval` secondes, un `HepPacket` de signalement de vie
  (chunk `KEEPALIVE_TIMER` 0x000D + payload JSON `{"type":"keepalive",...}`),
  via le même `Sender` que le trafic normal (respecte `--dry-run`). Réglable
  via `--keepalive-interval`, `OXOHEP_KEEPALIVE_INTERVAL` ou
  `[hep].keepalive_interval` en TOML ; désactivé par défaut (`0`). N'est
  jamais démarré en relecture `--pcap` (le run se termine avant tout
  intervalle utile).
- `hep.py` : le chunk générique `KEEPALIVE_TIMER` (0x000D), prévu par la spec
  HEPv3 mais jusqu'ici inutilisé, est désormais encodable via le nouveau champ
  `HepPacket.keepalive_timer`.
- 9 nouveaux tests (`test_keepalive.py`) couvrant la structure du paquet
  keepalive, le déclenchement périodique et l'arrêt propre du scheduler, la
  non-activation en mode pcap, et l'intégration dans `Bridge` — 69 tests au
  total.
- Documentation : section « Keepalive HEP périodique » dans
  `docs/architecture.md`, chunks 0x000D/0x0013 documentés et section
  « Paquet keepalive » ajoutées dans `docs/hep-chunks.md`, option
  `--keepalive-interval` documentée dans le README et le TOML d'exemple.

### Non fait sciemment (dépend d'une instance HOMER ou d'un trafic OXO réel)
- Intégration Docker HOMER/heplify-server, mapping métier complet des
  opcodes, corrélation d'appel avec état partagé.
