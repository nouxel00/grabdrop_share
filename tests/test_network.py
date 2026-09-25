"""Plusieurs appareils simulés sur cette machine, sans découverte mDNS."""

import logging
import os
import time
import uuid

import pytest

from grabdrop.config import Config
from grabdrop.crypto import CHUNK_BYTES, Channel, new_pairing_code, parse_code
from grabdrop.items import TEXT, HeldItem, Item, files_item
from grabdrop.network import Node, Peer

CODE = new_pairing_code()


@pytest.fixture
def make_node():
    nodes = []

    def make(name, code=CODE, peers=()):
        config = Config(device_id=uuid.uuid4().hex, device_name=name, pairing_code=code)
        node = Node(config, Channel(parse_code(code)), HeldItem(), port=0,
                    static_peers=[("127.0.0.1", p.port) for p in peers], discovery=False,
                    host="127.0.0.1")
        node.start()
        nodes.append(node)
        return node

    yield make
    for n in nodes:
        n.stop()


def screenshot(data=b"\x89PNG fausse capture"):
    return Item(kind="screenshot", name="capture.png", mime="image/png", data=data)


def test_grab_on_a_drop_on_b(make_node, tmp_path):
    a = make_node("PC-A")
    b = make_node("PC-B", peers=[a])
    item = screenshot(b"x" * 500_000)
    a.held.hold(item)

    offers = b.find_offers()
    assert [(o.device_name, o.item_id, o.size, o.describe()) for o in offers] == [
        ("PC-A", item.id, 500_000, "capture d'écran (488,3 Ko)")
    ]
    received = b.claim(offers[0], tmp_path)
    assert received.data == item.data and received.name == "capture.png"
    # L'objet a quitté la main de A : un second DROP ne récupère rien.
    assert a.held.peek() is None
    assert b.find_offers() == []


def test_text(make_node, tmp_path):
    a = make_node("PC-A")
    b = make_node("PC-B", peers=[a])
    a.held.hold(Item(kind=TEXT, name="texte", mime="text/plain", data="Voilà ✓".encode()))
    received = b.claim(b.find_offers()[0], tmp_path)
    assert received.kind == TEXT and received.data.decode() == "Voilà ✓"


def test_files_and_folders_are_streamed_to_disk(make_node, tmp_path):
    src = tmp_path / "src"
    (src / "Projet" / "sous").mkdir(parents=True)
    big = os.urandom(3 * CHUNK_BYTES + 777)  # plusieurs morceaux chiffrés
    (src / "Projet" / "gros.bin").write_bytes(big)
    (src / "Projet" / "sous" / "vide.txt").write_bytes(b"")
    (src / "note.txt").write_text("bonjour", encoding="utf-8")

    a = make_node("PC-A")
    b = make_node("PC-B", peers=[a])
    a.held.hold(files_item([src / "Projet", src / "note.txt"]))
    offer = b.find_offers()[0]
    assert offer.describe() == "3 fichiers (3,0 Mo)"

    staging = tmp_path / "staging"
    received = b.claim(offer, staging)
    assert [f.path for f in received.files] == ["Projet/gros.bin", "Projet/sous/vide.txt", "note.txt"]
    assert (staging / "Projet" / "gros.bin").read_bytes() == big
    assert (staging / "Projet" / "sous" / "vide.txt").read_bytes() == b""
    assert (staging / "note.txt").read_text(encoding="utf-8") == "bonjour"


def test_file_deleted_before_drop_fails_cleanly(make_node, tmp_path, caplog):
    f = tmp_path / "temp.txt"
    f.write_bytes(b"contenu")
    a = make_node("PC-A")
    b = make_node("PC-B", peers=[a])
    a.held.hold(files_item([f]))
    offer = b.find_offers()[0]
    f.unlink()
    with caplog.at_level(logging.INFO, logger="grabdrop"):
        assert b.claim(offer, tmp_path / "staging") is None
    assert "interrompu" in caplog.text or "invalide" in caplog.text


def test_nothing_in_hand(make_node):
    a = make_node("PC-A")
    b = make_node("PC-B", peers=[a])
    assert b.find_offers() == []


def test_stranger_cannot_see_or_claim(make_node, caplog):
    a = make_node("PC-A")
    a.held.hold(screenshot())
    stranger = make_node("Intrus", code=new_pairing_code(), peers=[a])
    with caplog.at_level(logging.INFO, logger="grabdrop"):
        assert stranger.find_offers() == []
    assert a.held.peek() is not None
    assert "refuse" in caplog.text


def test_first_claim_wins(make_node, tmp_path):
    a = make_node("PC-A")
    b = make_node("PC-B", peers=[a])
    c = make_node("PC-C", peers=[a])
    a.held.hold(screenshot())
    offer_b, offer_c = b.find_offers()[0], c.find_offers()[0]
    assert b.claim(offer_b, tmp_path / "b") is not None
    assert c.claim(offer_c, tmp_path / "c") is None


def test_own_item_is_ignored(make_node):
    # Un appareil qui se liste lui-même (adresse manuelle) ne se « vole » pas son objet.
    a = make_node("PC-A")
    a._static_peers = [Peer("", "moi", "127.0.0.1", a.port)]
    a.held.hold(screenshot())
    assert a.find_offers() == []


def test_most_recent_offer_first(make_node):
    a = make_node("PC-A")
    b = make_node("PC-B")
    c = make_node("PC-C", peers=[a, b])
    a.held.hold(screenshot(b"ancienne"))
    a.held._since -= 5  # attrapée il y a 5 s
    b.held.hold(screenshot(b"recente"))
    offers = c.find_offers()
    assert [o.device_name for o in offers] == ["PC-B", "PC-A"]


def test_unreachable_peer_is_skipped(make_node):
    a = make_node("PC-A")
    a.held.hold(screenshot())
    b = make_node("PC-B", peers=[a])
    b._static_peers.append(Peer("", "eteint", "127.0.0.1", 1))
    assert [o.device_name for o in b.find_offers()] == ["PC-A"]


def test_unreachable_fallback_peer_does_not_slow_drop(make_node):
    a = make_node("PC-A")
    a.held.hold(screenshot())
    b = make_node("PC-B", peers=[a])
    # Téléphone appairé autrefois, absent du réseau : adresse non routable.
    b.set_fallback_peers([("10.255.255.1", 47800)])
    started = time.monotonic()
    assert [o.device_name for o in b.find_offers()] == ["PC-A"]
    assert time.monotonic() - started < 2.5


def test_fallback_peer_is_used_and_not_duplicated(make_node):
    a = make_node("PC-A")
    a.held.hold(screenshot())
    b = make_node("PC-B")
    b.set_fallback_peers([("127.0.0.1", a.port), ("127.0.0.1", a.port)])
    assert [p.fallback for p in b.peers()] == [True]
    assert [o.device_name for o in b.find_offers()] == ["PC-A"]


def test_identify_learns_the_name_of_a_device_heard_over_bluetooth(make_node):
    a = make_node("PC-A")
    b = make_node("PC-B")
    assert b.identify(Peer(a.config.device_id, "?", "127.0.0.1", a.port)) == "PC-A"  # même sans objet en main
    assert b.names[a.config.device_id[:8]] == "PC-A"


def test_second_copy_asks_the_running_one_to_show_itself(make_node):
    import urllib.request

    a = make_node("PC-A")
    shown = []
    a.on_show = lambda: shown.append(True)
    request = urllib.request.Request(f"http://127.0.0.1:{a.port}/v1/local/show", data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=3) as response:
        assert response.status == 200
    assert shown == [True]
