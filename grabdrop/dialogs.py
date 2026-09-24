"""Petites fenêtres (tkinter) : affichage et saisie du code d'appairage.

Chaque fenêtre tourne dans son propre thread avec sa propre instance Tk,
pour ne pas bloquer la caméra ni l'icône.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import simpledialog
from typing import Callable

from grabdrop.pairing import format_short_code


def show_pairing_code(code: str, expires_in_s: float, is_finished: Callable[[], bool]) -> None:
    """Affiche le code avec un compte à rebours ; se ferme seule une fois l'appairage terminé ou expiré."""

    def run() -> None:
        deadline = time.monotonic() + expires_in_s
        root = tk.Tk()
        root.title("GrabDrop – appairage")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        tk.Label(root, text="Code d'appairage", font=("Segoe UI", 11)).pack(padx=30, pady=(18, 0))
        tk.Label(root, text=format_short_code(code), font=("Segoe UI", 32, "bold")).pack(padx=30)
        hint = "Sur l'autre PC : icône GrabDrop → « Rejoindre un groupe… »\nou  python -m grabdrop pair " + code
        tk.Label(root, text=hint, font=("Segoe UI", 9), justify="center").pack(padx=30, pady=(4, 0))
        countdown = tk.Label(root, font=("Segoe UI", 9), fg="#666")
        countdown.pack(pady=(6, 14))

        def tick() -> None:
            remaining = deadline - time.monotonic()
            if is_finished() or remaining <= 0:
                root.destroy()
                return
            countdown.config(text=f"Valable encore {int(remaining) // 60}:{int(remaining) % 60:02d}")
            root.after(500, tick)

        tick()
        root.mainloop()

    threading.Thread(target=run, name="grabdrop-pair-window", daemon=True).start()


def ask_pairing_code(on_code: Callable[[str], None]) -> None:
    """Demande le code affiché par l'autre appareil, puis appelle `on_code` (hors du thread de la fenêtre)."""

    def run() -> None:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        code = simpledialog.askstring(
            "GrabDrop – rejoindre un groupe",
            "Code à 6 chiffres affiché par l'autre appareil\n(icône GrabDrop → « Appairer un nouvel appareil… ») :",
            parent=root,
        )
        root.destroy()
        if code and code.strip():
            on_code(code.strip())

    threading.Thread(target=run, name="grabdrop-join-window", daemon=True).start()
