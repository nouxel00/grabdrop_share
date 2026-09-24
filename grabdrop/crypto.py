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
