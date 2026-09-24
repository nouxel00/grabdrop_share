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

    def active(self) -> bool:
        now = time.monotonic()
        if self._used_at is not None and now - self._used_at > CONFIRM_TIMEOUT_S:
            self.finished.set()  # l'unique essai n'a pas abouti (mauvais code côté invité)
        return not self.finished.is_set() and now < self._expires_at

    def cancel(self) -> None:
        self.finished.set()

    def handle(self, path: str, body: bytes) -> tuple[int, bytes]:
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
