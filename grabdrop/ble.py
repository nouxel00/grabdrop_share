"""Découverte des appareils par Bluetooth basse consommation (BLE).

Le BLE sert à TROUVER les appareils (et à estimer leur proximité) ; les données
passent toujours par le Wi-Fi (network.py). Chaque appareil diffuse une annonce
de 18 octets dans les « données fabricant » (identifiant 0xFFFF, réservé aux
essais) :

    « GD » (2) | version (1) | signature (4) | contenu chiffré (11)
    contenu : identifiant court (4) | IPv4 (4) | port (2) | indicateurs (1)

La clé dérive de celle du groupe et la période change toutes les 10 minutes :
un appareil hors du groupe ne peut ni lire l'adresse, ni suivre durablement un
appareil, ni fabriquer une annonce acceptée. La signature (4 octets) sert à
trier les annonces ; la sécurité des échanges reste celle du canal Wi-Fi chiffré.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import struct
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("grabdrop")

COMPANY_ID = 0xFFFF
MAGIC = b"GD"
VERSION = 1
PAYLOAD_BYTES = 18
PERIOD_S = 600
PEER_TTL_S = 20.0  # sans nouvelle annonce, l'appareil est considéré comme parti

FLAG_HOLDING = 0x01  # l'appareil tient un objet
FLAG_PHONE = 0x02  # téléphone (sinon PC)


@dataclass(frozen=True)
class BleAnnouncement:
    device_tag: bytes  # 4 premiers octets de l'identifiant de l'appareil
    host: str
    port: int
    flags: int

    @property
    def holding(self) -> bool:
        return bool(self.flags & FLAG_HOLDING)

    @property
    def is_phone(self) -> bool:
        return bool(self.flags & FLAG_PHONE)


def device_tag(device_id: str) -> bytes:
    return bytes.fromhex(device_id[:8])


def _mac(key: bytes, label: bytes, period: int, data: bytes = b"") -> bytes:
    return hmac.new(key, label + struct.pack(">I", period) + data, hashlib.sha256).digest()


def encode(key: bytes, announcement: BleAnnouncement, now: float | None = None) -> bytes:
    period = int((time.time() if now is None else now) // PERIOD_S)
    body = (announcement.device_tag + ipaddress.IPv4Address(announcement.host).packed
            + struct.pack(">HB", announcement.port, announcement.flags))
    stream = _mac(key, b"body", period)[: len(body)]
    encrypted = bytes(a ^ b for a, b in zip(body, stream))
    signature = _mac(key, b"tag", period, body)[:4]
    return MAGIC + bytes([VERSION]) + signature + encrypted


def decode(key: bytes, payload: bytes, now: float | None = None) -> BleAnnouncement | None:
    """Annonce d'un appareil du groupe, ou None (autre groupe, altérée, trop ancienne)."""
    if len(payload) != PAYLOAD_BYTES or payload[:2] != MAGIC or payload[2] != VERSION:
        return None
    signature, encrypted = payload[3:7], payload[7:]
    current = int((time.time() if now is None else now) // PERIOD_S)
    for period in (current, current - 1, current + 1):  # horloges légèrement décalées
        stream = _mac(key, b"body", period)[: len(encrypted)]
        body = bytes(a ^ b for a, b in zip(encrypted, stream))
        if hmac.compare_digest(signature, _mac(key, b"tag", period, body)[:4]):
            port, flags = struct.unpack(">HB", body[8:11])
            return BleAnnouncement(body[:4], str(ipaddress.IPv4Address(body[4:8])), port, flags)
    return None


@dataclass
class BlePeer:
    announcement: BleAnnouncement
    rssi: int  # force du signal en dBm : plus c'est proche de 0, plus l'appareil est près
    last_seen: float


def proximity(rssi: int) -> str:
    """Ordre de grandeur seulement : le signal varie selon les murs, le corps, l'appareil..."""
    if rssi >= -55:
        return "très proche"
    if rssi >= -70:
        return "proche"
    return "à distance"


class BleDiscovery:
    """Diffuse l'annonce de cet appareil et écoute celles du groupe.

    Tout est facultatif : sans Bluetooth (désactivé, absent, autre système),
    GrabDrop continue avec la découverte mDNS seule.
    """

    RETRY_S = 10.0

    def __init__(self, key: bytes, device_id: str, port: int, host_provider: Callable[[], str]) -> None:
        self._key = key
        self._tag = device_tag(device_id)
        self._port = port
        self._host_provider = host_provider
        self._flags = 0
        self._lock = threading.Lock()
        self._peers: dict[bytes, BlePeer] = {}
        self._stop = threading.Event()
        self._changed = threading.Event()  # l'annonce doit être republiée
        self.status = "démarrage"

    # --- interface ------------------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=lambda: asyncio.run(self._run()), name="grabdrop-ble", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._changed.set()

    def set_key(self, key: bytes) -> None:
        with self._lock:
            self._key = key
            self._peers.clear()
        self._changed.set()

    def set_holding(self, holding: bool) -> None:
        flags = (self._flags | FLAG_HOLDING) if holding else (self._flags & ~FLAG_HOLDING)
        if flags != self._flags:
            self._flags = flags
            self._changed.set()

    def peers(self) -> list[BlePeer]:
        """Appareils du groupe entendus récemment, du plus proche au plus lointain."""
        now = time.monotonic()
        with self._lock:
            for tag in [t for t, p in self._peers.items() if now - p.last_seen > PEER_TTL_S]:
                del self._peers[tag]
            return sorted(self._peers.values(), key=lambda p: -p.rssi)

    # --- boucle -----------------------------------------------------------------------

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._session()
            except Exception as e:
                if self.status != f"indisponible ({e})":
                    log.info(f"Bluetooth indisponible ({e}) : découverte par Wi-Fi seulement, nouvel essai dans {self.RETRY_S:.0f} s.")
                self.status = f"indisponible ({e})"
            await asyncio.sleep(self.RETRY_S)

    async def _session(self) -> None:
        from bleak import BleakScanner

        publisher = _Publisher()
        async with BleakScanner(detection_callback=self._on_advertisement):
            if self.status != "actif":
                log.info("Bluetooth actif : annonce et détection des appareils proches.")
            self.status = "actif"
            period = None
            while not self._stop.is_set():
                current = int(time.time() // PERIOD_S)
                if self._changed.is_set() or current != period:  # nouvelle période : nouvelle annonce
                    self._changed.clear()
                    period = current
                    announcement = BleAnnouncement(self._tag, self._host_provider(), self._port, self._flags)
                    with self._lock:
                        key = self._key
                    publisher.publish(encode(key, announcement))
                await asyncio.sleep(0.5)
        publisher.stop()

    def _on_advertisement(self, device, data) -> None:
        payload = data.manufacturer_data.get(COMPANY_ID)
        if not payload:
            return
        with self._lock:
            announcement = decode(self._key, bytes(payload))
            if announcement is None or announcement.device_tag == self._tag:
                return
            self._peers[announcement.device_tag] = BlePeer(announcement, data.rssi, time.monotonic())


class _Publisher:
    """Diffusion de l'annonce. Windows : API WinRT ; ailleurs, pas encore pris en charge."""

    def __init__(self) -> None:
        self._publisher = None
        if sys.platform != "win32":
            log.info("Annonce Bluetooth non prise en charge sur ce système : détection seulement.")

    def publish(self, payload: bytes) -> None:
        if sys.platform != "win32":
            return
        from winrt.windows.devices.bluetooth.advertisement import (
            BluetoothLEAdvertisementPublisher,
            BluetoothLEAdvertisementPublisherStatus,
            BluetoothLEManufacturerData,
        )
        from winrt.windows.storage.streams import DataWriter

        self.stop()  # une annonce publiée ne se modifie pas : on la remplace
        writer = DataWriter()
        writer.write_bytes(payload)
        data = BluetoothLEManufacturerData()
        data.company_id = COMPANY_ID
        data.data = writer.detach_buffer()
        publisher = BluetoothLEAdvertisementPublisher()
        publisher.advertisement.manufacturer_data.append(data)
        publisher.start()
        if publisher.status == BluetoothLEAdvertisementPublisherStatus.ABORTED:
            raise OSError("annonce Bluetooth refusée par Windows")
        self._publisher = publisher

    def stop(self) -> None:
        if self._publisher is not None:
            try:
                self._publisher.stop()
            except Exception:
                pass
            self._publisher = None
