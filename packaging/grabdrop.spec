# Recette PyInstaller : GrabDrop.exe (sans console) et ses bibliothèques, dans dist/GrabDrop/.
# Lancée par build.ps1, après prepare.py.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

HERE = Path(SPECPATH)
ROOT = HERE.parent
BUILD = HERE / "build"

# MediaPipe charge sa bibliothèque native (tasks/c/libmediapipe.dll) par ctypes : PyInstaller
# ne la voit pas tout seul.
binaries = collect_dynamic_libs("mediapipe")
datas = collect_data_files("mediapipe") + [(str(BUILD / "gesture_recognizer.task"), "models")]

hiddenimports = (
    collect_submodules("mediapipe.tasks.python")
    # WinRT (annonce Bluetooth) : modules importés à la demande.
    + collect_submodules("winrt.windows.devices.bluetooth")
    + ["winrt.windows.storage.streams", "winrt.windows.foundation", "winrt.windows.foundation.collections"]
    + ["pystray._win32", "win32timezone"]
)

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "IPython", "jupyter", "notebook", "PyQt5", "PySide6", "tkinter.test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GrabDrop",
    icon=str(BUILD / "grabdrop.ico"),
    version=str(BUILD / "version_info.txt"),
    console=False,  # application de la barre des tâches : pas de fenêtre de console
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="GrabDrop", upx=False)
