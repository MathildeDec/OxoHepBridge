# Session 4 — 2026-08-26

### Ajouté
- Résolution IPv4/IPv6/DNS de `--hep-host` (`sender.py`) : `UDPSender`
  ouvrait jusqu'ici systématiquement une socket `AF_INET`, ce qui faisait
  échouer silencieusement (`OSError: Address family not supported by
  protocol`, comptée comme simple erreur d'envoi) tout envoi vers un
  collecteur HOMER/heplify-server désigné par une adresse IPv6 littérale.
  La famille de socket (`AF_INET`/`AF_INET6`) et le `sockaddr` de
  destination sont désormais résolus via `socket.getaddrinfo()` au premier
  envoi — couvre uniformément littéral IPv4, littéral IPv6 (zone id
  compris) et nom d'hôte DNS. En cas d'échec de résolution ou d'envoi, la
  socket est refermée et la résolution retentée au prochain paquet (utile
  en cas de bascule DNS ou de panne réseau transitoire), plutôt que de
  rester figée sur une adresse invalide pour tout le run.
- 7 nouveaux tests (`test_sender.py`, nouveau fichier — le sender n'avait
  jusqu'ici que des tests indirects via `test_bridge.py`) : résolution
  IPv4 littéral, IPv6 littéral, résolution DNS mockée, échec de résolution,
  échec d'envoi avec réinitialisation de la socket, idempotence de
  `close()`, respect du mode `--dry-run` par `make_sender()`. Le test IPv6
  littéral se `skip` proprement si l'environnement d'exécution n'a pas
  l'IPv6 disponible au niveau noyau (détecté par tentative réelle
  d'ouverture d'une socket `AF_INET6`, pas seulement `socket.has_ipv6`) —
  85 tests au total (1 skip possible selon l'environnement).
- Documentation : section « Résolution du collecteur HEP : IPv4, IPv6, DNS »
  dans `docs/architecture.md` ; description de `--hep-host` et de
  `sender.py` mises à jour dans le README ; diagramme d'architecture annoté
  IPv4/IPv6.

### Non fait sciemment (inchangé — dépend d'une instance HOMER ou d'un trafic OXO réel)
- Intégration Docker HOMER/heplify-server, mapping métier complet des
  opcodes (raison documentée dans `docs/noe-ua3g-homer-mapping.md`),
  corrélation d'appel avec état partagé (inter-protocoles UA↔SIP).
