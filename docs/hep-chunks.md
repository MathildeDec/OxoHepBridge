# Chunks HEPv3 encodés

Référence : [HEP3 rev12](https://www.voztovoice.org/sites/default/files/hep3_rev12.pdf)
et [heplify-server decoder_test.go](https://github.com/sipcapture/heplify-server/blob/master/decoder/decoder_test.go).

## Format paquet

```
"HEP3" (4 octets ASCII) + longueur totale (uint16 big-endian) + chunks...
```

## Format chunk

```
vendor_id (uint16) + chunk_type (uint16) + chunk_length (uint16, inclut les 6 octets d'en-tête) + payload
```

## Chunks émis par oxo-hep-bridge

| ID     | Nom                  | Type           | Toujours présent | Valeur                                    |
| ------ | -------------------- | -------------- | ----------------- | ------------------------------------------ |
| 0x0001 | IP protocol family   | uint8          | oui                | 2 = IPv4, 10 = IPv6                        |
| 0x0002 | IP protocol ID       | uint8          | oui                | 17 = UDP, 6 = TCP                          |
| 0x0003 | IPv4 source          | inet4-addr     | si IPv4            | adresse source                             |
| 0x0004 | IPv4 destination     | inet4-addr     | si IPv4            | adresse destination                        |
| 0x0005 | IPv6 source          | inet6-addr     | si IPv6            | adresse source                             |
| 0x0006 | IPv6 destination     | inet6-addr     | si IPv6            | adresse destination                        |
| 0x0007 | Port source           | uint16         | oui                | port UDP/TCP source                        |
| 0x0008 | Port destination      | uint16         | oui                | port UDP/TCP destination                   |
| 0x0009 | Timestamp (secondes)  | uint32         | oui                | epoch, issu de `frame.time_epoch`          |
| 0x000A | Timestamp (µs)        | uint32         | oui                | microsecondes                              |
| 0x000B | Protocol type          | uint8          | oui                | 100 (LOG) par défaut — pas de type SIP natif |
| 0x000C | Capture agent ID       | uint32         | oui                | identifiant configuré (`--hep-id`)         |
| 0x000D | Keepalive timer         | uint16         | keepalive seulement | intervalle en secondes (`--keepalive-interval`), absent des paquets normaux |
| 0x000E | Auth key               | octet-string   | si configuré        | `--hep-pass` / `OXOHEP_HEP_PASS`           |
| 0x000F | Payload                | octet-string   | oui, sauf si compressé | JSON UTF-8 des champs UAUDP/UA3G/NOE (ou marqueur `{"type":"keepalive",...}`) |
| 0x0010 | Compressed payload      | octet-string (gzip) | si `--hep-compress-payload` | payload gzippé, remplace 0x000F (jamais les deux ensemble) |
| 0x0011 | Correlation ID         | octet-string   | oui, sauf keepalive | clé de corrélation (voir architecture.md) — absent du paquet keepalive (aucun flux réel à corréler) |
| 0x0013 | Node name               | octet-string   | si configuré        | `--node-name` / `OXOHEP_NODE_NAME`         |

## Pourquoi `proto_type = LOG (100)` par défaut

UAUDP/UA3G/NOE n'est pas un protocole de signalisation standard (pas SIP, pas
H.323). HOMER/heplify-server route les paquets selon `proto_type` ; le type
`LOG` (générique, texte/JSON libre) est celui recommandé pour les protocoles
propriétaires non normalisés dans la spec HEP, à la place d'un type SIP qui
imposerait un format de payload SIP invalide ici.

## Structure du payload JSON

Le champ payload (chunk 0x000F) contient un objet JSON avec les sous-clés
disponibles pour le paquet :

```json
{
  "uaudp": { "opcode": "4", "sntseq": "10", "expseq": "8" },
  "ua3g": [
    { "opcode": "0x3f", "command_mute": false }
  ],
  "noe": [
    { "objectid": "4867", "class": "128", "method": "2" },
    { "objectid": "4864", "class": "128", "method": "2" }
  ]
}
```

Comme `noe`, `ua3g` est toujours une liste (un paquet UAUDP opcode 7 peut
empiler plusieurs messages UA3G — jusqu'à 3 observés dans les captures
d'exemple), jamais un objet unique.

Seules les clés présentes dans le paquet capturé sont incluses.

## Compression du payload (chunk 0x0010)

`--hep-compress-payload` (`hep.compress_payload` en TOML,
`OXOHEP_HEP_COMPRESS_PAYLOAD` en environnement, désactivé par défaut) fait
émettre le chunk `COMPRESSED_PAYLOAD` (0x0010, contenu gzippé via
`gzip.compress()`) à la place du chunk `PAYLOAD` (0x000F) — les deux ne sont
jamais présents simultanément sur un même paquet.

**⚠️ Vérifié incompatible avec HOMER11 en l'état.** Le décodeur HEP de
HOMER11 (`src/decoder/decoder.go`) définit une liste fermée de chunks connus
qui s'arrête à `NodeName` (0x0013) ; tout chunk hors de cette liste — dont
0x0010 — tombe dans un `switch` par défaut muet et n'est pas exploité. Sans
chunk `PAYLOAD` (0x000F) pour prendre le relais, le paquet HEP reçu par
HOMER11 aurait un payload vide : ce n'est pas une dégradation mineure, c'est
une perte de données pour chaque paquet envoyé. Ce constat vient d'une
lecture directe du code source de HOMER11 (chunk types déclarés dans
`decoder.go`, `switch chunkType` de `parseHEP()` dans `hep.go`), pas d'une
supposition.

Cette option reste implémentée (conforme à la spec HEP3 rev12, décodable par
`tools/hep_receiver.py` fourni avec ce projet) pour un usage contre un futur
collecteur qui supporterait explicitement ce chunk, ou un autre outil
conforme à la spec — jamais recommandée en l'état contre HOMER11 ou
heplify-server sans avoir vérifié au préalable leur support de ce chunk
côté collecteur. `cli.py` logge un avertissement explicite au démarrage si
l'option est activée.

## Paquet keepalive

Quand `--keepalive-interval` est configuré (capture live uniquement), un
paquet HEPv3 distinct est envoyé périodiquement en plus du flux normal. Il
diffère des paquets de trafic capturé sur plusieurs points :

- pas de chunks IP/port réels : `0.0.0.0:0` (aucun flux n'est représenté),
- porte le chunk 0x000D (Keepalive timer, absent des paquets de trafic),
- **pas de chunk 0x0011 (Correlation ID)** : contrairement à un paquet de
  trafic normalisé (`normalize()` calcule toujours un `correlation_id`, via
  `build_correlation_id()` — jamais vide, voir architecture.md), le
  keepalive ne représente aucun flux réel et n'a donc rien à corréler,
- payload JSON minimal, distinguable par `"type": "keepalive"` :

```json
{
  "type": "keepalive",
  "node_name": "oxo-besancon-01",
  "capture_agent_id": 2001,
  "interval_seconds": 60
}
```

Voir [architecture.md](architecture.md#keepalive-hep-p%C3%A9riodique) pour le
détail du mécanisme.
