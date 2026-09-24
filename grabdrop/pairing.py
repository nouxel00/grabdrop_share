"""Appairage par code court (6 chiffres), protégé par SPAKE2.

L'hôte (un appareil du groupe) affiche un code à 6 chiffres et accepte UNE
seule tentative pendant PAIRING_WINDOW_S secondes. L'invité saisit le code et
reçoit le secret du groupe.

Grâce au PAKE (échange de clé authentifié par mot de passe), écouter l'échange
ne permet pas de retrouver le code, et un intrus n'a qu'un essai : une chance
sur un million.

Échange (HTTP, hors du chiffrement de groupe) :
 1. invité -> hôte : POST /v1/pair/start   {"msg": SPAKE2 invité, "id", "name"}
 2. hôte -> invité : {"msg": SPAKE2 hôte, "name", "box": AES-GCM(clé PAKE, secret du groupe)}
 3. invité -> hôte : POST /v1/pair/confirm {"mac": HMAC(clé PAKE)}  (l'hôte sait que c'est réussi)

Variante téléphone (QR code) : l'hôte affiche un QR contenant son adresse et un
jeton aléatoire de 128 bits, valable pendant la même fenêtre et une seule fois.
Le jeton ne circule jamais sur le réseau :
 1. téléphone -> hôte : POST /v1/pair/qr {"id", "name", "nonce", "mac": HMAC(jeton, nonce + id)}
 2. hôte -> téléphone : {"box": AES-GCM(clé dérivée du jeton, secret du groupe)}
Un appareil qui n'a pas scanné le QR ne peut ni fabriquer la requête, ni lire la réponse.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from spake2 import SPAKE2_Symmetric
from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

PAIR_SERVICE_TYPE = "_grabdrop-pair._tcp.local."
PAIRING_WINDOW_S = 120
CONFIRM_TIMEOUT_S = 10  # essai sans confirmation (mauvais code) : la fenêtre se ferme
SHORT_CODE_DIGITS = 6
QR_TOKEN_BYTES = 16
QR_SCHEME = "grabdrop"
_SPAKE_ID = b"grabdrop pair v1"
TIMEOUT_S = 5.0

log = logging.getLogger("grabdrop")


class PairingError(Exception):
    pass


def new_short_code() -> str:
    return f"{secrets.randbelow(10**SHORT_CODE_DIGITS):0{SHORT_CODE_DIGITS}d}"


def normalize_short_code(code: str) -> str | None:
    """« 123 456 » ou « 123-456 » -> « 123456 » ; None si ce n'est pas un code court."""
    digits = "".join(c for c in code if not c.isspace() and c != "-")
    return digits if len(digits) == SHORT_CODE_DIGITS and digits.isdigit() else None


def format_short_code(code: str) -> str:
    return f"{code[:3]} {code[3:]}"


def _derive(key: bytes, label: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=label).derive(key)


def _seal_box(key: bytes, payload: dict) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_derive(key, b"grabdrop pair box")).encrypt(nonce, json.dumps(payload).encode(), b"box")


def _open_box(key: bytes, box: bytes) -> dict:
    return json.loads(AESGCM(_derive(key, b"grabdrop pair box")).decrypt(box[:12], box[12:], b"box"))


def _confirm_mac(key: bytes) -> bytes:
    return hmac.new(_derive(key, b"grabdrop pair confirm"), b"invite ok", "sha256").digest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _qr_mac(token: bytes, nonce: bytes, device_id: str) -> bytes:
    return hmac.new(_derive(token, b"grabdrop qr mac"), nonce + device_id.encode(), "sha256").digest()


def qr_uri(token: bytes, hosts: list[str], port: int, device_name: str) -> str:
    """Contenu du QR : grabdrop://pair?v=1&h=IP1,IP2&p=PORT&t=JETON&n=NOM."""
    query = urllib.parse.urlencode({
        "v": 1,
        "h": ",".join(hosts),
        "p": port,
        "t": base64.b32encode(token).decode().rstrip("="),
        "n": device_name,
    })
    return f"{QR_SCHEME}://pair?{query}"


