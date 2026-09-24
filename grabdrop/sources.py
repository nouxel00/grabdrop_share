"""Choix de ce qui est attrapé au GRAB.

Priorité (choisie pour GrabDrop) :
1. fichiers et dossiers sélectionnés dans l'Explorateur au premier plan ;
2. sinon, ce qui a été copié (Ctrl+C) récemment : fichiers, texte ou image ;
3. sinon, une capture d'écran.
Un presse-papiers ancien n'est jamais envoyé, et chaque copie ne part qu'une fois.
"""

from __future__ import annotations

import io
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from grabdrop import platform_win
from grabdrop.items import IMAGE, TEXT, Item, files_item

RECENT_COPY_S = 30.0


class ClipboardWatcher:
    """Retient quand l'utilisateur a copié quelque chose pour la dernière fois."""

    def __init__(self, poll_s: float = 0.25) -> None:
        self._poll_s = poll_s
        self._lock = threading.Lock()
        self._seq = platform_win.clipboard_sequence()
        self._changed_at: float | None = None  # rien de copié depuis le lancement
        self._writing = False
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="grabdrop-clipboard", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def copied_within(self, seconds: float) -> bool:
        self._poll()
        with self._lock:
            return self._changed_at is not None and time.monotonic() - self._changed_at <= seconds

    def consume(self) -> None:
        """Cette copie a été attrapée : elle ne le sera pas une seconde fois."""
        with self._lock:
            self._changed_at = None

    @contextmanager
    def own_write(self) -> Iterator[None]:
        """À utiliser quand GrabDrop remplit le presse-papiers (réception) : ce n'est pas une copie de l'utilisateur."""
        with self._lock:
            self._writing = True
        try:
            yield
        finally:
            with self._lock:
                self._seq = platform_win.clipboard_sequence()
                self._writing = False

    def _run(self) -> None:
        while not self._stop.wait(self._poll_s):
            self._poll()

    def _poll(self) -> None:
        seq = platform_win.clipboard_sequence()
        with self._lock:
            if seq != self._seq and not self._writing:
                self._seq = seq
                self._changed_at = time.monotonic()


def grab_content(watcher: ClipboardWatcher | None, recent_s: float = RECENT_COPY_S) -> Item:
    selection = platform_win.explorer_selection()
    if selection:
        item = files_item(selection)
        if item:
            return item

    if watcher and watcher.copied_within(recent_s):
        item = _clipboard_item()
        if item:
            watcher.consume()
            return item

    from grabdrop.capture import capture_screen  # import tardif : mss n'est utile qu'ici

    return capture_screen()


def _clipboard_item() -> Item | None:
    content = platform_win.read_clipboard()
    if content is None:
        return None
    kind, value = content
    if kind == "files":
        return files_item(value)
    if kind == "text":
        return Item(kind=TEXT, name="texte", mime="text/plain; charset=utf-8", data=value.encode("utf-8"))
    png = io.BytesIO()
    value.save(png, "PNG")
    return Item(kind=IMAGE, name=f"image_{datetime.now():%Y%m%d_%H%M%S}.png", mime="image/png", data=png.getvalue())
