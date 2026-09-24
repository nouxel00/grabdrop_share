"""Agent GrabDrop.

GRAB (main ouverte -> poing) : capture l'écran et la garde « en main ».
DROP (poing -> main ouverte) : récupère l'objet en main sur un autre appareil,
l'enregistre et l'ouvre.

    python -m grabdrop                lance l'agent
    python -m grabdrop pair CODE      rejoint le groupe d'un autre PC
    python -m grabdrop code           affiche le code d'appairage de ce PC
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from grabdrop.config import Config, config_path, load_config, save_config
from grabdrop.crypto import Channel, format_code, new_pairing_code, parse_code
from grabdrop.gestures import Event
from grabdrop.items import HeldItem, save_item
from grabdrop.network import DEFAULT_PORT, Node

DEFAULT_OUT = Path.home() / "Pictures" / "GrabDrop"


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["run", *argv]  # « run » est la commande par défaut

    parser = argparse.ArgumentParser(prog="python -m grabdrop", description="GrabDrop : transférer d'un geste de la main")
    sub = parser.add_subparsers(dest="command", required=True)
    add_run_arguments(sub.add_parser("run", help="lancer l'agent (commande par défaut)"))
    pair = sub.add_parser("pair", help="rejoindre le groupe d'un autre PC avec son code")
    pair.add_argument("code", nargs="+", help="code d'appairage affiché par l'autre PC")
    sub.add_parser("code", help="afficher le code d'appairage de ce PC")
    args = parser.parse_args(argv)

    config = load_config()
    if args.command == "pair":
        cmd_pair(config, " ".join(args.code))
    elif args.command == "code":
        print(f"Code d'appairage : {ensure_pairing_code(config)}")
    else:
        cmd_run(config, args)


def add_run_arguments(p: argparse.ArgumentParser) -> None:
    from grabdrop.camera import add_camera_arguments

    add_camera_arguments(p)
    p.add_argument("--preview", action="store_true", help="afficher la fenêtre caméra (réglage, débogage)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port réseau (défaut : {DEFAULT_PORT})")
    p.add_argument(
        "--peer", action="append", default=[], metavar="IP[:PORT]",
        help="adresse d'un autre PC, si la découverte automatique ne le trouve pas (répétable)",
    )
    p.add_argument("--no-discovery", action="store_true", help="désactiver la découverte automatique (mDNS)")
    p.add_argument("--hold-seconds", type=float, default=20.0, help="durée pendant laquelle un objet attrapé reste disponible")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"dossier de réception (défaut : {DEFAULT_OUT})")
    p.add_argument("--no-open", action="store_true", help="ne pas ouvrir automatiquement ce qui est reçu")


def ensure_pairing_code(config: Config) -> str:
    if not config.pairing_code:
        config.pairing_code = new_pairing_code()
        save_config(config)
    return config.pairing_code


def cmd_pair(config: Config, code: str) -> None:
    try:
        secret = parse_code(code)
    except ValueError as e:
        sys.exit(f"Erreur : {e}. Vérifiez le code affiché par l'autre PC.")
    config.pairing_code = format_code(secret)
    save_config(config)
    print(f"Appairage enregistré ({config_path()}).")
    print("Lancez maintenant : python -m grabdrop")


def cmd_run(config: Config, args: argparse.Namespace) -> None:
    from grabdrop.camera import run_camera_loop  # import lourd (MediaPipe), seulement ici

    had_code = bool(config.pairing_code)
    code = ensure_pairing_code(config)
    if not had_code:
        print("Nouveau groupe créé. Sur l'autre PC, exécutez :")
        print(f"    python -m grabdrop pair {code}\n")

    held = HeldItem(ttl_s=args.hold_seconds)
    node = Node(
        config, Channel(parse_code(code)), held,
        port=args.port,
        static_peers=[_parse_peer(p) for p in args.peer],
        discovery=not args.no_discovery,
        on_peer_found=lambda peer: print(f"Appareil trouvé : {peer.name} ({peer.host})"),
    )
    try:
        node.start()
    except OSError as e:
        sys.exit(f"Impossible d'écouter sur le port {args.port} ({e}). GrabDrop tourne-t-il déjà ?")

    actions = Actions(node, held, args)
    worker = ThreadPoolExecutor(max_workers=1)  # une action à la fois, hors de la boucle caméra

    def on_event(event: Event) -> None:
        worker.submit(_report_errors(actions.grab if event == Event.GRAB else actions.drop))

    print(f"GrabDrop actif sur « {config.device_name} » (port {node.port}).")
    print("Main ouverte -> poing : attraper l'écran. Poing -> main ouverte : déposer.")
    print("Ctrl+C pour quitter." if not args.preview else "'q' dans la fenêtre pour quitter.")
    try:
        run_camera_loop(args, on_event=on_event, preview=args.preview, title="GrabDrop - q pour quitter", status=actions.status)
    finally:
        worker.shutdown(wait=True)
        node.stop()
        print("GrabDrop arrêté.")


class Actions:
    def __init__(self, node: Node, held: HeldItem, args: argparse.Namespace) -> None:
        self.node, self.held, self.args = node, held, args

    def grab(self) -> None:
        from grabdrop.capture import capture_screen

        try:
            item = capture_screen()
        except Exception as e:  # pilote graphique, session verrouillée...
            return _say(f"GRAB : capture impossible ({e})", "error")
        self.held.hold(item)
        _say(f"GRAB : capture d'écran en main ({len(item.data) // 1024} Ko), "
             f"à déposer sur un autre appareil dans les {self.held.ttl_s:.0f} s", "grab")

    def drop(self) -> None:
        for offer in self.node.find_offers():
            item = self.node.claim(offer)
            if item is None:
                continue  # déjà pris par un autre appareil, ou expiré entre-temps
            path = save_item(item, self.args.out)
            _say(f"DROP : capture reçue de {offer.device_name} -> {path}", "drop")
            if not self.args.no_open:
                _open_file(path)
            return

        if self.held.peek():
            _say("DROP : la capture en main vient de ce PC ; déposez-la sur l'autre appareil", "error")
        elif not self.node.peers():
            _say("DROP : aucun autre appareil GrabDrop trouvé sur le réseau", "error")
        else:
            _say("DROP : rien à déposer (aucun appareil n'a d'objet en main)", "error")

    def status(self) -> str:
        n = len(self.node.peers())
        held = self.held.peek()
        in_hand = f"en main : capture ({self.held.ttl_s - held[1]:.0f} s)" if held else "main vide"
        return f"{n} appareil(s) connu(s) | {in_hand}"


def _report_errors(action: Callable[[], None]) -> Callable[[], None]:
    """Sans cela, une exception dans le thread de travail passerait inaperçue."""

    def run() -> None:
        try:
            action()
        except Exception:
            traceback.print_exc()
            _say("Erreur inattendue (détails ci-dessus)", "error")

    return run


def _parse_peer(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":") if ":" in value else (value, "", "")
    return host, int(port) if port else DEFAULT_PORT


def _say(message: str, sound: str) -> None:
    print(message)
    if sys.platform == "win32":
        import winsound

        kind = {"grab": winsound.MB_OK, "drop": winsound.MB_ICONASTERISK, "error": winsound.MB_ICONHAND}[sound]
        winsound.MessageBeep(kind)


def _open_file(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


if __name__ == "__main__":
    main()
