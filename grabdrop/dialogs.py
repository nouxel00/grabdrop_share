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


# --- Fenêtre GrabDrop (état et actions) -------------------------------------------------

_status_window: tk.Toplevel | None = None

_BLUE, _INK, _MUTED, _LINE, _TIP_BG = "#2563EB", "#0F172A", "#5B6475", "#E3E7EF", "#EEF3FF"


def show_status_window(agent) -> None:
    """Ouvre la fenêtre GrabDrop, ou la ramène au premier plan si elle est déjà ouverte."""

    def build(root: tk.Tk) -> None:
        global _status_window
        if _status_window is not None and _status_window.winfo_exists():
            _bring_to_front(_status_window)
            return
        from PIL import ImageTk

        from grabdrop import platform_win
        from grabdrop.tray import IDLE, make_icon

        win = tk.Toplevel(root, bg="white")
        _status_window = win
        win.title("GrabDrop")
        win.resizable(False, False)
        win.icon_image = ImageTk.PhotoImage(make_icon(IDLE, 64), master=win)
        win.iconphoto(False, win.icon_image)

        # En-tête : logo et nom de l'appareil
        head = tk.Frame(win, bg="white")
        head.pack(fill="x", padx=24, pady=(20, 12))
        win.logo = ImageTk.PhotoImage(make_icon(IDLE, 52), master=win)
        tk.Label(head, image=win.logo, bg="white").pack(side="left")
        titles = tk.Frame(head, bg="white")
        titles.pack(side="left", padx=(14, 0))
        tk.Label(titles, text="GrabDrop", font=("Segoe UI Semibold", 17), fg=_INK, bg="white").pack(anchor="w")
        tk.Label(titles, text=f"En marche sur « {agent.config.device_name} »", font=("Segoe UI", 10),
                 fg=_MUTED, bg="white").pack(anchor="w")

        # État, rafraîchi chaque seconde
        tk.Frame(win, height=1, bg=_LINE).pack(fill="x", padx=24)
        grid = tk.Frame(win, bg="white")
        grid.pack(fill="x", padx=24, pady=12)
        rows = {}
        for i, label in enumerate(("Appareils", "Bluetooth", "Caméra", "En main")):
            tk.Label(grid, text=label, font=("Segoe UI Semibold", 10), fg=_MUTED, bg="white").grid(
                row=i, column=0, sticky="w", pady=3, padx=(0, 16))
            rows[label] = tk.Label(grid, font=("Segoe UI", 10), fg=_INK, bg="white", anchor="w",
                                   justify="left", wraplength=330)
            rows[label].grid(row=i, column=1, sticky="w", pady=3)

        # Où est l'icône ? (Windows 11 la range dans les icônes cachées)
        tip = tk.Frame(win, bg=_TIP_BG, highlightthickness=0)
        tip.pack(fill="x", padx=24, pady=(4, 16))
        tk.Frame(tip, width=4, bg=_BLUE).pack(side="left", fill="y")
        tk.Label(
            tip, justify="left", wraplength=400, bg=_TIP_BG, fg=_INK, font=("Segoe UI", 9),
            text="GrabDrop tourne en arrière-plan : fermer cette fenêtre ne l'arrête pas.\n"
                 "Son icône (la main bleue) se trouve près de l'horloge, souvent cachée derrière "
                 "la flèche ^. Faites-la glisser sur la barre des tâches pour la garder visible.",
        ).pack(side="left", padx=12, pady=10)

        # Actions
        actions = tk.Frame(win, bg="white")
        actions.pack(fill="x", padx=24)
        preview_button = _button(actions, "", agent.toggle_preview)
        for text, command in (("Appairer un appareil", agent.start_pairing),
                              ("Fichiers reçus", agent.open_received_folder)):
            _button(actions, text, command).pack(side="left", padx=(0, 8))
        preview_button.pack(side="left")

        bottom = tk.Frame(win, bg="white")
        bottom.pack(fill="x", padx=24, pady=(14, 20))
        _button(bottom, "Quitter GrabDrop", agent.quit, danger=True).pack(side="left")
        _button(bottom, "Fermer", win.destroy, primary=True).pack(side="right")

        def refresh() -> None:
            if not win.winfo_exists():
                return
            rows["Appareils"].config(text=agent.peers_text())
            rows["Bluetooth"].config(text=agent.ble_text().removeprefix("Bluetooth : "))
            rows["Caméra"].config(text=agent.camera_text())
            rows["En main"].config(text=agent.held_text().removeprefix("En main : "))
            preview_button.config(text="Masquer l'aperçu" if agent.controls.preview else "Aperçu caméra")
            win.after(1000, refresh)

        refresh()
        win.update_idletasks()
        platform_win.show_in_taskbar(win.winfo_id())
        _bring_to_front(win)

    ui().call(build)


def _button(parent, text: str, command, primary: bool = False, danger: bool = False) -> tk.Button:
    # Principal : bleu plein ; secondaire : gris clair ; « Quitter » : texte rouge discret.
    bg = _BLUE if primary else ("white" if danger else "#EEF1F6")
    fg = "white" if primary else ("#B42318" if danger else _INK)
    return tk.Button(
        parent, text=text, command=command, font=("Segoe UI Semibold", 10), bg=bg, fg=fg,
        activebackground="#1D4ED8" if primary else "#E1E6EF", activeforeground=fg,
        relief="flat", bd=0, padx=14, pady=7, cursor="hand2",
    )


def _bring_to_front(win: tk.Toplevel) -> None:
    win.withdraw()  # réaffichage : applique le bouton de barre des tâches et passe au premier plan
    win.deiconify()
    win.lift()
    win.attributes("-topmost", True)
    win.after(400, lambda: win.winfo_exists() and win.attributes("-topmost", False))
    win.focus_force()
