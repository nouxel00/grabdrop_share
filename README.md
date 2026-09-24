# GrabDrop

Transférer des données entre appareils d'un geste de la main, à la manière de
Huawei Share : on **ferme la main** devant un écran pour « attraper », on
**l'ouvre** devant un autre pour « déposer ».

Tout le traitement vidéo est fait localement : aucune image de la caméra ne
quitte l'appareil.

## État : V3 (PC Windows + téléphone Android, animations)

| Geste | Séquence | Effet |
|---|---|---|
| Attraper | main ouverte → poing fermé (tenu ~0,3 s) | met un objet « en main » (20 s sur PC, 60 s sur téléphone) |
| Déposer | poing fermé → main ouverte (tenue ~0,3 s) | l'objet en main sur un autre appareil arrive ici |

Sur PC, une animation accompagne chaque geste : l'objet attrapé rétrécit vers
le bas de l'écran, l'objet reçu surgit au centre (désactivable avec `--no-animations`).

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

## Installation sur PC Windows (sans Python)

Lancer **`GrabDrop-Setup-0.4.0.exe`** et suivre l'assistant :

- **pour tous les utilisateurs** (droits administrateur) : GrabDrop est aussi
  autorisé dans le pare-feu Windows (réseaux privés) ;
- **pour moi seulement** : sans droits administrateur ; Windows demandera
  d'autoriser GrabDrop dans le pare-feu au premier lancement.

L'assistant crée un raccourci dans le menu Démarrer (et sur le Bureau en option)
et propose le lancement automatique à l'ouverture de session. Ensuite, plus
aucune commande : GrabDrop démarre avec Windows, ou depuis le menu Démarrer.
La désinstallation (Paramètres → Applications) garde l'appairage.

L'installateur n'est pas signé : Windows SmartScreen peut afficher « Windows a
protégé votre ordinateur » → **Informations complémentaires** → **Exécuter quand même**.

**Fabriquer l'installateur** (Inno Setup 6 : `winget install JRSoftware.InnoSetup`) :

```bash
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Résultat : `packaging\dist\GrabDrop-Setup-<version>.exe`. L'exécutable autonome
(PyInstaller, modèle de gestes inclus) est dans `packaging\dist\GrabDrop\`.

## Installation pour développer (sur chaque PC)

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
Une fenêtre affiche pendant 2 minutes un **code à 6 chiffres** (pour un autre PC)
et un **QR code** (pour un téléphone).

- Autre PC : icône → **Rejoindre un groupe…** et saisir le code (ou
  `python -m grabdrop pair 123456`).
- Téléphone : app GrabDrop → **Scanner le QR code** (l'appareil photo du
  téléphone ouvre aussi l'app directement).

L'échange du code utilise SPAKE2 (échange de clé authentifié par mot de passe) :
écouter le réseau ne permet pas de retrouver le code, et un seul essai est
accepté par code. Le QR contient un jeton aléatoire de 128 bits qui ne circule
jamais sur le réseau et ne sert qu'une fois. Ensuite, tous les échanges sont
chiffrés et authentifiés (AES-256-GCM, transferts découpés en morceaux chiffrés
et numérotés) avec la clé du groupe, stockée dans `%APPDATA%\GrabDrop\config.json`.

À l'appairage par QR, le PC et le téléphone retiennent l'adresse l'un de
l'autre : si la découverte automatique (mDNS) est bloquée par le Wi-Fi, ils se
joignent quand même.

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
| `--no-animations` | pas d'animation à l'écran au GRAB et au DROP |
| `--no-ble` | ne pas utiliser le Bluetooth pour trouver les appareils |
| `--camera 1`, `--allow-back`, `--log essai.csv` | autre webcam ; accepter le dos de la main ; journal de réglage |

Démo des gestes seuls, sans réseau : `python -m grabdrop.demo`.

### Dépannage

- *« Aucun autre appareil GrabDrop trouvé »* : pare-feu et profil réseau sur les
  deux PC, ou `--peer IP_DE_L_AUTRE_PC`.
- *« refuse la requête »* : les PC ne sont pas du même groupe (refaire
  l'appairage), ou leurs horloges ont plus de 2 minutes d'écart.
- *« Caméra indisponible »* : une autre application l'utilise ; GrabDrop
  réessaie toutes les 5 s.

## Application Android

Android 10 ou plus récent, avec les services Google (pour le scanner de QR).

**Installer** : copier `GrabDrop.apk` sur le téléphone et l'ouvrir (autoriser
l'installation d'applications inconnues), ou, téléphone branché en USB avec le
débogage USB activé :

```bash
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

**Compiler** (JDK 17 ou plus, SDK Android) :

```bash
cd android
./gradlew assembleDebug        # Windows : gradlew.bat assembleDebug
```

**Utiliser** :

