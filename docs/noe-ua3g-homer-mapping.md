# Intégration NOE/UA3G (Alcatel-Lucent) ↔ HOMER — Synthèse

> **Note de contexte projet** — Ce document est une synthèse exploratoire
> produite pour évaluer la faisabilité d'un mapping métier complet des
> opcodes UAUDP/NOE. Conclusion (§1-6, écrite avant qu'une source officielle
> ALE soit disponible) : **aucun mapping opcode → événement d'appel SIP
> fiable ne peut être codé en dur** sans trafic OXO réel. Cette conclusion
> reste vraie pour le mapping **vers des événements d'appel SIP**
> (INVITE/BYE/...) — voir **§6bis** pour une mise à jour importante : le
> **nommage protocolaire** (opcode/classe/méthode/événement → libellé
> officiel, sans lien avec SIP) est, lui, désormais sourcé et implémenté
> dans `oxo-hep-bridge`, suite à la fourniture du dissecteur Wireshark
> officiel Alcatel-Lucent Enterprise. Ne pas confondre les deux — la
> nuance est expliquée en détail en §6bis. Le lien avec le code actuel de
> `oxo-hep-bridge` est fait en fin de document (§7).

## Contexte

Question initiale : peut-on établir un mapping entre les champs des protocoles propriétaires Alcatel-Lucent **NOE** et **UA3G** (signalisation poste ↔ OmniPCX Enterprise) et le monde **HOMER** (capture/monitoring SIP, VoIP, RTC).

---

## 1. Constat de départ

- **HOMER** repose sur le protocole **HEP** (Homer Encapsulation Protocol), conçu pour transporter du **SIP/RTP/RTCP** ainsi que des logs/CDR génériques.
- **NOE** et **UA3G** sont des protocoles **propriétaires Alcatel-Lucent Enterprise**, utilisés entre les postes IP et le serveur d'appel **OmniPCX Enterprise (OXE)**. Ils n'ont de dissecteur que côté **Wireshark**, pas côté HOMER.
- **Conclusion** : il n'existe **aucun mapping officiel** publié par Alcatel-Lucent ou par le projet sipcapture/HOMER entre ces deux mondes.

---

## 2. Où se fait réellement la "traduction"

Il n'y a pas de passerelle réseau qui convertit paquet par paquet du NOE/UA3G vers du SIP. La traduction est **applicative**, faite par l'**OXE** lui-même :

- **Côté poste** : le téléphone IP Alcatel parle NOE/UA3G avec l'OXE (décroché, touches, écran, audio local).
- **Côté réseau** : l'OXE parle SIP (ou H.323, QSIG, ISDN) vers l'extérieur via ses **SIP Trunks**.

⚠️ Ce n'est pas une conversion 1:1 transparente : certaines fonctionnalités (ex. MWI) ne se propagent pas correctement d'un monde à l'autre car les protocoles ne sont pas réellement équivalents (cas documenté dans l'interop Cisco UCM ↔ OmniPCX).

---

## 3. Mapping conceptuel (construit par déduction — non officiel)

Utile uniquement au niveau **événements d'appel de haut niveau** :

| Événement métier | Champ NOE/UA3G source | Message SIP correspondant | Où dans HOMER |
|---|---|---|---|
| Décrochage poste | `ua3g.special_key.hookswitch_status`, `noe.event` | `INVITE` sortant | Call-Flow, méthode INVITE |
| Raccroché | `ua3g.special_key.hookswitch_status` | `BYE` | méthode BYE |
| Sonnerie déclenchée | `ua3g.command.ring` | `180 Ringing` | code réponse 180 |
| Prise de ligne / réponse | `ua3g.command.audio_config` | `200 OK` | code réponse 200 |
| Numérotation (touche) | `ua3g.digit_dialed.digit_value` | `INFO` (DTMF) ou digits dans INVITE | méthode INFO |
| Mise en attente / transfert | `noe.event`, `noe.method` | `re-INVITE`, `REFER` | méthode REFER / re-INVITE |
| Message en attente (MWI) | `noe.property` | `NOTIFY` (peu fiable en interop) | méthode NOTIFY |
| Erreur / échec | `noe.errcode` | `4xx/5xx` SIP | code réponse SIP |
| État du poste | `noe.event_device_presence.state` | `REGISTER` / `200 OK` | méthode REGISTER |
| Volume / config audio poste | `ua3g.command.audio_config.*` | **aucun équivalent** | non visible |
| LED / écran / touches | `ua3g.command.led`, `ua3g.command.lcd_line` | **aucun équivalent** | non visible |

