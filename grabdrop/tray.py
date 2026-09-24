"""Icône dans la zone de notification (barre des tâches)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pystray
from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from grabdrop.agent import Agent

# Couleur de l'icône selon l'état
IDLE, HOLDING, PAUSED = (37, 99, 235), (245, 158, 11), (148, 163, 184)


def make_icon(color: tuple[int, int, int], size: int = 64) -> Image.Image:
    """Pastille colorée avec une main stylisée (quatre doigts et un pouce)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    d.rounded_rectangle((2 * s, 2 * s, 62 * s, 62 * s), radius=14 * s, fill=color)
    white = (255, 255, 255)
    d.rounded_rectangle((18 * s, 30 * s, 46 * s, 54 * s), radius=8 * s, fill=white)  # paume
    for i, top in enumerate((14, 10, 12, 18)):  # doigts
        x = 18 * s + i * 7.5 * s
        d.rounded_rectangle((x, top * s, x + 6 * s, 38 * s), radius=3 * s, fill=white)
    d.rounded_rectangle((8 * s, 30 * s, 22 * s, 38 * s), radius=4 * s, fill=white)  # pouce
    return img


class Tray:
    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self._state = IDLE
        self._icon = pystray.Icon("GrabDrop", make_icon(IDLE), "GrabDrop", menu=self._menu())

    def start(self) -> None:
        threading.Thread(target=self._icon.run, name="grabdrop-tray", daemon=True).start()

    def stop(self) -> None:
        self._icon.stop()

    def notify(self, message: str) -> None:
        try:
            self._icon.notify(message, "GrabDrop")
        except Exception:
            pass  # notifications désactivées : le message reste dans le journal

    def refresh(self) -> None:
        """Met à jour la couleur, l'info-bulle et les textes du menu."""
        if not self._icon.visible:
            return  # icône pas encore affichée
        a = self.agent
        state = PAUSED if a.controls.paused else HOLDING if a.held.peek() else IDLE
        if state != self._state:
            self._state = state
            self._icon.icon = make_icon(state)
        self._icon.title = f"GrabDrop – {a.status_text()}"[:127]
        self._icon.update_menu()

    def _menu(self) -> pystray.Menu:
        a = self.agent
        item = pystray.MenuItem
        return pystray.Menu(
            item(lambda _: f"GrabDrop sur {a.config.device_name}", None, enabled=False),
            item(lambda _: a.peers_text(), None, enabled=False),
            item(lambda _: a.held_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("Mettre la caméra en pause", lambda: a.toggle_pause(), checked=lambda _: a.controls.paused),
            item("Afficher l'aperçu caméra", lambda: a.toggle_preview(), checked=lambda _: a.controls.preview),
            pystray.Menu.SEPARATOR,
            item("Appairer un nouvel appareil…", lambda: a.start_pairing()),
            item("Rejoindre un groupe…", lambda: a.ask_join()),
            pystray.Menu.SEPARATOR,
            item("Ouvrir les fichiers reçus", lambda: a.open_received_folder()),
            item("Lancer au démarrage de Windows", lambda: a.toggle_autostart(),
                 checked=lambda _: a.autostart_enabled(), visible=a.autostart_supported()),
            pystray.Menu.SEPARATOR,
            item("Quitter", lambda: a.quit()),
        )
