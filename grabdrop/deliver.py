"""Ce qui se passe quand un objet arrive (DROP réussi)."""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from grabdrop import platform_win
from grabdrop.items import FILES, IMAGE, SCREENSHOT, TEXT, Item, move_received_files, save_bytes
from grabdrop.sources import ClipboardWatcher

TEXT_PREVIEW_CHARS = 60


@dataclass
class Destinations:
    images: Path  # captures d'écran et images
    files: Path  # fichiers et dossiers
    open_items: bool = True  # ouvrir ce qui est reçu


def deliver(item: Item, staging: Path, dest: Destinations, watcher: ClipboardWatcher | None) -> str:
    """Enregistre / applique l'objet reçu et renvoie un message pour l'utilisateur."""
    if item.kind in (SCREENSHOT, IMAGE):
        path = save_bytes(item.data, item.name, dest.images, ".png")
        extra = ""
        if item.kind == IMAGE and platform_win.IS_WINDOWS:
            with _own_write(watcher):
                platform_win.write_clipboard_image(item.data)
            extra = " (aussi dans le presse-papiers)"
        if dest.open_items:
            open_file(path)
        return f"{'Capture d’écran' if item.kind == SCREENSHOT else 'Image'} enregistrée{extra} : {path}"

    if item.kind == TEXT:
        text = item.data.decode("utf-8", errors="replace")
        if platform_win.IS_WINDOWS:
            with _own_write(watcher):
                platform_win.write_clipboard_text(text)
        if dest.open_items and platform_win.is_single_url(text):
            webbrowser.open(text.strip())
            return f"Lien ouvert : {text.strip()}"
        return f"Texte reçu, collez-le avec Ctrl+V : « {_preview(text)} »"

    if item.kind == FILES or item.files:
        moved = move_received_files(staging, item.files, dest.files)
        if dest.open_items:
            platform_win.reveal_in_explorer(moved)
        where = moved[0] if len(moved) == 1 else dest.files
        return f"{item.describe().capitalize()} reçu(s) : {where}"

    # Type inconnu (version plus récente de l'autre côté) : on garde au moins les données.
    path = save_bytes(item.data, item.name, dest.files, Path(item.name).suffix)
    return f"Objet reçu : {path}"


def open_file(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def _own_write(watcher: ClipboardWatcher | None):
    return watcher.own_write() if watcher else nullcontext()


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= TEXT_PREVIEW_CHARS else flat[: TEXT_PREVIEW_CHARS - 1] + "…"
