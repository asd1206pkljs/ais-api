import base64
import json

import pytest

from app.services.crypto import (
    DataEncryptionError,
    EnvelopeCipher,
    KeyRing,
    decode_key,
    generate_key_b64,
    is_encrypted,
    key_id,
)
from app.services.file_storage_service import FileStorageService


def _ring(*keys: bytes) -> KeyRing:
    return KeyRing(keys[0], tuple(keys[1:]))


def test_roundtrip_and_header_layout():
    cipher = EnvelopeCipher(_ring(b"a" * 32))
    blob = cipher.encrypt(b'{"x": 1}')
    assert is_encrypted(blob)
    assert b'{"x": 1}' not in blob
    assert cipher.decrypt(blob) == b'{"x": 1}'
    assert cipher.key_id_of(blob) == key_id(b"a" * 32)


def test_each_file_gets_its_own_dek_and_nonce():
    cipher = EnvelopeCipher(_ring(b"a" * 32))
    assert cipher.encrypt(b"same") != cipher.encrypt(b"same")


def test_tampered_payload_is_rejected():
    cipher = EnvelopeCipher(_ring(b"a" * 32))
    blob = bytearray(cipher.encrypt(b"secret data"))
    blob[-1] ^= 0xFF
    with pytest.raises(DataEncryptionError):
        cipher.decrypt(bytes(blob))


def test_tampered_header_is_rejected():
    cipher = EnvelopeCipher(_ring(b"a" * 32))
    blob = cipher.encrypt(b"secret data")
    start = len(b"AISENC1\x00") + 4
    length = int.from_bytes(blob[len(b"AISENC1\x00"):start], "big")
    header = json.loads(blob[start:start + length])
    header["n"] = base64.b64encode(b"\x00" * 12).decode()
    new_header = json.dumps(header, separators=(",", ":")).encode()
    forged = blob[:len(b"AISENC1\x00")] + len(new_header).to_bytes(4, "big") + new_header + blob[start + length:]
    with pytest.raises(DataEncryptionError):
        cipher.decrypt(forged)


def test_unknown_key_id_is_rejected():
    blob = EnvelopeCipher(_ring(b"a" * 32)).encrypt(b"x")
    with pytest.raises(DataEncryptionError, match="No key available"):
        EnvelopeCipher(_ring(b"b" * 32)).decrypt(blob)


def test_rotation_previous_key_still_decrypts_and_rewrap_moves_to_active():
    old, new = b"a" * 32, b"b" * 32
    blob = EnvelopeCipher(_ring(old)).encrypt(b"payload")
    rotated = EnvelopeCipher(_ring(new, old))
    assert rotated.decrypt(blob) == b"payload"
    rewrapped = rotated.rewrap(blob)
    assert rotated.key_id_of(rewrapped) == key_id(new)
    assert rotated.rewrap(rewrapped) is rewrapped  # already current
    assert EnvelopeCipher(_ring(new)).decrypt(rewrapped) == b"payload"


def test_context_binds_blob_to_its_location():
    cipher = EnvelopeCipher(_ring(b"a" * 32))
    blob = cipher.encrypt(b"payload", b"equipment/1/config.json")
    assert cipher.decrypt(blob, b"equipment/1/config.json") == b"payload"
    with pytest.raises(DataEncryptionError):
        cipher.decrypt(blob, b"equipment/2/config.json")
    rotated = EnvelopeCipher(_ring(b"b" * 32, b"a" * 32))
    assert rotated.decrypt(rotated.rewrap(blob, b"equipment/1/config.json"), b"equipment/1/config.json") == b"payload"


def test_file_storage_blob_cannot_be_moved_between_resources(tmp_path):
    storage = FileStorageService(str(tmp_path), EnvelopeCipher(_ring(b"a" * 32)), encrypt=True)
    storage.write_json("equipment/one/config.json", {"secret": 1})
    (tmp_path / "equipment/two").mkdir(parents=True)
    (tmp_path / "equipment/two/config.json").write_bytes((tmp_path / "equipment/one/config.json").read_bytes())
    with pytest.raises(DataEncryptionError):
        storage.read_json(str(tmp_path / "equipment/two/config.json"))


