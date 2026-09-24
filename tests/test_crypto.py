import pytest

from grabdrop.crypto import Channel, CryptoError, format_code, new_pairing_code, parse_code


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