Une grande partie des champs UA3G (audio, LED, LCD, beep) sont **purement locaux au terminal** et ne se traduisent en rien côté SIP/HOMER.

---

## 4. Deux scénarios d'usage pratiques

**A. Voir simplement les appels (recommandé, simple)**
→ Positionner la sonde de capture (HEPlify/CaptAgent) sur les **trunks SIP de l'OXE**. HOMER fonctionne alors nativement, sans aucun mapping — l'OXE a déjà fait la traduction.

**B. Corréler comportement poste (NOE/UA3G) et appel SIP**
→ Nécessite de capturer les deux flux séparément (dissecteurs Wireshark), puis de les **corréler manuellement** (horodatage, numéro de poste). HOMER ne fait pas cette corrélation nativement — à implémenter en amont et injecter en événement custom via HEP.

---

## 5. Qualité de la voix — bonne nouvelle

La qualité voix **ne dépend pas** du protocole de signalisation (NOE ou SIP), mais du flux **RTP/RTCP**, standard des deux côtés.

### Principe
- **RTP** = paquets audio eux-mêmes
- **RTCP** = rapports périodiques (RR/SR) décrivant la réception du flux

### Métriques HOMER
| Rapport RTCP | Contenu | Métrique HOMER |
|---|---|---|
| RR (Receiver Report) | Fraction/perte cumulée, jitter | Packet loss %, jitter |
| SR (Sender Report) | Timestamp NTP, compteurs | RTT (combiné avec RR) |
| RTCP-XR (si supporté) | Burst/gap loss, R-factor, MOS-LQ/CQ | MOS plus précis |

Sans RTCP-XR, HOMER estime le MOS via l'algorithme **E-model (ITU-T G.107)** à partir de la perte, du jitter et du codec utilisé.

### Point clé
Le flux RTP/RTCP entre poste et OXE (ou OXE et trunk) est **standard**, indépendant de NOE/UA3G. Si la sonde capture ce flux, **HOMER fonctionne sans aucun mapping**.

---

## 6. Bilan — ce qui est acquis vs ce qui reste ouvert

### Acquis
- NOE/UA3G non compris nativement par HOMER — pas de mapping officiel existant
- L'OXE est le point de traduction signalisation poste ↔ SIP trunk
- Mapping conceptuel des événements haut niveau (construit par déduction)
- La qualité voix (RTP/RTCP) est indépendante de NOE/UA3G → zéro mapping nécessaire

### Ouvert / à valider
1. **Positionnement de la sonde de capture** (LAN poste vs lien OXE↔trunk) — non tranché, dépend de l'architecture réelle
2. **RTCP activé** sur l'OXE et les postes ? — à vérifier en configuration réelle
3. **Support RTCP-XR par l'OXE** ? — non confirmé, impacte la précision du MOS
4. **Corrélation appel NOE ↔ flux RTP** (quel `objectid` NOE correspond à quel Call-ID SIP) — non résolu, demande du développement
5. Le tableau de mapping (section 3) est une **construction logique**, pas un document Alcatel officiel — à valider avec la documentation technique OXE ou le support ALE si utilisation formelle nécessaire

---

## 6bis. Mise à jour — nommage protocolaire désormais sourcé

> Ajouté dans une session ultérieure à la synthèse initiale ci-dessus
> (§1-6), suite à la fourniture du code source du dissecteur Wireshark
> officiel pour UAUDP/NOE. Le constat du §6 point 5 (« aucun document
> Alcatel officiel ») est **partiellement obsolète** : voir la nuance
> ci-dessous, importante à ne pas manquer.

