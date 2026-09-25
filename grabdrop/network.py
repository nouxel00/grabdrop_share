"""Échanges entre appareils : découverte (mDNS), serveur HTTP et client.

Protocole (tous les corps sont chiffrés par `Channel`) :
- POST /v1/offer : « as-tu quelque chose en main ? » -> description de l'objet, ou rien
- POST /v1/claim : « je prends l'objet X » -> l'objet (une seule fois), ou 410.
  La réponse est un flux chiffré par morceaux (voir crypto.StreamSealer) :
  en-tête JSON, contenu en mémoire, puis le contenu de chaque fichier.

Le modèle est « tiré » : c'est l'appareil qui voit le DROP qui interroge les
autres. Aucune donnée ne circule tant que personne ne dépose.
"""

from __future__ import annotations

import json
import logging
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

from grabdrop.ble import BleDiscovery
from grabdrop.config import Config
from grabdrop.crypto import CHUNK_BYTES, NONCE_BYTES, Channel, CryptoError, StreamOpener, StreamSealer
from grabdrop.items import FileEntry, HeldItem, Item, describe, safe_relative_path, unique_path
from grabdrop.pairing import PairingHost

SERVICE_TYPE = "_grabdrop._tcp.local."
DEFAULT_PORT = 47800
MAX_CLOCK_SKEW_S = 120  # âge max d'une requête (limite le rejeu)
MAX_REQUEST_BYTES = 64 * 1024
MAX_HEADER_BYTES = 16 * 1024 * 1024  # liste des fichiers
MAX_MEMORY_BYTES = 256 * 1024 * 1024  # capture, image ou texte (les fichiers, eux, vont sur disque)
TIMEOUT_S = 3.0
FALLBACK_TIMEOUT_S = 1.0  # appareil peut-être absent : ne pas ralentir le DROP

log = logging.getLogger("grabdrop")


@dataclass(frozen=True)
class Peer:
    device_id: str
    name: str
    host: str
    port: int
    fallback: bool = False  # adresse retenue à l'appairage, utilisée si mDNS ne trouve pas l'appareil

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class Offer:
    peer: Peer
    device_id: str
    device_name: str
    item_id: str
    kind: str
    name: str
    size: int
    count: int
    age_s: float

    def describe(self) -> str:
        return describe(self.kind, self.name, self.size, self.count)


