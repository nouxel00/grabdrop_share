from grabdrop.items import HeldItem, Item, save_item


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def screenshot(data=b"png"):
    return Item(kind="screenshot", name="capture.png", mime="image/png", data=data)


def test_hold_peek_take_once():
    held = HeldItem(ttl_s=20)
    item = screenshot()
    held.hold(item)
    assert held.peek()[0] is item
    assert held.take("autre-id") is None
    assert held.take(item.id) is item
    assert held.take(item.id) is None  # une seule fois
    assert held.peek() is None


def test_item_expires():
    clock = FakeClock()
    held = HeldItem(ttl_s=20, clock=clock)
    item = screenshot()
    held.hold(item)
    clock.t = 19
    assert held.peek()[1] == 19
    clock.t = 21
    assert held.peek() is None
    assert held.take(item.id) is None


def test_new_grab_replaces_previous():
    held = HeldItem()
    first, second = screenshot(), screenshot()
    held.hold(first)
    held.hold(second)
    assert held.take(first.id) is None
    assert held.take(second.id) is second


def test_save_item_never_overwrites(tmp_path):
    p1 = save_item(screenshot(b"1"), tmp_path)
    p2 = save_item(screenshot(b"2"), tmp_path)
    assert p1 != p2 and p1.read_bytes() == b"1" and p2.read_bytes() == b"2"


def test_save_item_sanitizes_remote_name(tmp_path):
    for evil in ["../../evil.png", "..\\..\\evil.png", "C:\\Windows\\evil.png", "a:b?c.png", "", ".."]:
        item = Item(kind="screenshot", name=evil, mime="image/png", data=b"x")
        path = save_item(item, tmp_path / "out")
        assert path.parent == tmp_path / "out"
        assert path.suffix == ".png"
