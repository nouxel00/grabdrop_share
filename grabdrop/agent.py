"""Agent GrabDrop.

GRAB (main ouverte -> poing) : attrape la sélection de l'Explorateur, sinon ce
qui vient d'être copié, sinon une capture d'écran.
DROP (poing -> main ouverte) : récupère l'objet en main sur un autre appareil.

    python -m grabdrop                lance l'agent (icône dans la barre des tâches)
    python -m grabdrop pair           affiche un code à 6 chiffres pour appairer un autre appareil
    python -m grabdrop pair 123456    rejoint le groupe de l'appareil qui affiche ce code
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from grabdrop import platform_win
from grabdrop.config import Config, config_path, load_config, save_config
from grabdrop.crypto import Channel, format_code, new_pairing_code, parse_code
from grabdrop.deliver import Destinations, deliver
from grabdrop.gestures import Event
from grabdrop.items import HeldItem, human_size
from grabdrop.network import DEFAULT_PORT, Node, Peer, local_ip, local_ipv4_addresses
from grabdrop.pairing import (
    PAIRING_WINDOW_S,
    PairingAdvertiser,
    PairingError,
    PairingHost,
    format_short_code,
    join,
    new_short_code,
    normalize_short_code,
    qr_uri,
)
from grabdrop.sources import RECENT_COPY_S, ClipboardWatcher, grab_content

log = logging.getLogger("grabdrop")
LARGE_TRANSFER_BYTES = 20 * 1024 * 1024


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["run", *argv]  # « run » est la commande par défaut

    parser = argparse.ArgumentParser(prog="python -m grabdrop", description="GrabDrop : transférer d'un geste de la main")
    sub = parser.add_subparsers(dest="command", required=True)
    add_run_arguments(sub.add_parser("run", help="lancer l'agent (commande par défaut)"))
    pair = sub.add_parser("pair", help="appairer : sans code, en afficher un ; avec code, rejoindre l'autre appareil")
    pair.add_argument("code", nargs="*", help="code affiché par l'autre appareil")
    sub.add_parser("code", help="afficher le code de groupe complet (secours, si l'appairage court échoue)")
    args = parser.parse_args(argv)

    setup_logging()
    platform_win.set_app_id()
    config = load_config()
    if args.command == "pair":
        cmd_pair_join(config, " ".join(args.code)) if args.code else cmd_pair_host(config)
    elif args.command == "code":
        print(f"Code de groupe : {ensure_group_code(config)}")
        print("Sur l'autre PC :  python -m grabdrop pair <ce code>")
    else:
        Agent(config, args).run()


def add_run_arguments(p: argparse.ArgumentParser) -> None:
    from grabdrop.camera import add_camera_arguments

    add_camera_arguments(p)
    p.add_argument("--preview", action="store_true", help="afficher la fenêtre caméra dès le lancement")
    p.add_argument("--no-tray", action="store_true", help="pas d'icône dans la barre des tâches (console seule)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port réseau (défaut : {DEFAULT_PORT})")
    p.add_argument(
        "--peer", action="append", default=[], metavar="IP[:PORT]",
        help="adresse d'un autre PC, si la découverte automatique ne le trouve pas (répétable)",
    )
    p.add_argument("--no-discovery", action="store_true", help="désactiver la découverte automatique (mDNS)")
    p.add_argument("--no-ble", action="store_true", help="désactiver la découverte par Bluetooth")
    p.add_argument("--hold-seconds", type=float, default=20.0, help="durée pendant laquelle un objet attrapé reste disponible")
    p.add_argument("--recent-copy-seconds", type=float, default=RECENT_COPY_S,
                   help="une copie (Ctrl+C) plus ancienne n'est pas attrapée (défaut : 30 s)")
    p.add_argument("--images-out", type=Path, help="dossier des captures et images reçues (défaut : Images\\GrabDrop)")
    p.add_argument("--files-out", type=Path, help="dossier des fichiers reçus (défaut : Téléchargements\\GrabDrop)")
    p.add_argument("--no-open", action="store_true", help="ne pas ouvrir automatiquement ce qui est reçu")
    p.add_argument("--no-animations", action="store_true", help="pas d'animation à l'écran au GRAB et au DROP")


def setup_logging() -> None:
    """Journal dans la console (s'il y en a une) et dans un fichier (toujours)."""
    log.setLevel(logging.INFO)
    log_file = config_path().parent / "grabdrop.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(file_handler)
    if sys.stdout is not None:  # absent avec pythonw
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
        log.addHandler(console)


def fatal(message: str) -> None:
    log.error(message)
    if sys.stdout is None:
        platform_win.show_error_box(message)
    sys.exit(1)


def ensure_group_code(config: Config) -> str:
    if not config.pairing_code:
        config.pairing_code = new_pairing_code()
        save_config(config)
    return config.pairing_code


# --- Appairage en ligne de commande ----------------------------------------------


def cmd_pair_host(config: Config) -> None:
    group_code = ensure_group_code(config)
    node = Node(config, Channel(parse_code(group_code)), HeldItem(), port=0, discovery=False)
    node.start()
    short = new_short_code()
    host = PairingHost(short, group_code, config.device_name)
    node.pairing = host
    advertiser = PairingAdvertiser(node.port, config.device_id, config.device_name)
    print(f"\n    Code d'appairage :  {format_short_code(short)}\n")
    print(f"Sur l'autre PC :  python -m grabdrop pair {short}")
    print("(ou icône GrabDrop → « Rejoindre un groupe… »).")
    print("Sur un téléphone : app GrabDrop → « Appairer », puis scanner :")
    try:
        from grabdrop.dialogs import print_qr

        print_qr(qr_uri(host.qr_token, local_ipv4_addresses(), node.port, config.device_name))
    except UnicodeEncodeError:
        print("(la console ne peut pas afficher le QR : utilisez l'icône → « Appairer un nouvel appareil… »)")
    print(f"Valable {PAIRING_WINDOW_S // 60} minutes, un seul essai.")
    try:
        while host.active():
            host.finished.wait(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        advertiser.close()
        node.stop()
    if host.paired_with:
        print(f"Appairé avec « {host.paired_with} ».")
    else:
        sys.exit("Appairage non abouti (code expiré ou incorrect). Relancez  python -m grabdrop pair.")


def cmd_pair_join(config: Config, code: str) -> None:
    short = normalize_short_code(code)
    if short is None:  # code de groupe complet (secours)
        try:
            config.pairing_code = format_code(parse_code(code))
        except ValueError as e:
            sys.exit(f"Erreur : {e}. Vérifiez le code affiché par l'autre PC.")
        save_config(config)
        print(f"Code de groupe enregistré ({config_path()}).")
        return
    print("Recherche de l'appareil qui affiche le code…")
    try:
        result = join(short, config.device_id, config.device_name)
    except PairingError as e:
        sys.exit(f"Erreur : {e}.")
    config.pairing_code = result.group_code
    save_config(config)
    print(f"Appairé avec « {result.host_name} ». Si GrabDrop tourne déjà ici, il bascule tout seul sur ce groupe.")


# --- Agent -------------------------------------------------------------------------


class Agent:
    def __init__(self, config: Config, args: argparse.Namespace) -> None:
        from grabdrop.camera import CameraControls

        self.config = config
        self.args = args
        self.held = HeldItem(ttl_s=args.hold_seconds)
        self.watcher = ClipboardWatcher() if platform_win.IS_WINDOWS else None
        self.dest = Destinations(
            images=args.images_out or platform_win.pictures_dir() / "GrabDrop",
            files=args.files_out or platform_win.downloads_dir() / "GrabDrop",
            open_items=not args.no_open,
        )
        self.controls = CameraControls(
            preview=args.preview, close_quits=args.no_tray, retry_camera=not args.no_tray
        )
        self.tray = None
        self.node: Node | None = None
        self._worker = ThreadPoolExecutor(max_workers=1)  # une action à la fois, hors de la boucle caméra
        self._pairing: tuple[PairingHost, PairingAdvertiser] | None = None
        self._config_mtime = _mtime(config_path())
        self._identify_attempts: dict[str, float] = {}

    # --- cycle de vie

    def run(self) -> None:
        from grabdrop.camera import run_camera_loop

        had_code = bool(self.config.pairing_code)
        ensure_group_code(self.config)
        self.node = Node(
            self.config, Channel(parse_code(self.config.pairing_code)), self.held,
            port=self.args.port,
            static_peers=[_parse_peer(p) for p in self.args.peer],
            discovery=not self.args.no_discovery,
            on_peer_found=lambda peer: log.info(f"Appareil trouvé : {peer.name} ({peer.host})"),
        )
        self.node.set_fallback_peers([_parse_peer(p) for p in self.config.known_peers])
        try:
            self.node.start()
        except OSError:
            if _show_running_instance(self.args.port):  # déjà lancé : c'est sa fenêtre qui s'affiche
                log.info("GrabDrop tourne déjà : sa fenêtre est affichée.")
                sys.exit(0)
            fatal(f"Impossible d'écouter sur le port {self.args.port} : il est utilisé par un autre programme.")
        self.node.on_show = self.show_window
        if not self.args.no_ble:
            from grabdrop.ble import BleDiscovery

            self.node.ble = BleDiscovery(self.node.channel.ble_key, self.config.device_id, self.node.port, local_ip)
            self.node.ble.start()

        if self.watcher:
            self.watcher.start()
        if platform_win.IS_WINDOWS:
            from grabdrop.ui import ui

            ui()  # thread d'interface créé dès maintenant (fenêtres, animations)
        if not self.args.no_tray:
            from grabdrop.tray import Tray

            self.tray = Tray(self)
            self.tray.start()
        threading.Thread(target=self._housekeeping, name="grabdrop-housekeeping", daemon=True).start()

        log.info(f"GrabDrop actif sur « {self.config.device_name} » (port {self.node.port}).")
        log.info("Main ouverte -> poing : attraper. Poing -> main ouverte : déposer.")
        if not had_code:
            self.notify("Premier lancement : appairez vos appareils via l'icône GrabDrop "
                        "(« Appairer un nouvel appareil… » sur l'un, « Rejoindre un groupe… » sur l'autre).")
        if self.tray:
            log.info("Icône GrabDrop dans la zone de notification (clic : fenêtre ; clic droit : menu).")
            if not self.config.welcomed:  # tout premier lancement : montrer où est GrabDrop
                self.show_window()
                self.config.welcomed = True
                save_config(self.config)
                self._config_mtime = _mtime(config_path())
        else:
            log.info("'q' dans la fenêtre pour quitter." if self.args.preview else "Ctrl+C pour quitter.")

        try:
            run_camera_loop(
                self.args, on_event=self._on_event, controls=self.controls,
                title="GrabDrop - apercu", status=self.status_text, on_camera_problem=self.notify,
            )
        finally:
            self.controls.stop.set()
            self._worker.shutdown(wait=True)
            self._end_pairing()
            if self.watcher:
                self.watcher.stop()
            if self.node.ble:
                self.node.ble.stop()
            self.node.stop()
            if self.tray:
                self.tray.stop()
            from grabdrop.ui import shutdown_ui

            shutdown_ui()
            log.info("GrabDrop arrêté.")

    def quit(self) -> None:
        self.controls.stop.set()

    def show_window(self) -> None:
        """Fenêtre GrabDrop : état, actions, et où trouver l'icône (souvent masquée par Windows)."""
        if not platform_win.IS_WINDOWS:
            return
        from grabdrop.dialogs import show_status_window

        show_status_window(self)

    def camera_text(self) -> str:
        if self.controls.paused:
            return "en pause"
        return "active, gestes surveillés" + (" (aperçu ouvert)" if self.controls.preview else "")

    def _housekeeping(self) -> None:
        """Toutes les secondes : icône et annonce Bluetooth à jour, fin d'appairage, changement de groupe."""
        while not self.controls.stop.wait(1.0):
            try:
                if self._pairing and not self._pairing[0].active():
                    self._end_pairing()
                self._reload_config_if_changed()
                if self.node.ble:
                    self.node.ble.set_holding(self.held.peek() is not None)
                    self._identify_nearby()
                if self.tray:
                    self.tray.refresh()
            except Exception:
                log.exception("Erreur de maintenance")

    def _identify_nearby(self) -> None:
        """Appareils entendus en Bluetooth dont on ignore le nom : on le leur demande (Wi-Fi)."""
        now = time.monotonic()
        for b in self.node.ble.peers():
            tag = b.announcement.device_tag.hex()
            if tag in self.node.names or now - self._identify_attempts.get(tag, -1e9) < 30:
                continue
            self._identify_attempts[tag] = now
            peer = Peer("", b.announcement.host, b.announcement.host, b.announcement.port)
            threading.Thread(target=self.node.identify, args=(peer,), daemon=True).start()

    def _reload_config_if_changed(self) -> None:
        mtime = _mtime(config_path())
        if mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        fresh = load_config()
        if fresh.pairing_code and fresh.pairing_code != self.config.pairing_code:
            self._switch_group(fresh.pairing_code)

    def _switch_group(self, group_code: str) -> None:
        self.config.pairing_code = group_code
        self.config.known_peers = []  # adresses de l'ancien groupe : plus valables
        save_config(self.config)
        self._config_mtime = _mtime(config_path())
        self.node.set_fallback_peers([])
        self.node.change_group(Channel(parse_code(group_code)))
        self.held.clear()
        self.notify("Groupe d'appareils mis à jour.")

    # --- gestes

    def _on_event(self, event: Event) -> None:
        action = self.grab if event == Event.GRAB else self.drop
        self._worker.submit(_report_errors(action, self.notify))

    def grab(self) -> None:
        try:
            item = grab_content(self.watcher, self.args.recent_copy_seconds)
        except Exception as e:  # pilote graphique, session verrouillée...
            log.exception("GRAB impossible")
            return self.notify(f"Rien n'a pu être attrapé ({e}).", "error")
        self.held.hold(item)
        self._animate("play_grab", item)
        self.notify(f"En main : {item.describe()}. Déposez-le sur un autre appareil "
                    f"dans les {self.held.ttl_s:.0f} s.", "grab")

    def drop(self) -> None:
        for offer in self.node.find_offers():
            if offer.size >= LARGE_TRANSFER_BYTES:
                self.notify(f"Réception de {offer.describe()} depuis {offer.device_name}…")
            self.dest.files.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".grabdrop-", dir=self.dest.files))
            try:
                started = time.monotonic()
                item = self.node.claim(offer, staging)
                if item is None:
                    continue  # déjà pris par un autre appareil, ou transfert échoué
                message = deliver(item, staging, self.dest, self.watcher)
                self._animate("play_drop", item)
                elapsed = time.monotonic() - started
                if item.size >= LARGE_TRANSFER_BYTES:
                    message += f" ({human_size(int(item.size / max(elapsed, 1e-3)))}/s)"
                return self.notify(f"{message} — depuis {offer.device_name}", "drop")
            finally:
                shutil.rmtree(staging, ignore_errors=True)

        if self.held.peek():
            self.notify("Ce que vous tenez vient de ce PC : déposez-le sur l'autre appareil.", "error")
        elif not self.node.peers():
            self.notify("Aucun autre appareil GrabDrop trouvé sur le réseau.", "error")
        else:
            self.notify("Rien à déposer : aucun appareil n'a d'objet en main.", "error")

    # --- retours à l'utilisateur

    def _animate(self, animation: str, item) -> None:
        if self.args.no_animations or not platform_win.IS_WINDOWS:
            return
        try:
            from grabdrop import overlay

            getattr(overlay, animation)(item)
        except Exception:
            log.exception("Animation impossible")  # jamais bloquant pour le transfert

    def notify(self, message: str, sound: str | None = None) -> None:
        (log.warning if sound == "error" else log.info)(message)
        if sound and platform_win.IS_WINDOWS:
            import winsound

            kind = {"grab": winsound.MB_OK, "drop": winsound.MB_ICONASTERISK, "error": winsound.MB_ICONHAND}[sound]
            winsound.MessageBeep(kind)
        if self.tray:
            self.tray.notify(message)

    def peers_text(self) -> str:
        n = len(self.node.peers()) if self.node else 0
        return "Aucun autre appareil trouvé" if n == 0 else f"{n} appareil(s) connecté(s)"

    def ble_text(self) -> str:
        from grabdrop.ble import proximity

        ble = self.node.ble if self.node else None
        if ble is None:
            return "Bluetooth : désactivé (--no-ble)"
        if ble.status != "actif":
            return "Bluetooth : indisponible (désactivé dans Windows ?)"
        nearby = ble.peers()
        if not nearby:
            return "Bluetooth : aucun appareil à proximité"
        names = {**self.node.names, **{p.device_id[:8]: p.name for p in self.node.peers() if p.device_id}}
        first = nearby[0].announcement
        name = names.get(first.device_tag.hex(), "téléphone" if first.is_phone else first.host)
        return f"Bluetooth : {len(nearby)} à proximité, dont « {name} » ({proximity(nearby[0].rssi)})"

    def held_text(self) -> str:
        held = self.held.peek()
        if not held:
            return "Main vide"
        item, age = held
        return f"En main : {item.describe()} ({self.held.ttl_s - age:.0f} s)"

    def status_text(self) -> str:
        paused = " | caméra en pause" if self.controls.paused else ""
        return f"{self.peers_text()} | {self.held_text()}{paused}"

    # --- actions du menu

    def toggle_pause(self) -> None:
        self.controls.paused = not self.controls.paused
        self.notify("Caméra en pause." if self.controls.paused else "Caméra réactivée.")

    def toggle_preview(self) -> None:
        self.controls.preview = not self.controls.preview

    def open_received_folder(self) -> None:
        self.dest.files.mkdir(parents=True, exist_ok=True)
        if platform_win.IS_WINDOWS:
            os.startfile(self.dest.files)

    def start_pairing(self) -> None:
        from grabdrop.dialogs import show_pairing_code

        self._end_pairing()
        short = new_short_code()
        host = PairingHost(
            short, self.config.pairing_code, self.config.device_name,
            on_paired=lambda name: self._on_paired(host, name),
        )
        self.node.pairing = host
        self._pairing = (host, PairingAdvertiser(self.node.port, self.config.device_id, self.config.device_name))
        log.info(f"Code d'appairage : {format_short_code(short)} (valable {PAIRING_WINDOW_S // 60} min)")
        qr = qr_uri(host.qr_token, local_ipv4_addresses(), self.node.port, self.config.device_name)
        show_pairing_code(short, qr, PAIRING_WINDOW_S, lambda: not host.active())

    def _on_paired(self, host: PairingHost, name: str) -> None:
        if host.guest_address:  # téléphone appairé par QR : on retient son adresse en secours
            ip, port = host.guest_address
            entry = f"{ip}:{port}"
            self.config.known_peers = [p for p in self.config.known_peers if p != entry][-7:] + [entry]
            save_config(self.config)
            self._config_mtime = _mtime(config_path())
            self.node.set_fallback_peers([_parse_peer(p) for p in self.config.known_peers])
        self.notify(f"Appareil « {name} » ajouté au groupe.")

    def _end_pairing(self) -> None:
        if self._pairing:
            host, advertiser = self._pairing
            self._pairing = None
            if self.node and self.node.pairing is host:
                self.node.pairing = None
            host.cancel()
            advertiser.close()

    def ask_join(self) -> None:
        from grabdrop.dialogs import ask_pairing_code

        ask_pairing_code(lambda code: threading.Thread(target=self._join, args=(code,), daemon=True).start())

    def _join(self, code: str) -> None:
        short = normalize_short_code(code)
        if short is None:
            return self.notify("Le code doit comporter 6 chiffres.", "error")
        self.notify("Recherche de l'appareil qui affiche le code…")
        try:
            result = join(short, self.config.device_id, self.config.device_name)
        except PairingError as e:
            return self.notify(f"Appairage impossible : {e}.", "error")
        self.config.pairing_code = result.group_code
        save_config(self.config)
        self._config_mtime = _mtime(config_path())
        self._switch_group(result.group_code)
        self.notify(f"Appairé avec « {result.host_name} ».", "drop")

    def autostart_supported(self) -> bool:
        return platform_win.IS_WINDOWS

    def autostart_enabled(self) -> bool:
        return platform_win.autostart_command() is not None

    def toggle_autostart(self) -> None:
        if self.autostart_enabled():
            platform_win.set_autostart(None)
            return self.notify("GrabDrop ne se lancera plus au démarrage de Windows.")
        if getattr(sys, "frozen", False):  # version installée : GrabDrop.exe
            platform_win.set_autostart(f'"{sys.executable}"')
            return self.notify("GrabDrop se lancera à l'ouverture de session Windows.")
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        python = pythonw if pythonw.exists() else Path(sys.executable)
        # Le lancement se fait hors du dossier du projet : GrabDrop doit être installé (pip install -e .).
        check = subprocess.run([str(python), "-c", "import grabdrop"], cwd=Path.home(), capture_output=True)
        if check.returncode != 0:
            return self.notify("Installez d'abord GrabDrop dans l'environnement :  pip install -e .", "error")
        platform_win.set_autostart(f'"{python}" -m grabdrop')
        self.notify("GrabDrop se lancera à l'ouverture de session Windows.")


def _report_errors(action: Callable[[], None], notify: Callable[[str, str], None]) -> Callable[[], None]:
    """Sans cela, une exception dans le thread de travail passerait inaperçue."""

    def run() -> None:
        try:
            action()
        except Exception:
            log.error("Erreur inattendue :\n" + traceback.format_exc())
            notify("Erreur inattendue (détails dans le journal).", "error")

    return run


def _show_running_instance(port: int) -> bool:
    """GrabDrop tourne déjà sur ce PC : lui demander d'afficher sa fenêtre (plutôt qu'une erreur)."""
    import urllib.request

    platform_win.allow_any_foreground()  # la copie déjà lancée a le droit de passer au premier plan
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/local/show", data=b"", method="POST")
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200
    except OSError:
        return False


def _parse_peer(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":") if ":" in value else (value, "", "")
    return host, int(port) if port else DEFAULT_PORT


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


if __name__ == "__main__":
    main()