class Node:
    """Un appareil GrabDrop : sert son objet en main et interroge les autres."""

    def __init__(
        self,
        config: Config,
        channel: Channel,
        held: HeldItem,
        port: int = DEFAULT_PORT,
        static_peers: list[tuple[str, int]] = (),
        discovery: bool = True,
        on_peer_found: Callable[[Peer], None] | None = None,
        host: str = "0.0.0.0",
    ) -> None:
        self.config = config
        self.channel = channel
        self.held = held
        self._host = host
        self._requested_port = port
        self._static_peers = [Peer("", f"{h}:{p}", h, p) for h, p in static_peers]
        self._fallback_peers: list[Peer] = []
        self._discovery = Discovery(config, channel.group_id, on_peer_found) if discovery else None
        self._server: ThreadingHTTPServer | None = None
        self.pairing: PairingHost | None = None  # fenêtre d'appairage en cours (voir pairing.py)
        self.ble: BleDiscovery | None = None  # découverte Bluetooth, facultative (voir ble.py)
        # Noms des appareils du groupe, par identifiant court (les annonces Bluetooth n'ont pas le nom).
        self.names: dict[str, str] = {}
        # Une seconde copie de GrabDrop lancée sur ce PC demande à la première de se montrer.
        self.on_show: Callable[[], None] | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else self._requested_port

    def start(self) -> None:
        handler = type("Handler", (_Handler,), {"node": self})
        self._server = _Server((self._host, self._requested_port), handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, name="grabdrop-http", daemon=True).start()
        if self._discovery:
            self._discovery.start(self.port)

    def stop(self) -> None:
        if self._discovery:
            self._discovery.stop()
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def change_group(self, channel: Channel) -> None:
        """Bascule vers un autre groupe (après un appairage) sans relancer le serveur."""
        self.channel = channel
        if self._discovery:
            on_peer_found = self._discovery._on_peer_found
            self._discovery.stop()
            self._discovery = Discovery(self.config, channel.group_id, on_peer_found)
            self._discovery.start(self.port)
        if self.ble:
            self.ble.set_key(channel.ble_key)

    def set_fallback_peers(self, addresses: list[tuple[str, int]]) -> None:
        self._fallback_peers = [Peer("", f"{h}:{p}", h, p, fallback=True) for h, p in addresses]

    def peers(self) -> list[Peer]:
        found = self._discovery.peers() if self._discovery else []
        result = list(found)
        known = {(p.host, p.port) for p in found}
        nearby = [
            Peer("", f"appareil proche ({b.announcement.host})", b.announcement.host, b.announcement.port)
            for b in (self.ble.peers() if self.ble else [])
        ]
        # mDNS, puis Bluetooth, puis adresses manuelles, puis de secours
        for p in nearby + self._static_peers + self._fallback_peers:
            if (p.host, p.port) not in known:
                known.add((p.host, p.port))
                result.append(p)
        return result

    # --- côté client -------------------------------------------------------

    def find_offers(self) -> list[Offer]:
        """Interroge tous les appareils en parallèle ; renvoie les objets disponibles, du plus récent au plus ancien."""
        peers = self.peers()
        if not peers:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(peers))) as pool:
            results = pool.map(self._ask_offer, peers)
        offers = [o for o in results if o and o.device_id != self.config.device_id]
        return sorted(offers, key=lambda o: o.age_s)

    def claim(self, offer: Offer, staging: Path) -> Item | None:
        """Récupère l'objet. Les fichiers éventuels sont écrits dans `staging` (créé si besoin).

        Renvoie None si l'objet n'est plus disponible ou si le transfert échoue ;
        l'appelant supprime ensuite `staging` dans tous les cas.
        """
        path = "/v1/claim"
        sealed = self._seal_request(path, {"item_id": offer.item_id})
        try:
            with urllib.request.urlopen(_post(offer.peer, path, sealed), timeout=TIMEOUT_S) as resp:
                return _read_item(StreamOpener(self.channel, _response_context(path, sealed), resp), staging)
        except urllib.error.HTTPError as e:
            _report_http_error(offer.peer, e)
        except CryptoError as e:
            log.warning(f"transfert depuis {offer.peer.name} invalide ({e})")
        except OSError as e:
            log.warning(f"transfert depuis {offer.peer.name} interrompu ({e})")
        return None

    def _ask_offer(self, peer: Peer) -> Offer | None:
        body = self._request(peer, "/v1/offer", {})
        if body is None:
            return None
        reply = json.loads(body)
        self.names[str(reply["device_id"])[:8]] = str(reply["device_name"])
        item = reply.get("item")
        if not item:
            return None
        return Offer(
            peer, reply["device_id"], reply["device_name"], item["id"], item["kind"], item["name"],
            item["size"], item["count"], item["age_s"],
        )

    def identify(self, peer: Peer) -> str | None:
        """Demande son nom à un appareil (entendu en Bluetooth, par exemple)."""
        self._ask_offer(peer)
        return self.names.get(peer.device_id[:8]) if peer.device_id else None

    def _request(self, peer: Peer, path: str, payload: dict) -> bytes | None:
        """Petite requête chiffrée ; renvoie le corps déchiffré de la réponse, ou None."""
        sealed = self._seal_request(path, payload)
        try:
            timeout = FALLBACK_TIMEOUT_S if peer.fallback else TIMEOUT_S
            with urllib.request.urlopen(_post(peer, path, sealed), timeout=timeout) as resp:
                raw = resp.read(MAX_REQUEST_BYTES + 1)
        except urllib.error.HTTPError as e:
            _report_http_error(peer, e)
            return None
        except OSError:
            return None  # appareil injoignable ou éteint
        try:
            return self.channel.open(raw, _response_context(path, sealed))
        except CryptoError:
            log.warning(f"réponse invalide de {peer.name}, ignorée")
            return None

    def _seal_request(self, path: str, payload: dict) -> bytes:
        payload = {**payload, "ts": time.time(), "from": self.config.device_id}
        return self.channel.seal(json.dumps(payload).encode(), path.encode())


