# GrabDrop

Transférer des données entre appareils d'un geste de la main, à la manière de
Huawei Share : on **ferme la main** devant un écran pour « attraper », on
**l'ouvre** devant un autre pour « déposer ».

Tout le traitement vidéo est fait localement : aucune image de la caméra ne
quitte l'appareil.

## État : V2 (fichiers, presse-papiers, icône, appairage court)

| Geste | Séquence | Effet |
|---|---|---|
| Attraper | main ouverte → poing fermé (tenu ~0,3 s) | met un objet « en main » pendant 20 s |
| Déposer | poing fermé → main ouverte (tenue ~0,3 s) | l'objet en main sur un autre PC arrive ici |

**Ce qui est attrapé**, par ordre de priorité :

1. les fichiers et dossiers **sélectionnés dans l'Explorateur** au premier plan ;
2. sinon, ce que vous avez **copié (Ctrl+C) il y a moins de 30 s** : texte, image ou fichiers ;
3. sinon, une **capture de l'écran** sous la souris.

Une copie ancienne n'est jamais envoyée, et chaque copie ne part qu'une fois.

**À la réception** :

| Objet | Ce qui se passe |
|---|---|
| capture d'écran | enregistrée dans `Images\GrabDrop` et ouverte |
| image copiée | enregistrée, ouverte, et placée dans le presse-papiers |
| texte copié | placé dans le presse-papiers (Ctrl+V) ; un lien seul s'ouvre dans le navigateur |
| fichiers, dossiers | placés dans `Téléchargements\GrabDrop`, l'Explorateur s'ouvre dessus |

Rien n'est jamais écrasé : un élément existant est renommé « nom (1) ».

## Installation (sur chaque PC)

Python 3.11 recommandé.

```bash
git clone https://github.com/nouxel00/grabdrop_share.git
cd grabdrop_share
python -m venv .venv
.venv\Scripts\activate          # Windows (Linux/macOS : source .venv/bin/activate)
pip install -e ".[dev]"
```

Le modèle MediaPipe (~8 Mo) est téléchargé automatiquement au premier lancement.

## Lancement

```bash
python -m grabdrop
```

Une **icône** apparaît dans la barre des tâches (clic droit pour le menu) :
bleue au repos, orange quand un objet est en main, grise caméra en pause.

| Menu | Rôle |
|---|---|
| Mettre la caméra en pause | libère la webcam (visio, confidentialité) |
| Afficher l'aperçu caméra | fenêtre de réglage : main détectée, posture, taille |
| Appairer un nouvel appareil… | affiche un code à 6 chiffres |
| Rejoindre un groupe… | saisir le code affiché par l'autre appareil |
| Ouvrir les fichiers reçus | `Téléchargements\GrabDrop` |
| Lancer au démarrage de Windows | GrabDrop démarre sans console à l'ouverture de session |

Sans console : `pythonw -m grabdrop` (ou `grabdropw`). Le journal est dans
`%APPDATA%\GrabDrop\grabdrop.log`.

## Appairage

Sur un PC : icône → **Appairer un nouvel appareil…** (ou `python -m grabdrop pair`).
Un code à 6 chiffres s'affiche pendant 2 minutes.

Sur l'autre : icône → **Rejoindre un groupe…** et saisir le code (ou
`python -m grabdrop pair 123456`).

L'échange du code utilise SPAKE2 (échange de clé authentifié par mot de passe) :
écouter le réseau ne permet pas de retrouver le code, et un seul essai est
accepté par code. Ensuite, tous les échanges sont chiffrés et authentifiés
(AES-256-GCM, transferts découpés en morceaux chiffrés et numérotés) avec la clé
du groupe, stockée dans `%APPDATA%\GrabDrop\config.json`.

Pour ajouter un troisième appareil, répétez l'opération depuis n'importe quel
appareil du groupe. En secours, `python -m grabdrop code` affiche le code de
groupe complet, utilisable avec `pair`.