def test_not_encrypted_and_corrupt_blobs():
    cipher = EnvelopeCipher(_ring(b"a" * 32))
    with pytest.raises(DataEncryptionError):
        cipher.decrypt(b"plain json")
    with pytest.raises(DataEncryptionError):
        cipher.decrypt(b"AISENC1\x00" + (0).to_bytes(4, "big"))
    with pytest.raises(DataEncryptionError):
        cipher.decrypt(b"AISENC1\x00" + (5).to_bytes(4, "big") + b"nojsn")


def test_key_decoding_rules():
    assert len(decode_key(generate_key_b64())) == 32
    with pytest.raises(DataEncryptionError, match="32 bytes"):
        decode_key(base64.b64encode(b"short").decode())
    with pytest.raises(DataEncryptionError, match="base64"):
        decode_key("!!!not base64!!!")
    with pytest.raises(DataEncryptionError, match="not configured"):
        KeyRing.from_base64("")


def test_file_storage_encrypts_and_reads_legacy_plaintext(tmp_path):
    cipher = EnvelopeCipher(_ring(b"a" * 32))
    storage = FileStorageService(str(tmp_path), cipher, encrypt=True, allow_plaintext=True)
    path = storage.write_json("equipment/x/config.json", {"a": 1})
    raw = (tmp_path / "equipment/x/config.json").read_bytes()
    assert is_encrypted(raw) and b'"a"' not in raw
    assert storage.read_json(path) == {"a": 1}

    legacy = tmp_path / "flow_recipes/y/config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"legacy": true}')
    assert storage.read_json(str(legacy)) == {"legacy": True}
    assert storage.encrypt_in_place(str(legacy)) is True
    assert storage.encrypt_in_place(str(legacy)) is False
    assert storage.read_json(str(legacy)) == {"legacy": True}
    assert [p.name for p in storage.iter_config_files()] == ["config.json", "config.json"]

    strict = FileStorageService(str(tmp_path), cipher, encrypt=True, allow_plaintext=False)
    legacy2 = tmp_path / "simulators/z/config.json"
    legacy2.parent.mkdir(parents=True)
    legacy2.write_text("{}")
    with pytest.raises(DataEncryptionError, match="plaintext"):
        strict.read_json(str(legacy2))
    assert strict.rewrap_in_place(str(legacy2)) is False


def test_file_storage_plaintext_mode(tmp_path):
    storage = FileStorageService(str(tmp_path), encrypt=False)
    path = storage.write_json("equipment/p/config.json", {"b": 2})
    assert not is_encrypted((tmp_path / "equipment/p/config.json").read_bytes())
    assert storage.read_json(path) == {"b": 2}
    storage.delete(path)
    with pytest.raises(FileNotFoundError):
        storage.read_json(path)


def test_encrypt_files_task(tmp_path):
    from app.tasks.encrypt_files import run

    old, new = b"a" * 32, b"b" * 32
    storage = FileStorageService(str(tmp_path), EnvelopeCipher(_ring(old)), encrypt=True)
    storage.write_json("equipment/e1/config.json", {"k": 1})
    (tmp_path / "process_recipes/p1").mkdir(parents=True)
    (tmp_path / "process_recipes/p1/config.json").write_text('{"k": 2}')
    (tmp_path / "simulators/s1").mkdir(parents=True)
    (tmp_path / "simulators/s1/config.json").write_text("not json")

    report = run(storage, dry_run=True)
    assert (report.scanned, report.encrypted, report.already_current) == (3, 2, 1)
    assert not (tmp_path / "process_recipes/p1/config.json").read_bytes().startswith(b"AISENC1")

    report = run(storage)
    assert report.encrypted == 1 and report.already_current == 1 and len(report.failed) == 1
    assert storage.read_json(str(tmp_path / "process_recipes/p1/config.json")) == {"k": 2}

    rotated = FileStorageService(str(tmp_path), EnvelopeCipher(_ring(new, old)), encrypt=True)
    report = run(rotated, rewrap=True, dry_run=True)
    assert report.rewrapped == 2
    report = run(rotated, rewrap=True)
    assert report.rewrapped == 2 and len(report.failed) == 1
    assert run(rotated, rewrap=True).already_current == 2
    assert FileStorageService(str(tmp_path), EnvelopeCipher(_ring(new)), encrypt=True).read_json(
        str(tmp_path / "equipment/e1/config.json")) == {"k": 1}
