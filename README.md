# GrabDrop

Transférer des données entre appareils d'un geste de la main, à la manière de
Huawei Share : on **ferme la main** devant un écran pour « attraper », on
**l'ouvre** devant un autre pour « déposer ».

Tout le traitement vidéo est fait localement : aucune image de la caméra ne
quitte l'appareil.

## État : V1 (captures d'écran entre PC)

| Geste | Séquence | Effet |
|---|---|---|
| Attraper | main ouverte → poing fermé (tenu ~0,3 s) | capture de l'écran sous la souris, gardée « en main » 20 s |
| Déposer | poing fermé → main ouverte (tenue ~0,3 s) | la capture en main sur un autre PC arrive ici, est enregistrée et ouverte |

Une posture seule ne déclenche rien : il faut une transition, ce qui limite les
faux positifs. La main ouverte n'est acceptée que **paume face à la caméra**,
et une main trop éloignée est ignorée (gestes destinés à un PC voisin).

## Installation (sur chaque PC)

Python 3.11 recommandé.

```bash
git clone https://github.com/nouxel00/grabdrop_share.git
cd grabdrop_share
python -m venv .venv
.venv\Scripts\activate          # Windows (Linux/macOS : source .venv/bin/activate)
pip install -r requirements-dev.txt
```

Le modèle MediaPipe (~8 Mo) est téléchargé automatiquement dans `models/` au
premier lancement.

## Appairage (une seule fois)

Sur le premier PC :

```bash
python -m grabdrop code
```

Il affiche un code du type `ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ`. Sur le second PC :

```bash
python -m grabdrop pair ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ
```

Tous les échanges sont chiffrés et authentifiés (AES-256-GCM) avec une clé
dérivée de ce code : un appareil qui ne le connaît pas ne peut ni voir ni
récupérer vos captures. Gardez-le pour vous. Il est stocké dans
`%APPDATA%\GrabDrop\config.json` (Windows) ou `~/.config/grabdrop/` (Linux/macOS).

## Utilisation

```bash
python -m grabdrop --preview
```

`--preview` affiche la fenêtre caméra (pratique pour les premiers essais) ;
sans elle, l'agent tourne en console (Ctrl+C pour quitter) et signale chaque
action par un son. Les captures reçues vont dans `Images\GrabDrop`.

Options utiles :

| Option | Rôle |
|---|---|
| `--min-hand-size 0.15` | ignorer les mains plus lointaines (si un PC voisin réagit à vos gestes) |
| `--peer 192.168.1.20` | indiquer l'autre PC à la main, si la découverte automatique échoue |
| `--hold-seconds 30` | durée pendant laquelle une capture attrapée reste disponible |
| `--out DOSSIER`, `--no-open` | dossier de réception ; ne pas ouvrir ce qui est reçu |
| `--camera 1`, `--allow-back`, `--log essai.csv` | autre webcam ; accepter le dos de la main ; journal de réglage |

Démo des gestes seuls, sans réseau : `python -m grabdrop.demo`.

### Premier lancement sous Windows

- Le **pare-feu Windows** demande d'autoriser Python : cochez **Réseaux privés**
  et acceptez. Sans cela, l'autre PC ne peut pas récupérer vos captures.
- Le Wi-Fi doit être en profil **Privé** (Paramètres → Réseau et Internet →
  propriétés du réseau). En profil Public, Windows bloque la découverte.

### Dépannage

- *« aucun autre appareil GrabDrop trouvé »* : vérifier le pare-feu et le profil
  réseau sur les deux PC, ou utiliser `--peer IP_DE_L_AUTRE_PC`.
- *« refuse la requête »* : les deux PC n'ont pas le même code, ou leurs
  horloges ont plus de 2 minutes d'écart.

## Fonctionnement

1. Chaque PC s'annonce sur le réseau local (mDNS, `_grabdrop._tcp`) avec un
   identifiant de groupe dérivé du code : il ne voit que les PC de son groupe.
2. Au GRAB, la capture reste en mémoire sur le PC d'origine ; rien n'est envoyé.
3. Au DROP, le PC interroge les autres, récupère l'objet le plus récent (le
   premier qui le réclame l'obtient, une seule fois) et l'enregistre.

## Tests

```bash
pytest
```

## Structure

```
grabdrop/
  agent.py          agent : commandes run / pair / code, actions GRAB et DROP
  camera.py         boucle caméra, aperçu, options de détection
  gestures.py       machine à états postures -> GRAB/DROP (sans dépendance caméra)
  hand_geometry.py  doigts tendus/repliés, orientation de la paume, taille de la main
  detector.py       détection de la main et de sa posture (MediaPipe)
  capture.py        capture d'écran en mémoire
  items.py          objet « en main » (expiration, retrait unique), enregistrement
  network.py        découverte mDNS, serveur et client HTTP chiffrés
  crypto.py         code d'appairage, chiffrement AES-256-GCM
  config.py         identité de l'appareil, code d'appairage
  demo.py           démo des gestes sans réseau
tests/              tests unitaires et tests réseau (deux PC simulés en local)
```

## Feuille de route

- [x] **V0** : détection fiable des gestes grab/drop
- [x] **V1** : PC ↔ PC sur le réseau local, transfert de captures d'écran, chiffré
- [ ] **V2** : presse-papiers et fichiers, appairage par code court, icône dans la barre des tâches
- [ ] **V3** : application Android, animations