### Ce qui a changé

Le dissecteur Wireshark upstream pour UAUDP/NOE (`packet-uaudp.c`,
`packet-noe.c`) est écrit et maintenu par un développeur Alcatel-Lucent
Enterprise (Lars Ruoff, adresse `@alcatel-lucent.com` dans le copyright),
publié sous GPL v2+. Ce n'est pas une fuite ni une rétro-ingénierie tierce :
c'est le code que l'éditeur du protocole a lui-même contribué à un projet
open-source pour que Wireshark sache dissecter son propre protocole
propriétaire. À ce titre, les tables `value_string` qu'il contient (opcode
UAUDP → nom, classe/méthode/serveur/événement/erreur/propriété NOE → nom)
constituent une **source officielle exploitable**, chose absente lors de la
rédaction initiale de ce document.

`oxo-hep-bridge` a intégré ces tables (`src/oxo_hep_bridge/ua_opcode_names.py`,
voir CHANGELOG) et enrichit désormais la payload JSON de champs `*_name`
optionnels : `uaudp.opcode_name`, et par événement NOE `class_name`,
`method_name`, `server_name`, `event_name`, `errcode_name`, `property_name`.
Vérifié par recoupement avec les captures d'exemple réelles du projet — pas
seulement par lecture du source (voir CHANGELOG pour le détail des valeurs
recoupées).

### Ce qui n'a PAS changé — la distinction reste importante

Cette source officielle documente le **protocole** (quel est le nom de
l'opcode 7, de la classe 128...), pas la **sémantique d'un appel
téléphonique** au sens SIP. Concrètement :

- `EVT_ONHOOK`/`EVT_OFFHOOK` (désormais des noms officiels, pas déduits)
  sont des événements **combiné du poste** (décroché/raccroché
  physiquement), au niveau du dissecteur NOE. Ce n'est pas la même chose
  qu'un `INVITE`/`BYE` SIP : le tableau du §3 reliant les deux reste une
  **lecture de correspondance conceptuelle construite par déduction**, pas
  un fait documenté par cette source.
- Rien dans `packet-uaudp.c`/`packet-noe.c` ne documente comment ni quand
  l'OXE traduit un `EVT_OFFHOOK` poste en `INVITE` SIP sortant (temporisation,
  conditions, quel `objectid` NOE correspond à quel `Call-ID` SIP). Ces
  fichiers dissectent le protocole **poste ↔ OXE**, pas la logique
  applicative interne de l'OXE qui fait le pont vers le monde SIP.
- Le point ouvert §6.4 (corrélation appel NOE ↔ flux RTP/Call-ID SIP) reste
  donc entier : aucun élément de cette mise à jour ne le résout. Voir aussi
  `docs/roadmap.md`, où l'item est maintenant scindé explicitement entre
  « nommage protocolaire » (fait) et « mapping événement d'appel » (toujours
  reporté).
- Le fichier `packet-ua3g.c` (le protocole "sous-jacent" transportant NOE,
  incluant audio/LED/LCD/touches) n'a volontairement pas été traité de la
  même façon : plus de 4500 lignes sans table `value_string` unique
  facilement extractible avec le même niveau de confiance — voir CHANGELOG.

En résumé : **avant** cette mise à jour, un `noe.class == 128` était un
entier opaque. **Après**, on sait que c'est une `"FrameBox"` — un fait
protocolaire vérifiable. On ne sait toujours pas dire, sans trafic OXO réel,
qu'une séquence de `SetProperty` sur des `FrameBox` correspond à tel
événement de l'écran d'un appel en cours — ça reste une interprétation
humaine à faire au cas par cas dans HOMER, pas un fait à coder en dur.

---

## 6ter. Opcodes UAUDP 16-23 — hypothèse « bit 0x10 » (à valider)

