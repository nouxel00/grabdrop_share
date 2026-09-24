"""Chiffrement des échanges entre appareils appairés.

Les appareils d'un même groupe partagent un secret de 128 bits, saisi sous forme
de code d'appairage. Chaque message (requête comme réponse) est chiffré et
authentifié en AES-256-GCM avec une clé dérivée de ce secret : un appareil qui
ne connaît pas le code ne peut ni lire une capture, ni en réclamer une.
"""

from __future__ import annotations

import base64
import binascii
import os
import struct
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SECRET_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16

# Caractères souvent confondus à la saisie, absents de l'alphabet base32.
_TYPO_FIXES = str.maketrans("018", "OIB")


class CryptoError(Exception):
    """Message illisible : mauvais code d'appairage, ou message altéré."""


def new_pairing_code() -> str:
    return format_code(os.urandom(SECRET_BYTES))


def format_code(secret: bytes) -> str:
    """16 octets -> 26 caractères base32 groupés par 4 : ABCD-EFGH-...-YZ."""
    b32 = base64.b32encode(secret).decode().rstrip("=")
    return "-".join(b32[i : i + 4] for i in range(0, len(b32), 4))


def parse_code(code: str) -> bytes:
    """Inverse de `format_code`, tolérant aux minuscules, espaces et tirets."""
    cleaned = "".join(c for c in code.upper() if c.isalnum()).translate(_TYPO_FIXES)
    try:
        secret = base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))
    except binascii.Error:
        raise ValueError("code d'appairage invalide") from None
    if len(secret) != SECRET_BYTES:
        raise ValueError("code d'appairage invalide (longueur incorrecte)")
    return secret


def _derive(secret: bytes, label: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=label).derive(secret)


class Channel:
    """Canal chiffré partagé par tous les appareils ayant le même code."""

    def __init__(self, secret: bytes) -> None:
        self._aead = AESGCM(_derive(secret, b"grabdrop v1 key", 32))
        # Identifiant public du groupe, annoncé sur le réseau : permet d'ignorer
        # les appareils d'autres groupes sans rien révéler du secret.
        self.group_id = _derive(secret, b"grabdrop v1 group", 6).hex()
        # Clé des annonces Bluetooth (voir ble.py).
        self.ble_key = _derive(secret, b"grabdrop v1 ble", 32)

    def seal(self, plaintext: bytes, context: bytes) -> bytes:
        """Chiffre `plaintext`. `context` (non transmis) doit être identique à l'ouverture."""
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, plaintext, context)

    def open(self, blob: bytes, context: bytes) -> bytes:
        if len(blob) < NONCE_BYTES + TAG_BYTES:
            raise CryptoError("message trop court")
        try:
            return self._aead.decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], context)
        except InvalidTag:
            raise CryptoError("message non authentifié") from None


# --- Flux chiffrés (transferts volumineux) -----------------------------------
#
# Le contenu est découpé en morceaux d'au plus CHUNK_BYTES, chacun chiffré à
# part. Trame : longueur (4 octets) + drapeau « dernier » (1 octet) + morceau
# chiffré. Le numéro du morceau et le drapeau font partie du contexte
# authentifié : un morceau retiré, dupliqué, réordonné ou une fin de flux
# prématurée sont détectés.

CHUNK_BYTES = 1 << 20
_FRAME_HEADER = struct.Struct(">IB")


class StreamSealer:
    """Écrit un flux chiffré dans `out`. Appeler `close()` pour marquer la fin."""

    def __init__(self, channel: Channel, context: bytes, out: BinaryIO) -> None:
        self._channel, self._context, self._out = channel, context, out
        self._buffer = bytearray()
        self._index = 0

    def write(self, data: bytes) -> None:
        self._buffer += data
        while len(self._buffer) > CHUNK_BYTES:  # garder de quoi faire le dernier morceau
            self._emit(bytes(self._buffer[:CHUNK_BYTES]), last=False)
            del self._buffer[:CHUNK_BYTES]

    def close(self) -> None:
        self._emit(bytes(self._buffer), last=True)
        self._buffer.clear()

    def _emit(self, chunk: bytes, last: bool) -> None:
        sealed = self._channel.seal(chunk, _chunk_context(self._context, self._index, last))
        self._out.write(_FRAME_HEADER.pack(len(sealed), last) + sealed)
        self._index += 1


class StreamOpener:
    """Lit un flux produit par `StreamSealer`. Lève CryptoError s'il est altéré ou tronqué."""

    def __init__(self, channel: Channel, context: bytes, src: BinaryIO) -> None:
        self._channel, self._context, self._src = channel, context, src
        self._buffer = bytearray()
        self._index = 0
        self._finished = False

    def read_exact(self, n: int) -> bytes:
        while len(self._buffer) < n:
            if self._finished:
                raise CryptoError("flux plus court qu'annoncé")
            self._next_chunk()
        data = bytes(self._buffer[:n])
        del self._buffer[:n]
        return data

    def read_some(self, max_bytes: int) -> bytes:
        """Jusqu'à `max_bytes` octets (au moins 1), sans tout accumuler en mémoire."""
        if not self._buffer:
            if self._finished:
                raise CryptoError("flux plus court qu'annoncé")
            self._next_chunk()
        return self.read_exact(min(max_bytes, len(self._buffer)))

    def finish(self) -> None:
        """Vérifie que le flux est complet et entièrement consommé."""
        while not self._finished:
            self._next_chunk()
        if self._buffer:
            raise CryptoError("données inattendues en fin de flux")

    def _next_chunk(self) -> None:
        header = self._read_raw(_FRAME_HEADER.size)
        length, last = _FRAME_HEADER.unpack(header)
        if length > CHUNK_BYTES + NONCE_BYTES + TAG_BYTES or last > 1:
            raise CryptoError("trame invalide")
        chunk = self._channel.open(self._read_raw(length), _chunk_context(self._context, self._index, bool(last)))
        self._buffer += chunk
        self._index += 1
        self._finished = bool(last)

    def _read_raw(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            part = self._src.read(n - len(data))
            if not part:
                raise CryptoError("flux interrompu")
            data += part
        return data


def _chunk_context(context: bytes, index: int, last: bool) -> bytes:
    return context + struct.pack(">Q?", index, last)
