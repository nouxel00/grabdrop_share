"""Deux (ou trois) appareils simulés sur cette machine, sans découverte mDNS."""

import uuid

import pytest

from grabdrop.config import Config
from grabdrop.crypto import Channel, new_pairing_code, parse_code
from grabdrop.items import HeldItem, Item
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


def test_grab_on_a_drop_on_b(make_node):
    a = make_node("PC-A")
    b = make_node("PC-B", peers=[a])
    item = screenshot(b"x" * 500_000)
    a.held.hold(item)

    offers = b.find_offers()
    assert [(o.device_name, o.item_id, o.size) for o in offers] == [("PC-A", item.id, 500_000)]
    received = b.claim(offers[0])
    assert received.data == item.data and received.name == "capture.png"
    # L'objet a quitté la main de A : un second DROP ne récupère rien.
    assert a.held.peek() is None
    assert b.find_offers() == []


def test_nothing_in_hand(make_node):
    a = make_node("PC-A")
    b = make_node("PC-B", peers=[a])
    assert b.find_offers() == []


def test_stranger_cannot_see_or_claim(make_node, capsys):
    a = make_node("PC-A")
    a.held.hold(screenshot())
    stranger = make_node("Intrus", code=new_pairing_code(), peers=[a])
    assert stranger.find_offers() == []
    assert a.held.peek() is not None
    assert "refuse" in capsys.readouterr().out


def test_first_claim_wins(make_node):
    a = make_node("PC-A")
    b = make_node("PC-B", peers=[a])
    c = make_node("PC-C", peers=[a])
    a.held.hold(screenshot())
    offer_b, offer_c = b.find_offers()[0], c.find_offers()[0]
    assert b.claim(offer_b) is not None
    assert c.claim(offer_c) is None


def test_own_item_is_ignored(make_node):
    # Un appareil qui se liste lui-même (adresse manuelle) ne se « vole » pas sa capture.
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
