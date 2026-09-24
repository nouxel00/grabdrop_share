from pathlib import PurePosixPath

from grabdrop.items import (
    FILES,
    FileEntry,
    HeldItem,
    Item,
    files_item,
    human_size,
    move_received_files,
    safe_name,
    safe_relative_path,
    save_bytes,
)


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


def test_save_bytes_never_overwrites(tmp_path):
    p1 = save_bytes(b"1", "capture.png", tmp_path, ".png")
    p2 = save_bytes(b"2", "capture.png", tmp_path, ".png")
    assert (p1.name, p2.name) == ("capture.png", "capture (1).png")
    assert p1.read_bytes() == b"1" and p2.read_bytes() == b"2"


def test_save_bytes_sanitizes_remote_name(tmp_path):
    for evil in ["../../evil.png", "..\\..\\evil.png", "C:\\Windows\\evil.png", "a:b?c.png", "", "..", "CON.png"]:
        path = save_bytes(b"x", evil, tmp_path / "out", ".png")
        assert path.parent == tmp_path / "out"
        assert path.suffix == ".png"
        assert path.stem.upper() != "CON"


def test_safe_relative_path_stays_inside():
    assert safe_relative_path("Dossier/sous/f.txt") == PurePosixPath("Dossier/sous/f.txt")
    assert safe_relative_path("../../etc/passwd") == PurePosixPath("etc/passwd")
    assert safe_relative_path("C:\\Windows\\System32\\x.dll") == PurePosixPath("C_/Windows/System32/x.dll")
    assert safe_relative_path("/abs/./x") == PurePosixPath("abs/x")
    assert safe_relative_path("..") == PurePosixPath("grabdrop")


def test_safe_name():
    assert safe_name("rapport final.pdf") == "rapport final.pdf"
    assert safe_name("nul.txt") == "_nul.txt"
    assert safe_name(" . ") == "grabdrop"


def test_files_item_walks_folders(tmp_path):
    (tmp_path / "Projet" / "sous").mkdir(parents=True)
    (tmp_path / "Projet" / "a.txt").write_bytes(b"aaa")
    (tmp_path / "Projet" / "sous" / "b.txt").write_bytes(b"bb")
    (tmp_path / "seul.pdf").write_bytes(b"p")

    item = files_item([tmp_path / "Projet", tmp_path / "seul.pdf"])
    assert item.kind == FILES and item.name == "2 éléments"
    assert [(f.path, f.size) for f in item.files] == [("Projet/a.txt", 3), ("Projet/sous/b.txt", 2), ("seul.pdf", 1)]
    assert item.size == 6
    assert files_item([tmp_path / "Projet"]).name == "Projet"
    assert files_item([tmp_path / "inexistant"]) is None


def test_move_received_files_renames_existing(tmp_path):
    staging, out = tmp_path / "staging", tmp_path / "out"
    (staging / "Projet").mkdir(parents=True)
    (staging / "Projet" / "a.txt").write_bytes(b"new")
    (staging / "f.txt").write_bytes(b"f")
    (out / "Projet").mkdir(parents=True)  # existe déjà : ne pas écraser
    files = [FileEntry("Projet/a.txt", 3), FileEntry("f.txt", 1)]

    moved = move_received_files(staging, files, out)
    assert [p.name for p in moved] == ["Projet (1)", "f.txt"]
    assert (out / "Projet (1)" / "a.txt").read_bytes() == b"new"


def test_describe_and_sizes():
    assert human_size(512) == "512 octets"
    assert human_size(1536) == "1,5 Ko"
    assert human_size(5 * 1024**3) == "5,0 Go"
    assert screenshot(b"x" * 2048).describe() == "capture d'écran (2,0 Ko)"
    one = Item(kind=FILES, name="rapport.pdf", files=[FileEntry("rapport.pdf", 10)])
    assert one.describe() == "« rapport.pdf » (10 octets)"
