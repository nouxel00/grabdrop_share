"""Intégration Windows : sélection de l'Explorateur, presse-papiers, dossiers connus.

Toutes les fonctions se dégradent proprement hors Windows (résultat vide).
"""

from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
_EXPLORER_CLASSES = ("CabinetWClass", "ExploreWClass")


# --- Sélection dans l'Explorateur --------------------------------------------


def explorer_selection() -> list[Path]:
    """Fichiers et dossiers sélectionnés dans la fenêtre de l'Explorateur au premier plan.

    Renvoie [] si l'Explorateur n'est pas au premier plan, si rien n'est
    sélectionné, ou en cas de doute (mieux vaut ne rien envoyer que les mauvais fichiers).
    """
    if not IS_WINDOWS:
        return []
    import pythoncom
    import win32com.client
    import win32gui

    foreground = win32gui.GetForegroundWindow()
    if win32gui.GetClassName(foreground) not in _EXPLORER_CLASSES:
        return []

    pythoncom.CoInitialize()  # appelé depuis un thread de travail
    try:
        windows = []
        for w in win32com.client.Dispatch("Shell.Application").Windows():
            try:
                if w.HWND == foreground:
                    windows.append(w)
            except Exception:
                continue
        # Windows 11 : chaque onglet est une « fenêtre » avec le même HWND.
        if len(windows) > 1:
            active = win32gui.FindWindowEx(foreground, 0, "ShellTabWindowClass", None)
            windows = [w for w in windows if _tab_window(w) == active]
        if len(windows) != 1:
            return []
        selected = windows[0].Document.SelectedItems()
        paths = [Path(selected.Item(i).Path) for i in range(selected.Count)]
        # Éléments virtuels (« Ce PC », corbeille...) exclus.
        return [p for p in paths if p.exists()]
    except Exception:
        return []
    finally:
        pythoncom.CoUninitialize()


def _tab_window(shell_window) -> int | None:
    """HWND de l'onglet (ShellTabWindowClass) correspondant à une fenêtre Shell."""
    import pythoncom
    from win32com.shell import shell

    try:
        provider = shell_window._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
        browser = provider.QueryService(shell.SID_STopLevelBrowser, shell.IID_IShellBrowser)
        return browser.GetWindow()
    except Exception:
        return None


def reveal_in_explorer(paths: list[Path]) -> None:
    """Ouvre le dossier parent dans l'Explorateur avec `paths` sélectionnés."""
    if not paths:
        return
    if not IS_WINDOWS:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(paths[0].parent)])
        return
    import pythoncom
    from win32com.shell import shell

    pythoncom.CoInitialize()
    try:
        folder = shell.SHParseDisplayName(str(paths[0].parent), 0)[0]
        children = [shell.SHParseDisplayName(str(p), 0)[0] for p in paths]
        shell.SHOpenFolderAndSelectItems(folder, children, 0)
    except Exception:
        subprocess.Popen(["explorer", f"/select,{paths[0]}"])
    finally:
        pythoncom.CoUninitialize()


# --- Dossiers ----------------------------------------------------------------


def downloads_dir() -> Path:
    return _known_folder("FOLDERID_Downloads", Path.home() / "Downloads")


def pictures_dir() -> Path:
    return _known_folder("FOLDERID_Pictures", Path.home() / "Pictures")


def _known_folder(folder_id: str, default: Path) -> Path:
    """Vrai emplacement du dossier (il peut être déplacé, par exemple dans OneDrive)."""
    if IS_WINDOWS:
        try:
            from win32com.shell import shell, shellcon

            return Path(shell.SHGetKnownFolderPath(getattr(shellcon, folder_id)))
        except Exception:
            pass
    return default


# --- Presse-papiers ------------------------------------------------------------


def clipboard_sequence() -> int:
    """Numéro incrémenté par Windows à chaque modification du presse-papiers."""
    if not IS_WINDOWS:
        return 0
    import win32clipboard

    return win32clipboard.GetClipboardSequenceNumber()


def read_clipboard() -> tuple[str, object] | None:
    """Contenu du presse-papiers : ("files", [Path]), ("text", str), ("image", PIL.Image) ou None.

    Priorité : fichiers copiés, puis texte, puis image. Exception : si le texte
    n'est qu'une adresse web et qu'une image est présente (« Copier l'image »
    d'un navigateur), on prend l'image.
    """
    if not IS_WINDOWS:
        return None
    from PIL import Image, ImageGrab

    content = _retry(ImageGrab.grabclipboard)  # liste de fichiers, image, ou None
    if isinstance(content, list):
        paths = [Path(p) for p in content if Path(p).exists()]
        return ("files", paths) if paths else None
    text = _retry(_clipboard_text)
    image = content if isinstance(content, Image.Image) else None
    if text and not (image is not None and is_single_url(text)):
        return "text", text
    if image is not None:
        return "image", image
    return None


def write_clipboard_text(text: str) -> None:
    import win32clipboard

    def write() -> None:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()

    _retry(write)


def write_clipboard_image(png: bytes) -> None:
    """Met une image dans le presse-papiers (format DIB universel + PNG pour la transparence)."""
    import win32clipboard
    from PIL import Image

    bmp = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(bmp, "BMP")
    dib = bmp.getvalue()[14:]  # un DIB est un BMP sans son en-tête de fichier
    png_format = win32clipboard.RegisterClipboardFormat("PNG")

    def write() -> None:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
            win32clipboard.SetClipboardData(png_format, png)
        finally:
            win32clipboard.CloseClipboard()

    _retry(write)


def _clipboard_text() -> str | None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return None
    finally:
        win32clipboard.CloseClipboard()


def is_single_url(text: str) -> bool:
    text = text.strip()
    return text.startswith(("http://", "https://")) and not any(c.isspace() for c in text)


def _retry(action, attempts: int = 5, delay_s: float = 0.05):
    """Le presse-papiers peut être momentanément verrouillé par une autre application."""
    for i in range(attempts):
        try:
            return action()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(delay_s)


# --- Lancement au démarrage ----------------------------------------------------

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "GrabDrop"


def autostart_command() -> str | None:
    """Commande enregistrée pour le démarrage de Windows, ou None."""
    if not IS_WINDOWS:
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            return winreg.QueryValueEx(key, _RUN_VALUE)[0]
    except OSError:
        return None


def set_autostart(command: str | None) -> None:
    """Active (commande donnée) ou désactive (None) le lancement à l'ouverture de session."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if command:
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, _RUN_VALUE)
            except FileNotFoundError:
                pass


def show_error_box(message: str) -> None:
    """Boîte d'erreur, utile quand GrabDrop tourne sans console (pythonw)."""
    if IS_WINDOWS:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "GrabDrop", 0x10)