| Pour… | Faire |
|---|---|
| envoyer du téléphone vers un PC | « Partager → GrabDrop » depuis n'importe quelle app (photos, fichiers, liens, texte), ou les boutons **Photos** / **Fichiers** de l'app ; puis DROP devant un PC |
| recevoir sur le téléphone | GRAB devant un PC, puis DROP devant le téléphone (app ouverte), ou bouton **Recevoir** |
| attraper un texte copié | copier le texte, ouvrir GrabDrop, GRAB devant le téléphone (copie de moins d'une minute) |

La caméra ne surveille les gestes que lorsque l'app est à l'écran. Un objet
partagé reste en main 60 s, même si l'app passe en arrière-plan (notification).
À la réception : fichiers dans `Téléchargements/GrabDrop`, captures et images
dans `Images/GrabDrop`, texte dans le presse-papiers (un lien s'ouvre).

## Bluetooth : trouver les appareils proches

Le Bluetooth basse consommation (BLE) sert à **trouver** les appareils du groupe
et à estimer leur **proximité** ; les données passent toujours par le Wi-Fi,
bien plus rapide (même principe que Huawei Share).

- Chaque appareil diffuse une annonce de 18 octets : son adresse et son port
  Wi-Fi, et s'il **tient un objet**. Le téléphone affiche par exemple
  « « Axel-Laptop » très proche · Axel-Laptop tient un objet, faites DROP ! ».
- Les appareils se trouvent même quand le Wi-Fi bloque la découverte mDNS
  (points d'accès publics, partage de connexion du téléphone...).
- L'annonce est chiffrée et signée avec une clé dérivée de celle du groupe, et
  change toutes les 10 minutes : un appareil étranger ne peut ni lire
  l'adresse, ni suivre un appareil, ni fabriquer une fausse annonce acceptée.

Il faut le Bluetooth activé (sur le PC : Paramètres → Bluetooth et appareils)
et, sur le téléphone, l'autorisation « Appareils à proximité ». Sans Bluetooth,
GrabDrop continue par le Wi-Fi seul ; `--no-ble` le désactive côté PC. Le menu
de l'icône indique les appareils entendus et le plus proche.

## Fonctionnement

1. Chaque PC s'annonce sur le réseau local (mDNS, `_grabdrop._tcp`) et en
   Bluetooth, avec un identifiant dérivé de la clé du groupe : il ne voit que
   les appareils de son groupe.
2. Au GRAB, l'objet reste sur le PC d'origine ; rien n'est envoyé.
3. Au DROP, le PC interroge les autres, récupère l'objet le plus récent (le
   premier qui le réclame l'obtient, une seule fois). Les fichiers sont écrits
   au fil de l'eau dans un dossier temporaire, puis déplacés une fois complets :
   un transfert interrompu ne laisse rien de partiel.

## Tests

```bash
pytest                                   # PC (Python)
cd android && ./gradlew testDebugUnitTest  # téléphone (Kotlin), dont l'interopérabilité avec le Python
```

Le test d'interopérabilité lance un vrai nœud Python (`tools/interop_peer.py`) :
transferts dans les deux sens et appairage par QR entre le code Kotlin et le code
Python.

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
  ble.py            découverte Bluetooth (annonces chiffrées, proximité)
  pairing.py        appairage par code à 6 chiffres (SPAKE2) et par QR code
  crypto.py         clé de groupe, chiffrement AES-256-GCM, flux chiffrés
  platform_win.py   Explorateur, presse-papiers, dossiers Windows, démarrage auto
  tray.py           icône de la barre des tâches
  ui.py             thread d'interface unique (tkinter)
  dialogs.py        fenêtres d'appairage (code et QR) et de saisie du code
  overlay.py        animations à l'écran (GRAB, DROP)
  config.py         identité de l'appareil, clé du groupe, adresses connues
  demo.py           démo des gestes sans réseau
tests/              tests unitaires et réseau (plusieurs PC simulés en local)
tools/
  interop_peer.py   nœud Python piloté par le test d'interopérabilité Kotlin
packaging/          installateur Windows
  build.ps1         fabrique tout : préparation, PyInstaller, Inno Setup
  prepare.py        icône .ico, modèle de gestes, informations de version
  grabdrop.spec     recette PyInstaller (GrabDrop.exe sans console)
  grabdrop.iss      programme d'installation (raccourcis, démarrage, pare-feu)
  launcher.py       point d'entrée de GrabDrop.exe
android/            application Android (Kotlin, Jetpack Compose)
  app/src/main/java/io/github/nouxel00/grabdrop/
    core/           protocole, chiffrement, gestes : Kotlin pur, testé sur PC
    GrabDropRuntime.kt  état de l'app, envoi, réception, appairage
    GestureCamera.kt    caméra frontale + MediaPipe
    Discovery.kt        découverte mDNS (NsdManager)
    BleDiscovery.kt     découverte Bluetooth (annonce et détection BLE)
    Storage.kt          Téléchargements, Images, presse-papiers
    ui/                 écran principal et animations
```

## Feuille de route

- [x] **V0** : détection fiable des gestes grab/drop
- [x] **V1** : PC ↔ PC sur le réseau local, transfert de captures d'écran, chiffré
- [x] **V2** : fichiers, dossiers, presse-papiers ; icône ; appairage par code court
- [x] **V3** : application Android, appairage par QR, animations
