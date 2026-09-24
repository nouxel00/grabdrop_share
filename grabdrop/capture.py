"""Capture d'écran en mémoire (PNG)."""

from __future__ import annotations

import sys
from datetime import datetime

import mss
import mss.tools

from grabdrop.items import SCREENSHOT, Item


def capture_screen() -> Item:
    """Capture l'écran sous le curseur de la souris (l'écran principal par défaut)."""
    with mss.MSS() as sct:
        # mss rend le processus « DPI aware » : la position du curseur est lue
        # après, pour être en pixels physiques comme les écrans.
        monitor = _monitor_under_cursor(sct.monitors)
        shot = sct.grab(monitor)
        png = mss.tools.to_png(shot.rgb, shot.size)
    return Item(kind=SCREENSHOT, name=f"capture_{datetime.now():%Y%m%d_%H%M%S}.png", mime="image/png", data=png)


def _monitor_under_cursor(monitors: list[dict]) -> dict:
    # monitors[0] = tous les écrans réunis ; monitors[1] = écran principal.
    pos = _cursor_position()
    if pos:
        x, y = pos
        for m in monitors[1:]:
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                return m
    return monitors[1]


def _cursor_position() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes

    pt = ctypes.wintypes.POINT()
    return (pt.x, pt.y) if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)) else None