def _post(peer: Peer, path: str, sealed: bytes) -> urllib.request.Request:
    return urllib.request.Request(peer.url + path, data=sealed, method="POST")


def _report_http_error(peer: Peer, e: urllib.error.HTTPError) -> None:
    if e.code == 403:
        log.warning(f"{peer.name} refuse la requête (code d'appairage différent, ou horloges décalées ?)")


def _response_context(path: str, request_body: bytes) -> bytes:
    # La réponse est liée à la requête (via son nonce) : impossible de rejouer
    # une ancienne réponse.
    return b"resp:" + path.encode() + request_body[:NONCE_BYTES]


def _write_item(item: Item, stream: StreamSealer) -> None:
    header = json.dumps({
        "id": item.id, "kind": item.kind, "name": item.name, "mime": item.mime, "data_len": len(item.data),
        "files": [{"path": f.path, "size": f.size} for f in item.files],
    }).encode()
    stream.write(struct.pack(">I", len(header)) + header)
    stream.write(item.data)
    for f in item.files:
        with open(f.source, "rb") as src:
            remaining = f.size
            while remaining:
                block = src.read(min(CHUNK_BYTES, remaining))
                if not block:
                    raise OSError(f"{f.source} a été raccourci pendant l'envoi")
                stream.write(block)
                remaining -= len(block)
    stream.close()


def _read_item(stream: StreamOpener, staging: Path) -> Item:
    (header_len,) = struct.unpack(">I", stream.read_exact(4))
    if header_len > MAX_HEADER_BYTES:
        raise CryptoError("en-tête trop grand")
    header = json.loads(stream.read_exact(header_len))
    data_len = int(header["data_len"])
    if data_len > MAX_MEMORY_BYTES:
        raise CryptoError("contenu en mémoire trop grand")
    data = stream.read_exact(data_len)

    files = []
    for f in header["files"]:
        dest = unique_path(staging / safe_relative_path(f["path"]))
        dest.parent.mkdir(parents=True, exist_ok=True)
        remaining = size = int(f["size"])
        with open(dest, "wb") as out:
            while remaining:
                block = stream.read_some(min(CHUNK_BYTES, remaining))
                out.write(block)
                remaining -= len(block)
        files.append(FileEntry(dest.relative_to(staging).as_posix(), size, dest))
    stream.finish()
    return Item(kind=header["kind"], name=header["name"], mime=header["mime"], data=data, files=files, id=header["id"])


