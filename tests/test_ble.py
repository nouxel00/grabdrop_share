import os
from types import SimpleNamespace

from grabdrop.ble import (
    COMPANY_ID,
    FLAG_HOLDING,
    FLAG_PHONE,
    PAYLOAD_BYTES,
    PERIOD_S,
    BleAnnouncement,
    BleDiscovery,
    decode,
    device_tag,
    encode,
)
from grabdrop.crypto import Channel

KEY = Channel(bytes(range(16))).ble_key
ANN = BleAnnouncement(device_tag("9587922337d6410a82f60f5b9511f920"), "192.168.1.42", 47800, FLAG_HOLDING | FLAG_PHONE)
NOW = 1_790_000_000.0


def test_roundtrip_fits_in_a_legacy_advertisement():
    payload = encode(KEY, ANN, NOW)
    assert len(payload) == PAYLOAD_BYTES  # + 4 octets d'en-tête fabricant + 3 de drapeaux <= 31
    got = decode(KEY, payload, NOW)
    assert got == ANN
    assert got.holding and got.is_phone
    assert device_tag("9587922337d6410a82f60f5b9511f920") == bytes.fromhex("95879223")


def test_other_group_cannot_read_it():
    payload = encode(KEY, ANN, NOW)
    assert decode(Channel(os.urandom(16)).ble_key, payload, NOW) is None
    # Adresse illisible sans la clé : l'IP n'apparaît pas en clair.
    assert bytes([192, 168, 1, 42]) not in payload


def test_tampering_is_detected():
    payload = bytearray(encode(KEY, ANN, NOW))
    payload[10] ^= 0x01  # un bit de l'adresse chiffrée
    assert decode(KEY, bytes(payload), NOW) is None
    assert decode(KEY, b"XX" + bytes(payload[2:]), NOW) is None
    assert decode(KEY, bytes(payload[:-1]), NOW) is None


def test_rotates_every_period_but_tolerates_clock_skew():
    payload = encode(KEY, ANN, NOW)
    assert encode(KEY, ANN, NOW + PERIOD_S) != payload  # pas d'identifiant fixe traçable
    assert decode(KEY, payload, NOW + PERIOD_S) == ANN  # période suivante : accepté
    assert decode(KEY, payload, NOW - PERIOD_S) == ANN  # horloge en retard : accepté
    assert decode(KEY, payload, NOW + 3 * PERIOD_S) is None  # trop ancien : ignoré


def test_discovery_keeps_group_peers_sorted_by_proximity(monkeypatch):
    ble = BleDiscovery(KEY, "aaaaaaaa" + "0" * 24, 47800, lambda: "192.168.1.10")

    def hear(announcement, rssi):
        data = SimpleNamespace(manufacturer_data={COMPANY_ID: encode(KEY, announcement)}, rssi=rssi)
        ble._on_advertisement(None, data)

    far = BleAnnouncement(bytes.fromhex("11111111"), "192.168.1.20", 47800, 0)
    near = BleAnnouncement(bytes.fromhex("22222222"), "192.168.1.30", 47800, FLAG_HOLDING)
    own = BleAnnouncement(bytes.fromhex("aaaaaaaa"), "192.168.1.10", 47800, 0)
    hear(far, -80)
    hear(near, -45)
    hear(own, -30)  # sa propre annonce (renvoyée par un autre adaptateur) : ignorée
    ble._on_advertisement(None, SimpleNamespace(manufacturer_data={COMPANY_ID: os.urandom(18)}, rssi=-40))
    ble._on_advertisement(None, SimpleNamespace(manufacturer_data={0x004C: b"autre"}, rssi=-40))

    assert [(p.announcement.host, p.rssi) for p in ble.peers()] == [("192.168.1.30", -45), ("192.168.1.20", -80)]

    # Un appareil qui ne s'annonce plus disparaît.
    ble._peers[bytes.fromhex("11111111")].last_seen -= 60
    assert [p.announcement.host for p in ble.peers()] == ["192.168.1.30"]
