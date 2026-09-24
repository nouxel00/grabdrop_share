"""Prépare ce que PyInstaller et Inno Setup embarquent : icône, modèle de gestes, version.

Écrit dans packaging/build/ :
- grabdrop.ico              icône (même dessin que l'icône de la barre des tâches)
- gesture_recognizer.task   modèle MediaPipe, livré avec l'exécutable (fonctionne hors ligne)
- version_info.txt          propriétés du fichier GrabDrop.exe (nom, version...)
- version.txt               numéro de version, lu par build.ps1
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "packaging" / "build"
sys.path.insert(0, str(ROOT))

from grabdrop import __version__  # noqa: E402
from grabdrop.detector import MODEL_PATH, MODEL_URL  # noqa: E402
from grabdrop.tray import IDLE, make_icon  # noqa: E402

VERSION_INFO = """\
VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', 'GrabDrop'),
      StringStruct('FileDescription', 'GrabDrop'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'GrabDrop'),
      StringStruct('OriginalFilename', 'GrabDrop.exe'),
      StringStruct('ProductName', 'GrabDrop'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x040C, 1200])])
  ]
)
"""


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)

    # Icône : chaque taille est dessinée à part, plus nette qu'une réduction.
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [make_icon(IDLE, s) for s in sizes]
    images[-1].save(BUILD / "grabdrop.ico", format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])

    model = BUILD / "gesture_recognizer.task"
    if not model.exists():
        if MODEL_PATH.exists():
            shutil.copy2(MODEL_PATH, model)
        else:
            print(f"Téléchargement du modèle de gestes -> {model}")
            urllib.request.urlretrieve(MODEL_URL, model)

    numbers = tuple(int(n) for n in __version__.split(".")) + (0,)
    (BUILD / "version_info.txt").write_text(VERSION_INFO.format(t=numbers[:4], v=__version__), encoding="utf-8")
    (BUILD / "version.txt").write_text(__version__, encoding="ascii")
    print(f"Préparé pour GrabDrop {__version__} dans {BUILD}")


if __name__ == "__main__":
    main()
