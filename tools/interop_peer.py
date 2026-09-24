"""Pair Python pour le test d'interopérabilité Kotlin <-> Python (lancé par InteropTest.kt).

Déroulé, piloté par l'entrée standard :
1. Démarre un nœud Python, tient un objet « fichiers », ouvre une fenêtre d'appairage,
   puis affiche : READY <port> <empreintes> <uri du QR>
2. Le test Kotlin récupère l'objet, s'appaire par QR, puis tient son propre objet
   et écrit : YOUR_TURN <port kotlin>
3. Ce script récupère l'objet Kotlin et affiche : RESULT <chemin:taille:sha256,...> PAIRED=<nom>
"""

from __future__ import annotations

import hashlib
import random
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from grabdrop.config import Config  # noqa: E402
from grabdrop.crypto import Channel, parse_code  # noqa: E402
from grabdrop.items import HeldItem, files_item  # noqa: E402
from grabdrop.network import Node, Peer  # noqa: E402
from grabdrop.pairing import PairingHost, qr_uri  # noqa: E402


def main() -> None:
    code = sys.argv[1]
    work = Path(tempfile.mkdtemp(prefix="grabdrop-interop-"))
    src = work / "src"
    (src / "Été").mkdir(parents=True)
    rng = random.Random(42)
    (src / "Été" / "gros.bin").write_bytes(bytes(rng.getrandbits(8) for _ in range(2_500_000)))
    (src / "Été" / "note_✓.txt").write_text("Bonjour du PC — ça marche !", encoding="utf-8")

    config = Config(device_id=uuid.uuid4().hex, device_name="PC-Python", pairing_code=code)
    node = Node(config, Channel(parse_code(code)), HeldItem(ttl_s=60), port=0, discovery=False, host="127.0.0.1")
    node.start()
    item = files_item([src / "Été"])
    node.held.hold(item)
    host = PairingHost("123456", code, "PC-Python")
    node.pairing = host
    digests = ",".join(f"{f.path}:{f.size}:{hashlib.sha256(f.source.read_bytes()).hexdigest()}" for f in item.files)
    print(f"READY {node.port} {digests} {qr_uri(host.qr_token, ['127.0.0.1'], node.port, 'PC-Python')}", flush=True)

    line = sys.stdin.readline().split()
    if not line or line[0] != "YOUR_TURN":
        sys.exit("protocole de test rompu")
    node._static_peers = [Peer("", "kotlin", "127.0.0.1", int(line[1]))]
    offers = node.find_offers()
    received = node.claim(offers[0], work / "recu") if offers else None
    if received is None:
        print("RESULT ECHEC", flush=True)
    else:
        parts = [
            f"{f.path}:{f.size}:{hashlib.sha256(f.source.read_bytes()).hexdigest()}" for f in received.files
        ]
        text = received.data.decode("utf-8") if received.data else ""
        guest = ":".join(map(str, host.guest_address)) if host.guest_address else "-"
        print(f"RESULT {received.kind} {','.join(parts)} DATA={text.encode().hex()} PAIRED={host.paired_with} GUEST={guest}", flush=True)
    node.stop()


if __name__ == "__main__":
    main()
