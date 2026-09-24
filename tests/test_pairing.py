import uuid

import pytest

from grabdrop.config import Config
from grabdrop.crypto import Channel, new_pairing_code, parse_code
from grabdrop.items import HeldItem
from grabdrop.network import Node
from grabdrop.pairing import PairingError, PairingHost, format_short_code, join, new_short_code, normalize_short_code


@pytest.fixture
def host_node():
    code = new_pairing_code()
    node = Node(Config(uuid.uuid4().hex, "PC-hôte", code), Channel(parse_code(code)), HeldItem(),
                port=0, discovery=False, host="127.0.0.1")
    node.start()
    yield node
    node.stop()


def open_window(node, short_code="123456", window_s=60):
    paired = []
    node.pairing = PairingHost(short_code, node.config.pairing_code, node.config.device_name,
                               on_paired=paired.append, window_s=window_s)
    return paired


def guest_join(node, short_code):
    return join(short_code, uuid.uuid4().hex, "PC-invité", hosts=[("127.0.0.1", node.port)])


def test_right_code_shares_group_secret(host_node):
    paired = open_window(host_node, "123456")
    result = guest_join(host_node, "123456")
    assert result.group_code == host_node.config.pairing_code
    assert result.host_name == "PC-hôte"
    assert paired == ["PC-invité"]
    assert not host_node.pairing.active()  # fenêtre fermée après succès


def test_wrong_code_fails_and_burns_the_window(host_node):
    paired = open_window(host_node, "123456")
    with pytest.raises(PairingError, match="code incorrect"):
        guest_join(host_node, "654321")
    # Un seul essai : même le bon code ne passe plus.
    with pytest.raises(PairingError, match="n'accepte plus"):
        guest_join(host_node, "123456")
    assert paired == []


def test_no_window_open(host_node):
    with pytest.raises(PairingError):
        guest_join(host_node, "123456")


def test_expired_window(host_node):
    open_window(host_node, "123456", window_s=0)
    with pytest.raises(PairingError, match="n'accepte plus"):
        guest_join(host_node, "123456")


def test_group_traffic_still_protected_during_pairing(host_node):
    # Les requêtes de groupe d'un intrus restent refusées même si une fenêtre d'appairage est ouverte.
    open_window(host_node)
    code = new_pairing_code()
    intruder = Node(Config(uuid.uuid4().hex, "Intrus", code), Channel(parse_code(code)), HeldItem(),
                    port=0, static_peers=[("127.0.0.1", host_node.port)], discovery=False, host="127.0.0.1")
    assert intruder.find_offers() == []


def test_short_code_helpers():
    code = new_short_code()
    assert len(code) == 6 and code.isdigit()
    assert normalize_short_code("123 456") == "123456"
    assert normalize_short_code("123-456") == "123456"
    assert normalize_short_code("12345") is None
    assert normalize_short_code("ABCD-EFGH-IJKL") is None
    assert format_short_code("123456") == "123 456"


def test_window_closes_soon_after_a_failed_attempt(host_node, monkeypatch):
    import grabdrop.pairing as pairing

    open_window(host_node, "123456", window_s=60)
    with pytest.raises(PairingError):
        guest_join(host_node, "000000")
    assert host_node.pairing.active()  # l'invité pourrait encore confirmer...
    monkeypatch.setattr(pairing, "CONFIRM_TIMEOUT_S", 0)
    assert not host_node.pairing.active()  # ...mais sans confirmation, la fenêtre se ferme
    assert host_node.pairing.finished.is_set()
