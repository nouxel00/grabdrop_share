# GrabDrop

Transférer des données entre appareils d'un geste de la main, à la manière de
Huawei Share : on **ferme la main** devant un écran pour « attraper », on
**l'ouvre** devant un autre pour « déposer ».

Tout le traitement vidéo est fait localement : aucune image ne quitte l'appareil.

## État : V0 (détection des gestes)

| Geste | Séquence | Événement |
|---|---|---|
| Attraper | main ouverte → poing fermé (tenu ~0,3 s) | `GRAB` |
| Déposer | poing fermé → main ouverte (tenue ~0,3 s) | `DROP` |

Une posture seule ne déclenche rien : il faut une transition, ce qui limite les
faux positifs. La main ouverte n'est acceptée que **paume face à la caméra**.

La posture est déduite de deux sources combinées : le classifieur de gestes
MediaPipe et la géométrie des doigts (distance du bout de chaque doigt au
poignet), plus tolérante pour une main ouverte doigts serrés.

## Installation

Python 3.11 recommandé.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (Linux/macOS : source .venv/bin/activate)
pip install -r requirements-dev.txt
```

Le modèle MediaPipe (~8 Mo) est téléchargé automatiquement dans `models/` au
premier lancement.

## Utilisation

```bash
python -m grabdrop.demo
```

Options : `--camera 1` (autre webcam), `--min-score 0.5` (confiance minimale),
`--hold-ms 400` (durée de tenue), `--allow-back` (accepter la main vue de dos),
`--log essai.csv` (enregistre chaque image analysée, utile pour le réglage).
Touche `q` ou `Échap` pour quitter.

Conseils : main à 40–80 cm de la caméra, paume face à l'écran, pièce éclairée.

## Tests

```bash
pytest
```

## Structure

```
grabdrop/
  gestures.py       machine à états postures -> GRAB/DROP (sans dépendance caméra)
  hand_geometry.py  doigts tendus/repliés, orientation de la paume (calculs purs)
  detector.py       détection de la main et de sa posture (MediaPipe)
  demo.py       démo webcam V0
tests/          tests de la machine à états
```

## Feuille de route

- [x] **V0** : détection fiable des gestes grab/drop
- [ ] **V1** : PC ↔ PC sur le réseau local, transfert de captures d'écran
- [ ] **V2** : presse-papiers et fichiers, appairage sécurisé, icône dans la barre des tâches
- [ ] **V3** : application Android, animations
