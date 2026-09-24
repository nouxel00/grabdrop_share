"""Thread d'interface unique pour toutes les fenêtres tkinter.

Tkinter exige que ses objets soient créés ET libérés dans le même thread :
sinon, « Tcl_AsyncDelete: async handler deleted by the wrong thread » fait
planter le processus. Toutes les fenêtres (appairage, saisie, animations)
passent donc par ce thread, qui garde une racine Tk cachée pour toute la durée
de vie de l'agent.
"""

from __future__ import annotations

import gc
import logging
import queue
import threading
import tkinter as tk
from typing import Callable

log = logging.getLogger("grabdrop")

_POLL_MS = 15


class UiThread:
    def __init__(self) -> None:
        self._queue: queue.Queue[Callable[[tk.Tk], None] | None] = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="grabdrop-ui", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def call(self, action: Callable[[tk.Tk], None]) -> None:
        """Exécute `action(racine)` dans le thread d'interface (sans attendre)."""
        self._queue.put(action)

    def shutdown(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)

    def _run(self) -> None:
        from grabdrop import platform_win

        platform_win.enable_dpi_awareness()
        previous = platform_win.foreground_window()
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        platform_win.make_overlay_window(root.winfo_id())
        # Tk active sa fenêtre racine à la création, même cachée : on rend la main.
        platform_win.restore_foreground(previous)
        self._ready.set()

        def poll() -> None:
            while True:
                try:
                    action = self._queue.get_nowait()
                except queue.Empty:
                    break
                if action is None:
                    root.quit()
                    return
                try:
                    action(root)
                except Exception:
                    log.exception("Erreur d'interface")
            root.after(_POLL_MS, poll)

        root.after(_POLL_MS, poll)
        root.mainloop()
        root.destroy()
        # Les widgets se référencent mutuellement (parent <-> enfants) : sans ce
        # ramassage ici, le ramasse-miettes les libérerait plus tard depuis un
        # autre thread, et avec eux l'interpréteur Tcl -> plantage.
        del poll
        gc.collect()
        del root  # l'interpréteur Tcl est libéré ici, dans ce thread
        gc.collect()


_instance: UiThread | None = None
_lock = threading.Lock()


def ui() -> UiThread:
    global _instance
    with _lock:
        if _instance is None:
            _instance = UiThread()
        return _instance


def shutdown_ui() -> None:
    global _instance
    with _lock:
        if _instance is not None:
            _instance.shutdown()
            _instance = None
