# Session 20 — 2026-09-05

### Contexte de la session
`docs/roadmap.md` liste toujours une section « À faire » vide — confirmé
à nouveau par une exécution réelle de la chaîne d'outillage (réseau
disponible dans ce sandbox) : `pytest` 311 passés/1 skip, `mypy` 0 erreur,
`ruff check`/`format --check` 0 violation, couverture 99,42 % — chiffres
identiques aux sessions 17/18/19, aucune régression. Comme lors des trois
sessions précédentes, la session s'est donc portée sur une vérification
empirique des affirmations documentaires existantes plutôt que de rester
sans rien produire, en rejouant le pipeline réel (`TsharkEKSource` +
`FakePopen`, puis `normalizer.normalize()`) sur les fixtures `.ek.ndjson`
existantes.

### Corrigé
- **`docs/architecture.md#limites-connues`, `README.md` et
  `docs/noe-ua3g-homer-mapping.md#6ter` affirmaient qu'~12 % du trafic
  uaudp de la fixture `sample_captures/uaudp_ipv6.pcap` porte un opcode
  UAUDP ≥ 16** (canal local, contenu NOE perdu par le dissecteur Wireshark
  upstream — constat qualitatif toujours exact). Ce chiffre, jamais
  recalculé depuis son estimation initiale (session 16), s'avère faux à un
  comptage réel : en rejouant `TsharkEKSource.iter_packets()` sur
  `tests/fixtures/uaudp_ipv6.ek.ndjson` puis en filtrant sur
  `uaudp_uaudp_opcode`, 163 des 993 trames uaudp de cette capture portent
  effectivement un opcode ≥ 16 (répartition exacte identique au tableau
  déjà présent dans `noe-ua3g-homer-mapping.md#6ter` : 9+6+11+1+24+24+1+87
  = 163), soit ~16,4 %, pas ~12 %. Les trois documents corrigés avec le
  chiffre exact (163/993, ~16 %).

### Ajouté
- 1 nouveau test
  (`tests/test_fields.py::test_uaudp_opcode_16_23_content_loss_matches_documented_figure`),
  1 nouvelle fixture pytest (`uaudp_ipv6_flat_lines` dans `conftest.py`,
  sur le modèle de `ua3g_freeseating_ipv4_flat_lines` déjà existante) :
  fige le compte exact (993 trames uaudp, 163 flaggées opcode ≥ 16,
  aucune ne portant de sous-couche `ua`/`noe`) pour empêcher toute
  nouvelle dérive silencieuse entre la doc et le comportement réel — même
  défaut de méthode que celui déjà corrigé aux sessions 17/18/19 (une
  affirmation documentaire jamais revérifiée empiriquement). 313 tests au
  total (312 passés, 1 skip conditionnel IPv6), couverture 99,4 %
  inchangée (`fields.py` déjà à 100 %).
