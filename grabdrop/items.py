"""Objets transférables et objet « dans la main » de l'appareil."""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_EXTENSIONS = {"image/png": ".png"}


@dataclass
class Item:
    kind: str  # "screenshot" pour l'instant
    name: str  # nom de fichier suggéré
    mime: str
    data: bytes
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


def save_item(item: Item, out_dir: Path) -> Path:
    """Enregistre l'objet reçu dans `out_dir` sans jamais écraser un fichier existant.

    Le nom vient de l'autre appareil : on n'en garde que la partie « nom de
    fichier », débarrassée des caractères interdits (pas de ../ ni de C:\\).
    """
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(item.name.replace("\\", "/")).name).strip(" .")
    stem, suffix = Path(name or "grabdrop").stem, Path(name).suffix
    suffix = _EXTENSIONS.get(item.mime, suffix)
    out_dir.mkdir(parents=True, exist_ok=True)
    path, n = out_dir / f"{stem}{suffix}", 1
    while path.exists():
        path, n = out_dir / f"{stem}_{n}{suffix}", n + 1
    path.write_bytes(item.data)
    return path


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