class PairingHost:
    """Côté hôte : une fenêtre d'appairage, une seule tentative."""

    def __init__(
        self,
        short_code: str,
        group_code: str,
        device_name: str,
        on_paired: Callable[[str], None] | None = None,
        window_s: float = PAIRING_WINDOW_S,
    ) -> None:
        self.short_code = short_code
        self.qr_token = secrets.token_bytes(QR_TOKEN_BYTES)
        self._qr_used = False
        self._group_code = group_code
        self._device_name = device_name
        self._on_paired = on_paired
        self._expires_at = time.monotonic() + window_s
        self._lock = threading.Lock()
        self._used_at: float | None = None
        self._key: bytes | None = None
        self._guest_name = "?"
        self.finished = threading.Event()
        self.paired_with: str | None = None
        # Adresse du téléphone appairé par QR (ip, port de son serveur) : gardée
        # en secours, si la découverte mDNS ne le trouve pas plus tard.
        self.guest_address: tuple[str, int] | None = None

    def active(self) -> bool:
        now = time.monotonic()
        if self._used_at is not None and now - self._used_at > CONFIRM_TIMEOUT_S:
            self.finished.set()  # l'unique essai n'a pas abouti (mauvais code côté invité)
        return not self.finished.is_set() and now < self._expires_at

    def cancel(self) -> None:
        self.finished.set()

    def handle(self, path: str, body: bytes, client_ip: str = "") -> tuple[int, bytes]:
        """Traite une requête /v1/pair/... ; renvoie (statut HTTP, corps)."""
        with self._lock:
            if not self.active():
                return 410, b""
            try:
                request = json.loads(body)
                if path == "/v1/pair/start":
                    return self._start(request)
                if path == "/v1/pair/confirm":
                    return self._confirm(request)
                if path == "/v1/pair/qr":
                    return self._qr(request, client_ip)
            except (ValueError, KeyError, TypeError):
                return 400, b""
            return 404, b""

    def _start(self, request: dict) -> tuple[int, bytes]:
        if self._used_at is not None:
            return 409, b""
        self._used_at = time.monotonic()  # un seul essai, réussi ou non
        spake = SPAKE2_Symmetric(self.short_code.encode(), idSymmetric=_SPAKE_ID)
        own_msg = spake.start()
        try:
            self._key = spake.finish(base64.b64decode(request["msg"]))
        except Exception:
            self.finished.set()
            return 400, b""
        self._guest_name = str(request.get("name", "?"))[:100]
        box = _seal_box(self._key, {"group_code": self._group_code})
        reply = {"msg": _b64(own_msg), "name": self._device_name, "box": _b64(box)}
        return 200, json.dumps(reply).encode()

    def _qr(self, request: dict, client_ip: str = "") -> tuple[int, bytes]:
        if self._qr_used:
            return 409, b""
        nonce, device_id = base64.b64decode(request["nonce"]), str(request["id"])
        if len(nonce) < 16 or not hmac.compare_digest(base64.b64decode(request["mac"]), _qr_mac(self.qr_token, nonce, device_id)):
            # Requête sans le jeton : refusée, mais ne consomme pas la fenêtre
            # (un appareil quelconque du réseau ne peut pas la bloquer).
            return 403, b""
        self._qr_used = True
        key = _derive(self.qr_token, b"grabdrop qr box")
        box_nonce = os.urandom(12)
        box = box_nonce + AESGCM(key).encrypt(box_nonce, json.dumps({"group_code": self._group_code}).encode(), nonce)
        port = request.get("port")
        if client_ip and isinstance(port, int) and 0 < port < 65536:
            self.guest_address = (client_ip, port)
        self.finished.set()
        self.paired_with = str(request.get("name", "?"))[:100]
        if self._on_paired:
            self._on_paired(self.paired_with)
        return 200, json.dumps({"box": _b64(box), "name": self._device_name}).encode()

    def _confirm(self, request: dict) -> tuple[int, bytes]:
        if self._key is None:
            return 409, b""
        ok = hmac.compare_digest(base64.b64decode(request["mac"]), _confirm_mac(self._key))
        self.finished.set()
        if not ok:
            return 403, b""
        self.paired_with = self._guest_name
        if self._on_paired:
            self._on_paired(self._guest_name)
        return 200, b""


@dataclass
class JoinResult:
    group_code: str
    host_name: str


def join(short_code: str, device_id: str, device_name: str, hosts: list[tuple[str, int]] | None = None,
         search_s: float = 8.0) -> JoinResult:
    """Côté invité : trouve un hôte en attente et récupère le secret du groupe."""
    hosts = hosts or find_pairing_hosts(search_s)
    if not hosts:
        raise PairingError("aucun appareil en attente d'appairage trouvé sur le réseau")
    error = PairingError("échec de l'appairage")
    for host, port in hosts:
        try:
            return _join_host(short_code, host, port, device_id, device_name)
        except PairingError as e:
            error = e
    raise error


