"""Animations à l'écran.

GRAB : une vignette de l'objet attrapé apparaît au centre de l'écran puis
rétrécit vers le bas en s'effaçant, comme saisie par la main.
DROP : l'objet reçu surgit du bas, grandit jusqu'au centre, puis s'efface.

Les fenêtres d'animation ne prennent jamais le focus et laissent passer les
clics : on peut continuer à taper pendant l'animation, et l'Explorateur reste
au premier plan pour le GRAB suivant.
"""

from __future__ import annotations

import io
import logging
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageTk

from grabdrop import platform_win
from grabdrop.items import FILES, IMAGE, SCREENSHOT, TEXT, Item
from grabdrop.ui import ui

log = logging.getLogger("grabdrop")

THUMB_MAX = 420
FRAME_MS = 15
CARD_BG, CARD_FG, CARD_MUTED, CARD_BORDER = (255, 255, 255), (30, 30, 30), (110, 110, 110), (200, 200, 200)
ACCENT = (37, 99, 235)


# --- Vignettes -----------------------------------------------------------------------


def thumbnail_for(item: Item) -> Image.Image:
    """Image représentant l'objet (créée hors du thread d'interface)."""
    try:
        if item.kind in (SCREENSHOT, IMAGE) and item.data:
            img = Image.open(io.BytesIO(item.data)).convert("RGB")
            img.thumbnail((THUMB_MAX, THUMB_MAX))
            return _framed(img)
        if item.kind == TEXT:
            return _text_card(item.data.decode("utf-8", errors="replace"))
    except Exception:
        log.debug("vignette impossible", exc_info=True)
    return _files_card(item)


def _framed(img: Image.Image, border: int = 6) -> Image.Image:
    card = Image.new("RGB", (img.width + 2 * border, img.height + 2 * border), CARD_BG)
    card.paste(img, (border, border))
    ImageDraw.Draw(card).rectangle((0, 0, card.width - 1, card.height - 1), outline=CARD_BORDER)
    return card


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _text_card(text: str) -> Image.Image:
    w, h, pad = THUMB_MAX, 170, 22
    card = Image.new("RGB", (w, h), CARD_BG)
    d = ImageDraw.Draw(card)
    d.rectangle((0, 0, w - 1, h - 1), outline=CARD_BORDER)
    d.rectangle((0, 0, 6, h), fill=ACCENT)
    d.text((pad, 14), "“", font=_font(44, bold=True), fill=ACCENT)
    font = _font(20)
    lines, line = [], ""
    for word in " ".join(text.split()).split(" "):
        candidate = f"{line} {word}".strip()
        if d.textlength(candidate, font=font) <= w - 2 * pad - 30:
            line = candidate
        else:
            lines.append(line)
            line = word
        if len(lines) == 3:
            break
    if line and len(lines) < 3:
        lines.append(line)
    if len(" ".join(lines)) < len(" ".join(text.split())):
        lines[-1] = lines[-1].rstrip() + " …"
    for i, l in enumerate(lines):
        d.text((pad + 30, 30 + i * 30), l, font=font, fill=CARD_FG)
    return card


def _files_card(item: Item) -> Image.Image:
    w, h = THUMB_MAX, 130
    card = Image.new("RGB", (w, h), CARD_BG)
    d = ImageDraw.Draw(card)
    d.rectangle((0, 0, w - 1, h - 1), outline=CARD_BORDER)
    is_folder = len({Path(f.path).parts[0] for f in item.files}) == 1 and len(item.files) > 1
    if is_folder:  # dossier
        d.rounded_rectangle((24, 38, 104, 100), radius=6, fill=(250, 190, 60))
        d.rounded_rectangle((24, 30, 60, 46), radius=4, fill=(250, 190, 60))
    else:  # document(s)
        for dx in ((8, 4, 0) if len(item.files) > 1 else (0,)):
            d.rounded_rectangle((34 + dx, 22 - dx, 94 + dx, 104 - dx), radius=6, fill=CARD_BG, outline=ACCENT, width=3)
        for y in (48, 62, 76):
            d.line((46, y, 82, y), fill=ACCENT, width=3)
    title = item.name if len(item.name) <= 26 else item.name[:25] + "…"
    d.text((128, 34), title, font=_font(22, bold=True), fill=CARD_FG)
    d.text((128, 72), item.describe(), font=_font(17), fill=CARD_MUTED)
    return card


# --- Animations ------------------------------------------------------------------------


def play_grab(item: Item) -> None:
    _play(thumbnail_for(item), grab=True)


def play_drop(item: Item) -> None:
    _play(thumbnail_for(item), grab=False)


def _play(image: Image.Image, grab: bool) -> None:
    left, top, width, height = platform_win.monitor_under_cursor()
    center = (left + width / 2, top + height / 2)
    hand = (left + width / 2, top + height - 60)  # « la main » : en bas, au centre
    start_scale = min(1.0, 0.45 * width / image.width, 0.45 * height / image.height) * 1.6

    if grab:
        keyframes = [(0.0, center, start_scale, 0.97), (0.12, center, start_scale * 1.04, 0.97),
                     (0.5, hand, 0.08, 0.0)]
    else:
        keyframes = [(0.0, hand, 0.08, 0.0), (0.38, center, start_scale, 0.97),
                     (1.3, center, start_scale, 0.97), (1.6, center, start_scale * 0.96, 0.0)]
    ui().call(lambda root: _animate(root, image, keyframes))


def _animate(root: tk.Tk, image: Image.Image, keyframes: list) -> None:
    win = tk.Toplevel(root)
    win.withdraw()  # styles « sans focus » posés AVANT le premier affichage, sinon la fenêtre vole le focus
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", 0.0)
    label = tk.Label(win, bd=0)
    label.pack()
    win.update_idletasks()
    platform_win.make_overlay_window(win.winfo_id())

    started = time.monotonic()
    duration = keyframes[-1][0]
    shown = False

    def step() -> None:
        nonlocal shown
        t = time.monotonic() - started
        if t >= duration:
            win.destroy()
            return
        (x, y), scale, alpha = _interpolate(keyframes, t)
        w, h = max(8, int(image.width * scale)), max(8, int(image.height * scale))
        frame = ImageTk.PhotoImage(image.resize((w, h), Image.BILINEAR), master=win)
        label.configure(image=frame)
        win.frame_image = frame  # garder la référence (sinon l'image disparaît)
        win.geometry(f"{w}x{h}+{int(x - w / 2)}+{int(y - h / 2)}")
        win.attributes("-alpha", max(0.0, min(1.0, alpha)))
        if not shown:
            win.deiconify()
            shown = True
        win.after(FRAME_MS, step)

    step()


def _interpolate(keyframes: list, t: float):
    for (t0, p0, s0, a0), (t1, p1, s1, a1) in zip(keyframes, keyframes[1:]):
        if t <= t1:
            u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            u = u * u * (3 - 2 * u)  # accélération puis décélération douces
            pos = (p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u)
            return pos, s0 + (s1 - s0) * u, a0 + (a1 - a0) * u
    _, p, s, a = keyframes[-1]
    return p, s, a
