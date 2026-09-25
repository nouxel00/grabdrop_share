"""Configuration locale : identité de l'appareil et code d'appairage."""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
        return base / "GrabDrop" / "config.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "grabdrop" / "config.json"


@dataclass
class Config:
    device_id: str
    device_name: str
    pairing_code: str | None = None
    # « ip:port » d'appareils appairés par QR (téléphones), en secours de la découverte mDNS
    known_peers: list[str] = field(default_factory=list)
    # La fenêtre GrabDrop s'ouvre d'elle-même au tout premier lancement (où est l'icône, etc.).
    welcomed: bool = False


def load_config(path: Path | None = None) -> Config:
    """Charge la configuration, en la créant (nouvel identifiant) au premier lancement."""
    path = path or config_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(Config)}
        return Config(**{k: v for k, v in data.items() if k in known})
    config = Config(device_id=uuid.uuid4().hex, device_name=socket.gethostname())
    save_config(config, path)
    return config


def save_config(config: Config, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")
