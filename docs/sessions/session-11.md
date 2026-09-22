# Session 11 — 2026-08-28

### Ajouté
- **Notification systemd (`sd_notify`) et watchdog** (`sdnotify.py`,
  nouveau module) : sans elle, `systemctl status` ne peut pas distinguer un
  pont qui fonctionne normalement d'un pont dont le thread de lecture
  tshark s'est bloqué en silence — le process reste vivant, le service
  reste marqué actif indéfiniment sans aucun signal de santé applicative.
  Implémenté sans dépendance à `libsystemd` ni au paquet PyPI `sdnotify`
  (seul `socket.AF_UNIX` de la bibliothèque standard, dans le même esprit
  « pas de dépendance lourde » que le reste du projet) :
  - `SdNotifier` envoie `READY=1`, `STOPPING=1`, `WATCHDOG=1` et
    `STATUS=...` sur la socket Unix `NOTIFY_SOCKET` (chemin filesystem ou
    espace de noms abstrait Linux `@...`) ; no-op silencieux si
    `NOTIFY_SOCKET` n'est pas définie (hors service systemd) — permet à
    `cli.py` d'appeler `ready()`/`stopping()` inconditionnellement.
  - `cli.main()` envoie `READY=1` juste avant `bridge.run()` (config
    validée, `Bridge` construit avec succès) et `STOPPING=1` dans le
    `finally` qui entoure `bridge.run()`, donc sur les trois chemins de
    sortie (retour normal, arrêt par SIGINT/SIGTERM, exception fatale).
  - `WatchdogScheduler` (même style que `KeepaliveScheduler` : thread
    daemon, `threading.Event`, `start()`/`stop()` idempotents) envoie
    `WATCHDOG=1` à la moitié de l'intervalle annoncé par systemd
    (`WATCHDOG_USEC`, dérivé de `WatchdogSec=` côté unité — marge de
    sécurité recommandée par `sd_notify(3)`). `resolve_watchdog_interval()`
    lit `WATCHDOG_USEC`/`WATCHDOG_PID` (ce dernier vérifié contre le PID
    courant). Watchdog désactivé (comportement historique inchangé) si
    `WatchdogSec=` n'est pas configuré côté unité — exactement comme
    `keepalive_interval = 0` désactive le keepalive HEP.
  - **Portée volontairement limitée, documentée explicitement** (même
    esprit que l'avertissement sur `--hep-compress-payload`) : le ping
    watchdog est un timer indépendant, pas un heartbeat asservi à la
    progression réelle de `Bridge.run()` — détecte un process figé ou
    disparu (déjà couvert par `Restart=on-failure`), pas un appel réseau
    individuellement bloqué (`send()` qui ne revient jamais). Un heartbeat
    asservi à la boucle de lecture a été écarté : il resterait aussi
    silencieux pendant une période creuse légitime (pas de trafic OXO),
    au risque de redémarrer un pont parfaitement sain mais inactif.
  - `systemd/oxo-hep-bridge.service` : `Type=simple` → `Type=notify`
    (systemd attend `READY=1` avant de considérer le service démarré) ;
    `WatchdogSec=30` ajouté en commentaire, opt-in explicite.
- 23 nouveaux tests : `test_sdnotify.py` (nouveau fichier, 17 tests —
  `SdNotifier` sur une vraie socket Unix locale au test, filesystem et
  espace de noms abstrait, tolérance à un chemin de socket invalide,
  `resolve_watchdog_interval()` sur tous les cas WATCHDOG_USEC/PID,
  déclenchement périodique et arrêt propre de `WatchdogScheduler`),
  `test_cli_sdnotify.py` (nouveau fichier, 6 tests — séquence `READY=1`
  puis `STOPPING=1` sur run normal/SIGINT-SIGTERM/exception fatale, silence
  total sans `NOTIFY_SOCKET`, ping watchdog effectif sur un run assez long,
  non-régression de la restauration des handlers de signal) — 213 tests au
  total (1 skip conditionnel selon la disponibilité IPv6, inchangé).
- Documentation à jour : `README.md` (puce de fonctionnalités, entrée dans
  la liste des modules, section « Déploiement systemd » détaillant
  `Type=notify` et l'activation optionnelle du watchdog),
  `docs/architecture.md` (nouvelle section détaillant le raisonnement, ce
  que le watchdog détecte et ce qu'il ne détecte pas), `docs/roadmap.md`
  (item déplacé de « à faire » vers « fait »).
