# Session 3 — 2026-08-26

### Ajouté
- Arrêt propre sur `SIGTERM` en plus de `SIGINT` (`cli.py`) : `systemctl
  stop`/un redémarrage du service systemd envoie `SIGTERM` par défaut (pas
  `SIGINT`), or seul Ctrl-C déclenchait jusqu'ici la fermeture propre du
  subprocess tshark, de la socket UDP et du thread de keepalive, ainsi que
  le résumé de stats de fin de run. Les deux signaux partagent désormais le
  même handler, qui lève `KeyboardInterrupt` ; les handlers d'origine sont
  restaurés dans tous les cas (arrêt propre, exception inattendue).
- 5 nouveaux tests (`test_signal_handling.py`) : handler identique installé
  pour `SIGINT`/`SIGTERM` pendant `run()`, le handler lève bien
  `KeyboardInterrupt`, code de retour `130` sur arrêt par signal, et
  restauration des handlers d'origine — y compris après une exception fatale
  non liée à un signal — 78 tests au total.
- Documentation : section « Arrêt propre : SIGINT et SIGTERM » dans
  `docs/architecture.md` ; bullet dédié dans le README.

### Non fait sciemment (inchangé — dépend d'une instance HOMER ou d'un trafic OXO réel)
- Intégration Docker HOMER/heplify-server, mapping métier complet des
  opcodes (raison documentée dans `docs/noe-ua3g-homer-mapping.md`),
  corrélation d'appel avec état partagé (inter-protocoles UA↔SIP).
