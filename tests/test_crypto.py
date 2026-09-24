import io
import os

import pytest

from grabdrop.crypto import (
    CHUNK_BYTES,
    Channel,
    CryptoError,
    StreamOpener,
    StreamSealer,
    format_code,
    new_pairing_code,
    parse_code,
)


def test_pairing_code_roundtrip():
    code = new_pairing_code()
    assert len(code.replace("-", "")) == 26
    assert format_code(parse_code(code)) == code


def test_pairing_code_is_tolerant_to_typing():
    code = format_code(bytes(range(16)))
    sloppy = code.lower().replace("-", " ")
    assert parse_code(sloppy) == bytes(range(16))
    # 0 tapé à la place de O
    assert parse_code(code.replace("O", "0")) == parse_code(code)


@pytest.mark.parametrize("bad", ["", "ABCD-EFGH", "!!!!", new_pairing_code() + "AAAA"])
def test_invalid_pairing_code(bad):
    with pytest.raises(ValueError):
        parse_code(bad)


def test_seal_open_roundtrip():
    ch = Channel(parse_code(new_pairing_code()))
    assert ch.open(ch.seal(b"bonjour", b"ctx"), b"ctx") == b"bonjour"


def test_same_code_same_group():
    code = new_pairing_code()
    assert Channel(parse_code(code)).group_id == Channel(parse_code(code)).group_id
    assert Channel(parse_code(code)).group_id != Channel(parse_code(new_pairing_code())).group_id


def test_rejects_wrong_key_context_or_tampering():
    code = new_pairing_code()
    a, b, stranger = Channel(parse_code(code)), Channel(parse_code(code)), Channel(parse_code(new_pairing_code()))
    blob = a.seal(b"secret", b"/v1/claim")
    assert b.open(blob, b"/v1/claim") == b"secret"
    with pytest.raises(CryptoError):
        stranger.open(blob, b"/v1/claim")
    with pytest.raises(CryptoError):
        b.open(blob, b"/v1/offer")
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(CryptoError):
        b.open(tampered, b"/v1/claim")
    with pytest.raises(CryptoError):
        b.open(b"court", b"/v1/claim")


# --- Flux chiffrés ---------------------------------------------------------------


def _sealed_stream(ch, data, context=b"ctx", pieces=7):
    out = io.BytesIO()
    sealer = StreamSealer(ch, context, out)
    step = max(1, len(data) // pieces)
    for i in range(0, len(data), step):
        sealer.write(data[i : i + step])
    sealer.close()
    return out.getvalue()


@pytest.mark.parametrize("size", [0, 10, CHUNK_BYTES, CHUNK_BYTES + 1, 3 * CHUNK_BYTES + 12345])
def test_stream_roundtrip(size):
    ch = Channel(parse_code(new_pairing_code()))
    data = os.urandom(size)
    opener = StreamOpener(ch, b"ctx", io.BytesIO(_sealed_stream(ch, data)))
    got = b""
    while len(got) < size:
        got += opener.read_some(100_000)
    opener.finish()
    assert got == data


def test_stream_truncated_or_tampered():
    ch = Channel(parse_code(new_pairing_code()))
    blob = _sealed_stream(ch, os.urandom(2 * CHUNK_BYTES + 10))
    first_frame_len = 5 + int.from_bytes(blob[:4], "big")

    def read_all(raw, context=b"ctx"):
        opener = StreamOpener(ch, context, io.BytesIO(raw))
        opener.read_exact(2 * CHUNK_BYTES + 10)
        opener.finish()

    read_all(blob)  # intact : OK
    with pytest.raises(CryptoError):
        read_all(blob[:-1])  # coupé
    with pytest.raises(CryptoError):
        read_all(blob[first_frame_len:])  # premier morceau retiré
    with pytest.raises(CryptoError):
        read_all(blob[: len(blob) // 2] + bytes([blob[len(blob) // 2] ^ 1]) + blob[len(blob) // 2 + 1 :])
    with pytest.raises(CryptoError):
        read_all(blob, context=b"autre")
    # Faux « dernier morceau » : le drapeau est authentifié.
    forged = blob[:4] + b"\x01" + blob[5:first_frame_len]
    with pytest.raises(CryptoError):
        StreamOpener(ch, b"ctx", io.BytesIO(forged)).read_exact(1)
