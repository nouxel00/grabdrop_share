"""Petites fenêtres : affichage et saisie du code d'appairage.

Elles s'exécutent dans le thread d'interface unique (voir ui.py), sans bloquer
la caméra ni l'icône.
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import Callable

from grabdrop.pairing import format_short_code
from grabdrop.ui import ui


def show_pairing_code(code: str, qr_content: str, expires_in_s: float, is_finished: Callable[[], bool]) -> None:
    """Affiche le code (PC) et le QR (téléphone) avec un compte à rebours ; se ferme seule à la fin."""

    def build(root: tk.Tk) -> None:
        from PIL import ImageTk

        deadline = time.monotonic() + expires_in_s
        win = tk.Toplevel(root)
        win.title("GrabDrop – appairage")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        columns = tk.Frame(win)
        columns.pack(padx=24, pady=(16, 0))

        pc = tk.Frame(columns)
        pc.grid(row=0, column=0, padx=(0, 24), sticky="n")
        tk.Label(pc, text="Autre PC", font=("Segoe UI", 11, "bold")).pack()
        tk.Label(pc, text=format_short_code(code), font=("Segoe UI", 32, "bold")).pack(pady=(24, 0))
        hint = "Icône GrabDrop →\n« Rejoindre un groupe… »\nou  python -m grabdrop pair " + code
        tk.Label(pc, text=hint, font=("Segoe UI", 9), justify="center").pack(pady=(8, 0))

        phone = tk.Frame(columns)
        phone.grid(row=0, column=1, sticky="n")
        tk.Label(phone, text="Téléphone", font=("Segoe UI", 11, "bold")).pack()
        qr_image = ImageTk.PhotoImage(make_qr_image(qr_content, box_size=5), master=win)
        tk.Label(phone, image=qr_image).pack()
        win.qr_image = qr_image  # garder une référence tant que la fenêtre existe
        tk.Label(phone, text="App GrabDrop → « Appairer »", font=("Segoe UI", 9)).pack()

        countdown = tk.Label(win, font=("Segoe UI", 9), fg="#666")
        countdown.pack(pady=(10, 14))

        def tick() -> None:
            remaining = deadline - time.monotonic()
            if is_finished() or remaining <= 0:
                win.destroy()
                return
            countdown.config(text=f"Valable encore {int(remaining) // 60}:{int(remaining) % 60:02d}")
            win.after(500, tick)

        tick()

    ui().call(build)


def ask_pairing_code(on_code: Callable[[str], None]) -> None:
    """Demande le code affiché par l'autre appareil, puis appelle `on_code` (dans le thread d'interface)."""

    def build(root: tk.Tk) -> None:
        win = tk.Toplevel(root)
        win.title("GrabDrop – rejoindre un groupe")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        tk.Label(
            win, justify="center", font=("Segoe UI", 10),
            text="Code à 6 chiffres affiché par l'autre PC\n(icône GrabDrop → « Appairer un nouvel appareil… »)",
        ).pack(padx=24, pady=(16, 8))
        entry = tk.Entry(win, font=("Segoe UI", 20), width=8, justify="center")
        entry.pack(padx=24)

        def submit(_event=None) -> None:
            code = entry.get().strip()
            win.destroy()
            if code:
                on_code(code)

        buttons = tk.Frame(win)
        buttons.pack(pady=14)
        tk.Button(buttons, text="Rejoindre", width=12, command=submit).pack(side="left", padx=4)
        tk.Button(buttons, text="Annuler", width=12, command=win.destroy).pack(side="left", padx=4)
        entry.bind("<Return>", submit)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.after(50, entry.focus_force)

    ui().call(build)


def make_qr_image(content: str, box_size: int = 5):
    import qrcode

    qr = qrcode.QRCode(border=2, box_size=box_size, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(content)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image()


def print_qr(content: str) -> None:
    """QR en caractères dans la console."""
    import qrcode

    qr = qrcode.QRCode(border=2)
    qr.add_data(content)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
