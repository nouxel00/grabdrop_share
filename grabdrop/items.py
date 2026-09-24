"""Objets transférables et objet « dans la main » de l'appareil."""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

# Types d'objets
SCREENSHOT, IMAGE, TEXT, FILES = "screenshot", "image", "text", "files"

_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


@dataclass
class FileEntry:
    path: str  # chemin relatif, séparateur "/" (ex. "Dossier/sous/fichier.txt")
    size: int
    source: Path | None = None  # fichier sur disque (côté expéditeur, ou fichier reçu)


@dataclass
class Item:
    kind: str  # SCREENSHOT, IMAGE, TEXT ou FILES
    name: str  # nom affichable / nom de fichier suggéré
    mime: str = ""
    data: bytes = b""  # contenu en mémoire (capture, image, texte)
    files: list[FileEntry] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def size(self) -> int:
        return len(self.data) + sum(f.size for f in self.files)

    def describe(self) -> str:
        return describe(self.kind, self.name, self.size, len(self.files))


def describe(kind: str, name: str, size: int, count: int = 0) -> str:
    if kind == SCREENSHOT:
        return f"capture d'écran ({human_size(size)})"
    if kind == IMAGE:
        return f"image copiée ({human_size(size)})"
    if kind == TEXT:
        return "texte copié"
    if count == 1:
        return f"« {name} » ({human_size(size)})"
    return f"{count} fichiers ({human_size(size)})"


def human_size(n: int) -> str:
    for unit in ("octets", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "octets" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    raise AssertionError


def files_item(paths: Iterable[Path]) -> Item | None:
    """Objet FILES à partir de fichiers et dossiers (parcourus récursivement)."""
    entries: list[FileEntry] = []
    tops = []
    for top in paths:
        top = Path(top)
        if top.is_file():
            entries.append(FileEntry(top.name, top.stat().st_size, top))
            tops.append(top)
        elif top.is_dir():
            tops.append(top)
            for root, dirs, names in os.walk(top):  # ne suit pas les liens de dossiers
                dirs.sort()
                for n in sorted(names):
                    p = Path(root) / n
                    try:
                        entries.append(FileEntry(p.relative_to(top.parent).as_posix(), p.stat().st_size, p))
                    except OSError:
                        pass  # fichier illisible ou disparu : ignoré
    if not entries:
        return None
    name = tops[0].name if len(tops) == 1 else f"{len(tops)} éléments"
    return Item(kind=FILES, name=name, files=entries)


def safe_name(name: str, default: str = "grabdrop") -> str:
    """Nom de fichier sûr sous Windows comme ailleurs."""
    name = _FORBIDDEN_CHARS.sub("_", name).strip(" .")
    if not name:
        return default
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        name = "_" + name
    return name


def safe_relative_path(path: str) -> PurePosixPath:
    """Chemin relatif venant d'un autre appareil, rendu inoffensif.

    Pas de chemin absolu, de lecteur (C:) ni de « .. » : le résultat reste
    toujours à l'intérieur du dossier de réception.
    """
    parts = [p for p in re.split(r"[\\/]+", path) if p not in ("", ".", "..")]
    return PurePosixPath(*[safe_name(p, "_") for p in parts]) if parts else PurePosixPath("grabdrop")


def unique_path(path: Path) -> Path:
    """`path` s'il est libre, sinon « nom (1).ext », « nom (2).ext »..."""
    n = 1
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate


def save_bytes(data: bytes, name: str, out_dir: Path, suffix: str) -> Path:
    """Enregistre `data` dans `out_dir` sans jamais écraser un fichier existant."""
    stem = Path(safe_name(Path(name.replace("\\", "/")).name)).stem
    out_dir.mkdir(parents=True, exist_ok=True)
    path = unique_path(out_dir / f"{stem}{suffix}")
    path.write_bytes(data)
    return path


def move_received_files(staging: Path, files: list[FileEntry], out_dir: Path) -> list[Path]:
    """Déplace des fichiers reçus (dans `staging`) vers `out_dir`.

    Chaque élément de premier niveau (fichier ou dossier) est renommé s'il
    existe déjà, sans rien écraser. Renvoie les éléments de premier niveau créés.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tops = list(dict.fromkeys(PurePosixPath(f.path).parts[0] for f in files))
    moved = []
    for top in tops:
        dest = unique_path(out_dir / top)
        shutil.move(str(staging / top), str(dest))
        moved.append(dest)
    return moved


class HeldItem:
    """L'objet attrapé sur cet appareil, en attente d'un DROP sur un autre.

    Il expire après `ttl_s` secondes et ne peut être récupéré qu'une fois.
    Accès concurrents possibles (boucle caméra + serveur réseau) : tout passe par un verrou.
    """

    def __init__(self, ttl_s: float = 20.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._item: Item | None = None
        self._since = 0.0

    def hold(self, item: Item) -> None:
        with self._lock:
            self._item, self._since = item, self._clock()

    def peek(self) -> tuple[Item, float] | None:
        """(objet, âge en secondes), ou None si rien en main ou expiré."""
        with self._lock:
            self._expire()
            return (self._item, self._clock() - self._since) if self._item else None

    def take(self, item_id: str) -> Item | None:
        """Retire l'objet s'il correspond à `item_id` : le premier qui le réclame l'obtient."""
        with self._lock:
            self._expire()
            if self._item is None or self._item.id != item_id:
                return None
            item, self._item = self._item, None
            return item

    def clear(self) -> None:
        with self._lock:
            self._item = None

    def _expire(self) -> None:
        if self._item is not None and self._clock() - self._since > self.ttl_s:
            self._item = None