> Ajouté suite à une analyse empirique des captures d'exemple du projet
> (`sample_captures/uaudp_ipv6.pcap`, rejouée via `oxo-hep-bridge` +
> `tools/hep_receiver.py`, sans instance HOMER réelle — voir CHANGELOG).
> **Ce n'est pas une source officielle** (contrairement au §6bis) :
> `packet-uaudp.c` ne documente que les opcodes 0-7
> (`uaudp_opcode_str[]`) ; Wireshark affiche lui-même `Opcode: Unknown
> (23)` pour toute valeur ≥ 8, y compris en display natif (`tshark -V`).
> Ce qui suit est une lecture par déduction sur trafic réel, à confirmer
> si un jour du trafic OXO en production ou une doc technique OXE devient
> disponible.

### Le motif

Sur `uaudp_ipv6.pcap`, les opcodes 16 à 23 correspondent systématiquement
à un opcode de base 0-7 **plus le bit `0x10`** :

| Opcode brut | = base + 0x10 | Occurrences | Rythmique observée |
|---|---|---|---|
| 16 / 17 | Connect (0) / Connect ACK (1) | 9 / 6 | Rafale de 2-3 échanges, répétée toutes les **~158,5 s** quasi pile (33.0s → 191.4s → 350.0s) |
| 18 / 19 | Release (2) / Release ACK (3) | 11 / 1 | 18 apparaît **seul** la plupart du temps, à intervalles irréguliers (~20-30s) ; payload fixe `12 00 02` + zéros |
| 20 / 21 | Keepalive (4) / Keepalive ACK (5) | 24 / 24 | Toujours en **paire immédiate** (~3,5 ms d'écart), rythme régulier **~15,1 s** — plus lent que le keepalive normal (opcode 4/5, ~5-10 s) |
| 22 | NACK (6) | 1 | Occurrence unique, juste après une rafale 16/17 |
| 23 | Data (7) | 87 | Le plus fréquent, en petites rafales de 3-4, toujours accolé à des échanges Data(7) normaux |

> **Colonnes « Occurrences » et « Rythmique » protégées par des tests de
> garde-fou depuis la session 43** (`tests/test_fields.py`,
> `test_uaudp_opcode_16_23_per_opcode_breakdown_matches_documented_table`,
> `test_uaudp_opcode_16_burst_rhythm_matches_documented_timing`,
> `test_uaudp_opcode_20_rhythm_matches_documented_timing`) — seul le total
> agrégé (163/993, section suivante) l'était jusqu'ici, depuis la
> session 20. Trouvé et corrigé lors d'un audit documentaire (backlog
> `docs/roadmap.md` vide, voir `docs/session-protocol.md`) : ce détail par
> opcode, contrairement au total, n'avait jamais été protégé — un
> recomptage réel en session 43 confirme exactement les valeurs
> ci-dessus, sans aucune dérive. Les rythmes de la ligne 18/19 (irrégulier)
> et l'écart en millisecondes de la ligne 20/21 ne sont volontairement pas
> figés par un test : trop variables pour une assertion stricte utile,
> contrairement aux deux rythmes ci-dessus (quasi constants sur
> l'ensemble des occurrences).

Toutes ces trames « flaggées » ont pour particularité `src_port ==
dst_port == 32640` (contrairement aux Data normales, échangées entre
32513 et 32640) — cohérent avec un **canal local distinct** (supervision
/ transport interne du poste), séparé du canal de signalisation
poste ↔ OXE proprement dit.

### Hypothèse

Le bit `0x10` ne semble **pas** signaler une retransmission classique
(pas de réutilisation de `sntseq`/`expseq`, ces champs sont d'ailleurs
absents sur ces trames). La régularité très marquée des cadences (158,5 s
pour Connect+flag, 15,1 s pour Keepalive+flag) suggère plutôt un
**second niveau de heartbeat/resynchronisation**, tournant en parallèle
du canal principal, sur un port en boucle locale (32640↔32640) — par
exemple entre le pilote UAUDP du poste et une couche système/supervision
interne, indépendamment du canal de signalisation d'appel vers l'OXE.

### Perte de contenu constatée (important pour `oxo-hep-bridge`)

Les trames opcode 23 (`Data+0x10`) contiennent, en octets bruts après
l'opcode, une structure qui ressemble fortement à un message NOE normal
(ex. trame 18 : `17 00 02 02 5f 01 28 04 00 15 04 02 33` — motifs `28`
= tag de propriété, `00 15` = serveur `0x15`, cohérents avec les champs
NOE vus ailleurs dans ce document). **Mais** Wireshark arrête la
dissection dès qu'il rencontre un opcode UAUDP inconnu (`Opcode: Unknown
(23)`) : aucune sous-couche `ua`/`noe` n'est produite dans la sortie
`tshark -T ek`. Conséquence directe : `oxo-hep-bridge` transmet bien le
paquet (avec `uaudp.opcode: "23"`), mais **sans aucun contenu NOE
associé** (`extract_noe_events` ne trouve rien à extraire, puisqu'il
dépend entièrement de la couche `ua`/`noe` produite par tshark). Ce n'est
pas un bug du pont — c'est une limite du dissecteur upstream — mais ça
signifie que 163 des 993 trames uaudp de cette capture d'exemple (~16 %,
chiffre recompté en session 20 — l'estimation initiale de ~12 % de cette
section n'avait jamais été revérifiée par un comptage réel, voir
CHANGELOG) sont actuellement transmises à HOMER comme une coquille quasi
vide
(`opcode`/`opcode_name: null` uniquement), alors que le paquet porte
probablement un événement NOE complet.

---

## 7. Lien avec `oxo-hep-bridge`

Ce que ce constat change concrètement pour le pont :

- **Scénario A (voir les appels)** ne concerne pas `oxo-hep-bridge` : il ne
  capture pas les trunks SIP de l'OXE, seulement le trafic UA/UAUDP/UA3G/NOE
  côté poste (`--bpf "udp port 32640"`, `--decode-as udp.port==32640,uaudp`).
  Pour ce scénario, une sonde HEP classique (heplify côté trunk SIP) suffit
  et ne nécessite aucun changement dans ce projet.
- **Scénario B (corréler poste et appel SIP)** est l'usage visé par
  `oxo-hep-bridge` : `semantics.py` extrait les champs UAUDP scalaires bruts
  (`opcode`, `sntseq`, `expseq`...) et les événements NOE (`objectid`,
  `class`, `method`, `property`...) **et**, depuis §6bis, leur libellé
  protocolaire officiel quand résolvable (`opcode_name`, `class_name`,
  `method_name`...) — toujours sans leur attribuer de sens **métier
  d'appel SIP**, voir le commentaire en tête de `semantics.py`. Le tableau
  du §3 ci-dessus reste une piste de lecture pour un humain analysant la
  payload JSON dans HOMER, **pas** un mapping à coder en dur : la
  correspondance `objectid` NOE ↔ `Call-ID` SIP (point ouvert §6.4) reste à
  faire manuellement ou via un enrichissement applicatif externe.
- La corrélation stateless déjà en place (`fields.build_correlation_id`,
  chunk HEP `correlation_id`) ne résout que la corrélation **intra-UA**
  (A→B / B→A d'un même flux UDP capturé par ce pont) — pas la corrélation
  **inter-protocoles** (UA ↔ SIP) décrite au §4.B, qui reste hors du
  périmètre technique actuel.
- Conséquence sur le suivi projet : l'item est désormais scindé dans le
  CHANGELOG/`docs/roadmap.md` entre **nommage protocolaire** (fait, cette
  session, sourcé depuis le dissecteur Wireshark officiel ALE) et
  **mapping événement d'appel SIP** (toujours « non fait sciemment » —
  aucun trafic OXO réel pour valider la corrélation par déduction).

---

*Document généré à partir d'un échange conversationnel — sources initiales (§1-6) : Wireshark Display Filter Reference (NOE/UA3G), documentation GitHub sipcapture/homer, documentation interop Cisco UCM/OmniPCX, fiches techniques Alcatel-Lucent Enterprise OmniPCX Enterprise. Source ajoutée en §6bis : code source du dissecteur Wireshark officiel `packet-uaudp.c`/`packet-noe.c` (copyright Alcatel-Lucent Enterprise, Lars Ruoff, upstream Wireshark, GPL v2+), fourni par l'utilisateur du projet.*