def _join_host(short_code: str, host: str, port: int, device_id: str, device_name: str) -> JoinResult:
    spake = SPAKE2_Symmetric(short_code.encode(), idSymmetric=_SPAKE_ID)
    reply = json.loads(_post(host, port, "/v1/pair/start", {"msg": _b64(spake.start()), "id": device_id, "name": device_name}))
    key = spake.finish(base64.b64decode(reply["msg"]))
    try:
        payload = _open_box(key, base64.b64decode(reply["box"]))
    except InvalidTag:
        raise PairingError("code incorrect (générez-en un nouveau sur l'autre appareil)") from None
    _post(host, port, "/v1/pair/confirm", {"mac": _b64(_confirm_mac(key))})
    return JoinResult(payload["group_code"], str(reply.get("name", host)))


def join_with_qr(uri: str, device_id: str, device_name: str, service_port: int = 47800) -> JoinResult:
    """Côté téléphone (référence Python, utilisée par les tests) : appairage à partir du contenu du QR."""
    parsed = urllib.parse.urlparse(uri)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    if parsed.scheme != QR_SCHEME or parsed.netloc != "pair" or query.get("v") != "1":
        raise PairingError("QR code non reconnu")
    token = base64.b32decode(query["t"] + "=" * (-len(query["t"]) % 8))
    nonce = os.urandom(16)
    payload = {
        "id": device_id, "name": device_name, "port": service_port,
        "nonce": _b64(nonce), "mac": _b64(_qr_mac(token, nonce, device_id)),
    }
    error = PairingError("appareil injoignable")
    for host in query["h"].split(","):
        try:
            reply = json.loads(_post(host, int(query["p"]), "/v1/pair/qr", payload))
        except PairingError as e:
            error = e
            continue
        box = base64.b64decode(reply["box"])
        group = json.loads(AESGCM(_derive(token, b"grabdrop qr box")).decrypt(box[:12], box[12:], nonce))
        return JoinResult(group["group_code"], str(reply.get("name", host)))
    raise error


def _post(host: str, port: int, path: str, payload: dict) -> bytes:
    req = urllib.request.Request(f"http://{host}:{port}{path}", data=json.dumps(payload).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.read(64 * 1024)
    except urllib.error.HTTPError as e:
        if e.code in (409, 410):
            raise PairingError("cet appareil n'accepte plus d'appairage : générez un nouveau code") from None
        raise PairingError(f"appairage refusé (HTTP {e.code})") from None
    except OSError as e:
        raise PairingError(f"appareil injoignable ({e})") from None


# --- Découverte des hôtes en attente -------------------------------------------


class PairingAdvertiser:
    """Annonce sur le réseau local qu'un appareil attend un appairage."""

    def __init__(self, port: int, device_id: str, device_name: str) -> None:
        from grabdrop.network import local_ip

        self._zc = Zeroconf(ip_version=IPVersion.V4Only)
        self._info = ServiceInfo(
            PAIR_SERVICE_TYPE,
            # Nom unique à chaque fenêtre : deux annonces successives ne se confondent pas.
            f"GrabDrop-pair-{secrets.token_hex(4)}.{PAIR_SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip())],
            port=port,
            properties={"name": device_name},
            server=f"grabdrop-pair-{device_id[:8]}-{secrets.token_hex(2)}.local.",
        )
        self._zc.register_service(self._info)

    def close(self) -> None:
        self._zc.unregister_service(self._info)
        self._zc.close()


def find_pairing_hosts(timeout_s: float) -> list[tuple[str, int]]:
    """Hôtes en attente d'appairage ; rend la main dès qu'un hôte est trouvé (plus un court délai)."""
    found: dict[str, tuple[str, int]] = {}
    first_found = threading.Event()

    def on_change(zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change is ServiceStateChange.Removed:
            return
        info = zeroconf.get_service_info(service_type, name, timeout=2000)
        if info and info.parsed_addresses(IPVersion.V4Only):
            found[name] = (info.parsed_addresses(IPVersion.V4Only)[0], info.port)
            first_found.set()

    zc = Zeroconf(ip_version=IPVersion.V4Only)
    try:
        ServiceBrowser(zc, PAIR_SERVICE_TYPE, handlers=[on_change])
        if first_found.wait(timeout_s):
            time.sleep(1.5)  # laisser arriver un éventuel second hôte
        return list(found.values())
    finally:
        zc.close()
