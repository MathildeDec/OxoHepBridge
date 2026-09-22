# Session 16 — 2026-08-29

### Contexte de la session
`docs/roadmap.md` ne liste toujours aucune feature réalisable sans
dépendance externe (instance HOMER réelle, trafic OXO réel), et
l'environnement de cette session n'avait pas accès aux outils de test
(`pytest`/`mypy`/`ruff` non installables, réseau restreint) — pas de code
de production ajouté par prudence. Session **documentation uniquement**,
axée sur un constat qui restait enterré dans un document exploratoire.

### Corrigé
- `docs/ua3g-call-signaling-decroche-numerotation.md` : caractère parasite
  (`問題`, probablement une mauvaise encodage lors d'une session
  précédente) remplacé par le texte français prévu (« nécessite
  `--decode-as` »).

### Ajouté
- Nouvelle section « Limites connues » dans `docs/architecture.md` : remonte
  explicitement le constat empirique du §6ter de
  `noe-ua3g-homer-mapping.md` (perte de contenu NOE sur ~12 % du trafic
  uaudp de la capture d'exemple `uaudp_ipv6.pcap`, opcodes UAUDP ≥ 16 non
  documentés par le dissecteur Wireshark upstream) — jusqu'ici visible
  uniquement dans un document exploratoire dédié au mapping SIP/HOMER, pas
  à l'endroit où un opérateur du pont chercherait les limites connues.
  Rappel bref des deux autres limites déjà documentées ailleurs (mapping
  événement d'appel SIP non codé en dur, corrélation intra-UA uniquement).
- Lien depuis le README vers cette nouvelle section.
- 2 nouveaux tests (`tests/test_docs.py`) : garde-fou pour que cette section
  ne redevienne pas orpheline (présence dans `architecture.md`, lien depuis
  le README) — 308 tests au total (non exécutés dans cette session faute
  d'outillage, voir « Contexte » ci-dessus ; vérifiés manuellement par
  rejeu des assertions en Python pur, syntaxe validée par `py_compile`).

### Non fait sciemment (inchangé — dépend d'une instance HOMER ou d'un trafic OXO réel)
- Intégration Docker HOMER/heplify-server, mapping métier complet des
  opcodes, corrélation d'appel avec état partagé (inter-protocoles UA↔SIP).
