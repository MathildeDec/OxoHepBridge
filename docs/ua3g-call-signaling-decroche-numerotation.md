# UA3G — Décroché / numérotation / sonnerie : où ça vit réellement

> Session du 2026-08-29. Fait suite à une hypothèse reçue en cours de session
> (texte externe attribuant des significations "OFF_HOOK / KEY_PRESSED /
> LED_CONTROL / DISPLAY_TEXT / AUDIO_PATH_CTRL" à des valeurs d'opcode
> UAUDP 0x01/0x06/0x10/0x24/0x41). **Cette hypothèse est fausse** — elle
> confond le niveau transport (UAUDP) et le niveau applicatif (UA3G/NOE).
> Vérifié par lecture directe de `packet-uaudp.c` et `packet-ua3g.c`
> (sources upstream Wireshark, cf. §3).

## 1. Pourquoi `uaudp.opcode` ne peut pas coder le décroché/la numérotation

`uaudp.opcode` est un champ de **transport**, comparable aux flags TCP. Sa
table officielle (`uaudp_opcode_str[]`, `packet-uaudp.c`) ne contient que
8 valeurs, déjà documentées dans `noe-ua3g-homer-mapping.md` §6bis :

| Opcode | Signification (transport, pas métier) |
|---|---|
| 0 | Connect |
| 1 | Connect ACK |
| 2 | Release |
| 3 | Release ACK |
| 4 | Keepalive |
| 5 | Keepalive ACK |
| 6 | NACK |
| 7 | **Data** |

Le contenu téléphonique (décroché, touche pressée, texte affiché, RTP)
voyage **entièrement à l'intérieur des paquets opcode 7 (Data)**, encapsulé
en UA3G. L'opcode UAUDP ne varie pas en fonction du contenu métier — il
reste `7` qu'il y ait décroché, appui touche ou accusé applicatif.

## 2. Les vrais champs UA3G pour la signalisation d'appel

Confirmés présents dans `packet-ua3g.c` (upstream, `tshark -G fields`) :

| Champ tshark | Rôle réel |
|---|---|
| `ua3g.unsolicited_msg.hook_status` | État du combiné (on/off). **Attention** : observé dans nos captures uniquement à l'intérieur d'un message `IP Device Routing: Init` (enregistrement du poste au démarrage — équivalent REGISTER), pas lors d'un vrai décroché en cours d'appel. |
| `ua3g.digit_dialed.digit_value` | La vraie valeur d'un chiffre composé (un champ par chiffre numéroté). |
| `ua3g.key_number` | Numéro de touche pressée (clavier physique, pas forcément un chiffre — peut être une touche de fonction). |
| `ua3g.special_key.hookswitch_status` | Variante liée aux touches spéciales / statut combiné. |

## 3. Ce qui est erroné dans l'hypothèse "OFF_HOOK/KEY_PRESSED/..." reçue en session

| Valeur affirmée | Vraie signification (source vérifiée) |
|---|---|
| `uaudp.opcode 0x01` = OFF_HOOK | En réalité **Connect ACK** (accusé de connexion transport) |
| `uaudp.opcode 0x02` = ON_HOOK | En réalité **Release** (fermeture transport) |
| `uaudp.opcode 0x06` = KEY_PRESSED | En réalité **NACK** |
| `uaudp.opcode 0x10/0x11` = LED_CONTROL / sonnerie | Non documenté officiellement (cf. `noe-ua3g-homer-mapping.md` §6ter — hypothèse "bit 0x10" sur le canal local, sans rapport avec la sonnerie) |
| `uaudp.opcode 0x24` = DISPLAY_TEXT | Jamais observé dans nos captures ; pas dans `uaudp_opcode_str[]` |
| `uaudp.opcode 0x41` = AUDIO_PATH_CTRL | Idem — pas dans la table officielle |

Sources de vérification : `packet-uaudp.c` (Fossies/GitHub, upstream
Wireshark), test direct `tshark -V` sur nos captures d'exemple confirmant
les libellés natifs (`Opcode: Connect ACK (1)`, etc., jamais "OFF_HOOK").

## 4. Constat sur les 3 captures d'exemple du projet

Aucune ne contient de vraie séquence décroché → numérotation → sonnerie :

| Capture | Durée | Contenu observé |
|---|---|---|
| `ua3g_freeseating_ipv4.pcap` | 20 s / 64 paquets | Uniquement `Create/Delete/SetProperty` — écran freeseating, zéro `event` |
| `ua3g_freeseating_ipv6.pcap` | 141 s / 339 paquets | `EVT_KEY_PRESS` = navigation menu freeseating (saisie code/badge), pas de numérotation téléphonique. `ua3g.digit_dialed.digit_value` et `ua3g.key_number` vides partout. Seule occurrence de `hook_status` (frame 119) = message `IP Device Routing: Init` (boot du poste), pas un décroché en cours d'appel |
| `uaudp_ipv6.pcap` | 357 s / 2544 paquets | Transport seul (nécessite `--decode-as`, cf. mapping doc §6ter), aucun contenu UA3G exploitable |

**Conclusion** : impossible de reconstituer un numéro composé à partir de
ces 3 fichiers — l'information n'y est simplement pas présente.

## 5. Commande à utiliser sur une vraie capture d'appel

```bash
tshark -r ta_trace.pcap -d "udp.port==32640,uaudp" -d "udp.port==32513,uaudp" \
  -Y "ua3g.unsolicited_msg.hook_status or ua3g.digit_dialed.digit_value or ua3g.key_number" \
  -T fields -e frame.number -e frame.time_relative -e ua3g.opcode \
  -e ua3g.unsolicited_msg.hook_status -e ua3g.digit_dialed.digit_value -e ua3g.key_number
```

Séquence attendue sur un appel sortant réel : `hook_status: On` (décroché)
→ une suite de `digit_dialed.digit_value` (un par chiffre composé) →
opcodes de tonalité/sonnerie. À valider dès qu'une vraie capture d'appel
est disponible — cette note sera mise à jour avec les valeurs réellement
observées (frame par frame) à ce moment-là.

## 6. Capture recommandée (rappel)

```bash
sudo tcpdump -i eth0 -w oxo_trace_$(date +%Y%m%d_%H%M%S).pcap \
  "udp port 32640 or udp port 32513"
```

Laisser tourner pendant un vrai décroché → composition → raccroché pour
capturer une séquence exploitable.
