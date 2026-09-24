# Fabrique le programme d'installation de GrabDrop pour Windows.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Résultat : packaging\dist\GrabDrop-Setup-<version>.exe
# Prérequis : l'environnement .venv du projet (pip install -e ".[dev]") et Inno Setup 6
# (winget install JRSoftware.InnoSetup). Avec -SkipInstaller, seul l'exécutable
# autonome est produit (packaging\dist\GrabDrop\GrabDrop.exe).

param([switch]$SkipInstaller)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$here = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

Write-Host "1/3 Préparation (icône, modèle de gestes, version)…"
& $python -m pip install --quiet "pyinstaller>=6"
& $python (Join-Path $here "prepare.py")
if ($LASTEXITCODE -ne 0) { throw "préparation échouée" }
$version = (Get-Content (Join-Path $here "build\version.txt")).Trim()

Write-Host "2/3 Exécutable autonome (PyInstaller)…"
& $python -m PyInstaller --noconfirm --clean --log-level WARN `
    --distpath (Join-Path $here "dist") --workpath (Join-Path $here "build\pyinstaller") `
    (Join-Path $here "grabdrop.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a échoué" }

if ($SkipInstaller) {
    Write-Host "Terminé : $(Join-Path $here 'dist\GrabDrop\GrabDrop.exe')"
    exit 0
}

Write-Host "3/3 Programme d'installation (Inno Setup)…"
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 introuvable : winget install JRSoftware.InnoSetup" }
& $iscc /Q "/DAppVersion=$version" (Join-Path $here "grabdrop.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup a échoué" }

Write-Host "Terminé : $(Join-Path $here "dist\GrabDrop-Setup-$version.exe")"
