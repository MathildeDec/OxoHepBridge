# Session 14 — 2026-08-28

### Contexte de la session
Analyse empirique des 3 captures d'exemple du projet, rejouées via
`oxo-hep-bridge` + `tools/hep_receiver.py` (sans instance HOMER réelle,
build du binaire Go HOMER11 non praticable dans l'environnement d'analyse —
toolchain Go 1.27 inaccessible). Objectif : vérifier de bout en bout que
la payload JSON produite correspond bien à ce que documente
`docs/noe-ua3g-homer-mapping.md`.

### Corrigé
- **`decode_name()` (`ua_opcode_names.py`) ne résolvait jamais
  `server_name` ni `property_name`.** Cause : `int(value)` en base 10,
  alors que tshark rend les champs `server`/`property`/`objectid` du
  dissecteur `packet-noe.c` en **hexadécimal préfixé** (`"0x15"`,
  `"0x28"`), contrairement à `class`/`method`/`event` rendus en décimal
  (`"128"`, `"2"`). `int("0x15")` lève `ValueError`, silencieusement
  absorbé par le `try/except` existant → `server_name`/`property_name`
  jamais ajoutés, même quand la table contenait l'entrée correspondante.
  Fix : `int(value, 0)` (détection automatique de base) pour les chaînes.
  Vérifié par recoupement sur `ua3g_freeseating_ipv4.pcap` +
  `ua3g_freeseating_ipv6.pcap` (503 événements NOE) : `server_name` passe
  de 0/503 à 503/503 résolus (`"Call Server"`), `property_name` de 0/426
  à 426/426 résolus sur les événements portant effectivement un champ
  `property` (les 77 événements restants — `Create`/`Delete`/`Notify`
  sans propriété — n'en ont simplement pas). Tests existants
  (`tests/test_ua_opcode_names.py`) inchangés, toujours verts — aucun ne
  couvrait le cas hexadécimal.

### Ajouté (documentation)
- `docs/noe-ua3g-homer-mapping.md` §6ter : hypothèse (non officielle, à
  valider) sur les opcodes UAUDP 16-23 observés dans
  `sample_captures/uaudp_ipv6.pcap` — motif `opcode = base (0-7) + 0x10`,
  sur un canal local distinct (`src_port==dst_port==32640`), avec des
  cadences très régulières (~158,5 s pour Connect+flag, ~15,1 s pour
  Keepalive+flag). Ces opcodes ne sont pas dans `uaudp_opcode_str[]`
  (Wireshark natif affiche `Opcode: Unknown`) — noté explicitement comme
  ne devant pas être codé en dur tant que non confirmé par une source
  officielle. Point notable : les trames `Data+0x10` (opcode 23) portent
  des octets ressemblant à un message NOE complet, mais Wireshark arrête
  la dissection à l'opcode inconnu — `extract_noe_events()` ne voit donc
  rien pour ces paquets (limite du dissecteur upstream, pas du pont).
