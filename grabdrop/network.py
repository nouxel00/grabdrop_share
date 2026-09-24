"""Échanges entre appareils : découverte (mDNS), serveur HTTP et client.

Protocole (tous les corps sont chiffrés par `Channel`) :
- POST /v1/offer : « as-tu quelque chose en main ? » -> description de l'objet, ou rien
- POST /v1/claim : « je prends l'objet X » -> l'objet (une seule fois), ou 410

Le modèle est « tiré » : c'est l'appareil qui voit le DROP qui interroge les
autres. Aucune donnée ne circule tant que personne ne dépose.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

from grabdrop.config import Config
from grabdrop.crypto import NONCE_BYTES, Channel, CryptoError
from grabdrop.items import HeldItem, Item

SERVICE_TYPE = "_grabdrop._tcp.local."
DEFAULT_PORT = 47800
MAX_CLOCK_SKEW_S = 120  # âge max d'une requête (limite le rejeu)
MAX_REQUEST_BYTES = 64 * 1024
MAX_ITEM_BYTES = 200 * 1024 * 1024
TIMEOUT_S = 3.0


@dataclass(frozen=True)
class Peer:
    device_id: str
    name: str
    host: str
    port: int

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
    size: int
    age_s: float


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
        self._host = host
        self.channel = channel
        self.held = held
        self._requested_port = port
        self._static_peers = [Peer("", f"{h}:{p}", h, p) for h, p in static_peers]
        self._discovery = Discovery(config, channel.group_id, on_peer_found) if discovery else None
        self._server: ThreadingHTTPServer | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else self._requested_port

    def start(self) -> None:
        handler = type("Handler", (_Handler,), {"node": self})
        self._server = ThreadingHTTPServer((self._host, self._requested_port), handler)
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

    def peers(self) -> list[Peer]:
        found = self._discovery.peers() if self._discovery else []
        known = {(p.host, p.port) for p in found}
        return found + [p for p in self._static_peers if (p.host, p.port) not in known]

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

    def claim(self, offer: Offer) -> Item | None:
        body = self._request(offer.peer, "/v1/claim", {"item_id": offer.item_id})
        if body is None:
            return None
        (header_len,) = struct.unpack(">I", body[:4])
        header = json.loads(body[4 : 4 + header_len])
        return Item(kind=header["kind"], name=header["name"], mime=header["mime"], data=body[4 + header_len :], id=header["id"])

    def _ask_offer(self, peer: Peer) -> Offer | None:
        body = self._request(peer, "/v1/offer", {})
        if body is None:
            return None
        reply = json.loads(body)
        item = reply.get("item")
        if not item:
            return None
        return Offer(peer, reply["device_id"], reply["device_name"], item["id"], item["kind"], item["size"], item["age_s"])

    def _request(self, peer: Peer, path: str, payload: dict) -> bytes | None:
        """Requête chiffrée ; renvoie le corps déchiffré de la réponse, ou None."""
        payload = {**payload, "ts": time.time(), "from": self.config.device_id}
        sealed = self.channel.seal(json.dumps(payload).encode(), path.encode())
        req = urllib.request.Request(peer.url + path, data=sealed, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                raw = resp.read(MAX_ITEM_BYTES + 1)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"  {peer.name} refuse la requête (code d'appairage différent, ou horloges décalées ?)")
            return None
        except OSError:
            return None  # appareil injoignable ou éteint
        try:
            return self.channel.open(raw, _response_context(path, sealed))
        except CryptoError:
            print(f"  réponse invalide de {peer.name}, ignorée")
            return None


def _response_context(path: str, request_body: bytes) -> bytes:
    # La réponse est liée à la requête (via son nonce) : impossible de rejouer
    # une ancienne réponse.
    return b"resp:" + path.encode() + request_body[:NONCE_BYTES]


class _Handler(BaseHTTPRequestHandler):
    node: Node

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_REQUEST_BYTES:
            return self._reply(413)
        body = self.rfile.read(length)
        try:
            request = json.loads(self.node.channel.open(body, self.path.encode()))
        except (CryptoError, ValueError):
            return self._reply(403)
        if abs(time.time() - float(request.get("ts", 0))) > MAX_CLOCK_SKEW_S:
            return self._reply(403)

        if self.path == "/v1/offer":
            payload = json.dumps(self._offer()).encode()
        elif self.path == "/v1/claim":
            item = self.node.held.take(str(request.get("item_id", "")))
            if item is None:
                return self._reply(410)
            header = json.dumps({"id": item.id, "kind": item.kind, "name": item.name, "mime": item.mime}).encode()
            payload = struct.pack(">I", len(header)) + header + item.data
            print(f"Capture envoyée à l'appareil qui l'a déposée ({len(item.data) // 1024} Ko)")
        else:
            return self._reply(404)
        self._reply(200, self.node.channel.seal(payload, _response_context(self.path, body)))

    def _offer(self) -> dict:
        config, held = self.node.config, self.node.held.peek()
        item = None
        if held:
            it, age = held
            item = {"id": it.id, "kind": it.kind, "size": len(it.data), "age_s": age}
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