### Premier lancement sous Windows

- Le **pare-feu Windows** demande d'autoriser Python : cochez **Réseaux privés**.
- Le Wi-Fi doit être en profil **Privé** (en profil Public, la découverte est bloquée).

## Options

| Option | Rôle |
|---|---|
| `--preview` | ouvrir l'aperçu caméra dès le lancement |
| `--no-tray` | console seule, sans icône (`q` ou Ctrl+C pour quitter) |
| `--min-hand-size 0.15` | ignorer les mains plus lointaines (si un PC voisin réagit à vos gestes) |
| `--peer 192.168.1.20` | indiquer l'autre PC à la main si la découverte automatique échoue |
| `--hold-seconds 30` | durée pendant laquelle un objet attrapé reste disponible |
| `--recent-copy-seconds 60` | ancienneté maximale d'une copie pour être attrapée |
| `--images-out`, `--files-out` | dossiers de réception |
| `--no-open` | ne rien ouvrir automatiquement à la réception |
| `--camera 1`, `--allow-back`, `--log essai.csv` | autre webcam ; accepter le dos de la main ; journal de réglage |

Démo des gestes seuls, sans réseau : `python -m grabdrop.demo`.

### Dépannage

- *« Aucun autre appareil GrabDrop trouvé »* : pare-feu et profil réseau sur les
  deux PC, ou `--peer IP_DE_L_AUTRE_PC`.
- *« refuse la requête »* : les PC ne sont pas du même groupe (refaire
  l'appairage), ou leurs horloges ont plus de 2 minutes d'écart.
- *« Caméra indisponible »* : une autre application l'utilise ; GrabDrop
  réessaie toutes les 5 s.

## Fonctionnement

1. Chaque PC s'annonce sur le réseau local (mDNS, `_grabdrop._tcp`) avec un
   identifiant dérivé de la clé du groupe : il ne voit que les PC de son groupe.
2. Au GRAB, l'objet reste sur le PC d'origine ; rien n'est envoyé.
3. Au DROP, le PC interroge les autres, récupère l'objet le plus récent (le
   premier qui le réclame l'obtient, une seule fois). Les fichiers sont écrits
   au fil de l'eau dans un dossier temporaire, puis déplacés une fois complets :
   un transfert interrompu ne laisse rien de partiel.

## Tests

```bash
pytest
```

## Structure

```
grabdrop/
  agent.py          agent : commandes run / pair / code, gestes, menu de l'icône
  camera.py         boucle caméra (pause, aperçu, reprise si la caméra est occupée)
  gestures.py       machine à états postures -> GRAB/DROP (sans dépendance caméra)
  hand_geometry.py  doigts tendus/repliés, orientation de la paume, taille de la main
  detector.py       détection de la main et de sa posture (MediaPipe)
  sources.py        ce qui est attrapé : sélection, copie récente, capture
  capture.py        capture d'écran en mémoire
  deliver.py        ce qui se passe à la réception
  items.py          objets transférables, objet « en main », noms de fichiers sûrs
  network.py        découverte mDNS, serveur et client HTTP chiffrés, transferts en flux
  pairing.py        appairage par code à 6 chiffres (SPAKE2)
  crypto.py         clé de groupe, chiffrement AES-256-GCM, flux chiffrés
  platform_win.py   Explorateur, presse-papiers, dossiers Windows, démarrage auto
  tray.py           icône de la barre des tâches
  dialogs.py        fenêtres d'affichage et de saisie du code
  config.py         identité de l'appareil, clé du groupe
  demo.py           démo des gestes sans réseau
tests/              tests unitaires et réseau (plusieurs PC simulés en local)
```

## Feuille de route

- [x] **V0** : détection fiable des gestes grab/drop
- [x] **V1** : PC ↔ PC sur le réseau local, transfert de captures d'écran, chiffré
- [x] **V2** : fichiers, dossiers, presse-papiers ; icône ; appairage par code court
- [ ] **V3** : application Android, animations