class _Server(ThreadingHTTPServer):
    # Sous Windows, SO_REUSEADDR permettrait à une seconde instance d'écouter le
    # même port sans erreur : on demande au contraire l'usage exclusif du port.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Handler(BaseHTTPRequestHandler):
    node: Node

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_REQUEST_BYTES:
            return self._reply(413)
        body = self.rfile.read(length)

        if self.path == "/v1/local/show":  # seconde copie lancée sur ce PC : accepté seulement en local
            if self.client_address[0] in ("127.0.0.1", "::1") and self.node.on_show:
                self.node.on_show()
                return self._reply(200)
            return self._reply(403)

        if self.path.startswith("/v1/pair/"):  # appairage : protégé par le PAKE, pas par le groupe
            pairing = self.node.pairing
            status, reply = pairing.handle(self.path, body, self.client_address[0]) if pairing else (404, b"")
            return self._reply(status, reply)

        try:
            request = json.loads(self.node.channel.open(body, self.path.encode()))
        except (CryptoError, ValueError):
            return self._reply(403)
        if abs(time.time() - float(request.get("ts", 0))) > MAX_CLOCK_SKEW_S:
            return self._reply(403)

        context = _response_context(self.path, body)
        if self.path == "/v1/offer":
            payload = json.dumps(self._offer()).encode()
            self._reply(200, self.node.channel.seal(payload, context))
        elif self.path == "/v1/claim":
            item = self.node.held.take(str(request.get("item_id", "")))
            if item is None:
                return self._reply(410)
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                _write_item(item, StreamSealer(self.node.channel, context, self.wfile))
            except OSError as e:
                log.warning(f"Envoi interrompu : {item.describe()} ({e})")
                return
            log.info(f"Envoyé : {item.describe()}")
        else:
            self._reply(404)

    def _offer(self) -> dict:
        config, held = self.node.config, self.node.held.peek()
        item = None
        if held:
            it, age = held
            item = {"id": it.id, "kind": it.kind, "name": it.name, "size": it.size, "count": len(it.files), "age_s": age}
        return {"device_id": config.device_id, "device_name": config.device_name, "item": item}

    def _reply(self, status: int, body: bytes = b"") -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass  # pas de journal HTTP dans la console


class Discovery:
    """Annonce cet appareil et repère ceux du même groupe sur le réseau local (mDNS)."""

    def __init__(self, config: Config, group_id: str, on_peer_found: Callable[[Peer], None] | None = None) -> None:
        self.config = config
        self.group_id = group_id
        self._on_peer_found = on_peer_found
        self._lock = threading.Lock()
        self._peers: dict[str, Peer] = {}
        self._zc: Zeroconf | None = None
        self._info: ServiceInfo | None = None

    def start(self, port: int) -> None:
        self._zc = Zeroconf(ip_version=IPVersion.V4Only)
        short_id = self.config.device_id[:8]
        self._info = ServiceInfo(
            SERVICE_TYPE,
            f"GrabDrop-{short_id}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip())],
            port=port,
            properties={"id": self.config.device_id, "name": self.config.device_name, "group": self.group_id},
            server=f"grabdrop-{short_id}.local.",
        )
        self._zc.register_service(self._info)
        ServiceBrowser(self._zc, SERVICE_TYPE, handlers=[self._on_change])

    def stop(self) -> None:
        if self._zc:
            if self._info:
                self._zc.unregister_service(self._info)
            self._zc.close()

    def peers(self) -> list[Peer]:
        with self._lock:
            return list(self._peers.values())

    def _on_change(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change is ServiceStateChange.Removed:
            with self._lock:
                self._peers.pop(name, None)
            return
        info = zeroconf.get_service_info(service_type, name, timeout=3000)
        if not info:
            return
        props = {k.decode(): (v or b"").decode() for k, v in info.properties.items()}
        if props.get("group") != self.group_id or props.get("id") == self.config.device_id:
            return
        addresses = info.parsed_addresses(IPVersion.V4Only)
        if not addresses:
            return
        peer = Peer(props["id"], props.get("name") or name, addresses[0], info.port)
        with self._lock:
            is_new = name not in self._peers
            self._peers[name] = peer
        if is_new and self._on_peer_found:
            self._on_peer_found(peer)


def local_ipv4_addresses() -> list[str]:
    """Adresses IPv4 utilisables par un autre appareil, l'interface par défaut en premier."""
    import ifaddr  # fourni avec zeroconf

    addresses = [local_ip()]
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if isinstance(ip.ip, str) and not ip.ip.startswith(("127.", "169.254.")) and ip.ip not in addresses:
                addresses.append(ip.ip)
    return [a for a in addresses if a != "127.0.0.1"][:4] or ["127.0.0.1"]


def local_ip() -> str:
    """Adresse IPv4 de l'interface par défaut (aucun paquet n'est envoyé)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
