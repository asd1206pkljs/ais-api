"""Envelope encryption for stored user data.

Every file gets its own random data-encryption key (DEK). The DEK is wrapped
with the master key (KEK, from DATA_ENCRYPTION_KEY) and stored in the file
header. Rotating the KEK (`python -m app.tasks.encrypt_files --rewrap`) needs
no new master-key material in the payload, but because the header is part of
the payload's AAD the file is re-sealed with a fresh DEK on rewrap.

`context` (the file's storage-relative path) is mixed into the AAD, so a valid
blob copied over another resource's file fails to decrypt.

Blob layout:  MAGIC | 4-byte header length | header JSON | AES-256-GCM ciphertext
header: {"v": 1, "kid": <key id>, "wn": <wrap nonce>, "wdek": <wrapped DEK>, "n": <data nonce>}
"""
import base64
import hashlib
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"AISENC1\0"
_KEY_BYTES = 32
_NONCE_BYTES = 12
_HEADER_LEN_BYTES = 4
_MAX_HEADER = 4096


class DataEncryptionError(Exception):
    """Raised when a blob cannot be decrypted (unknown key, tampering, bad format)."""


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def key_id(key: bytes) -> str:
    """Stable public identifier of a key (never reveals the key)."""
    return hashlib.sha256(key).hexdigest()[:16]


def decode_key(b64: str) -> bytes:
    try:
        key = _b64d(b64.strip())
    except Exception as e:  # noqa: BLE001 - any decode failure is a config error
        raise DataEncryptionError("DATA_ENCRYPTION_KEY is not valid base64") from e
    if len(key) != _KEY_BYTES:
        raise DataEncryptionError(
            f"DATA_ENCRYPTION_KEY must decode to {_KEY_BYTES} bytes, got {len(key)}"
        )
    return key


def generate_key_b64() -> str:
    return _b64e(os.urandom(_KEY_BYTES))


class KeyRing:
    """Active KEK plus previous KEKs that are still accepted for decryption."""

    def __init__(self, active: bytes, previous: tuple[bytes, ...] = ()):
        self._active_kid = key_id(active)
        self._keys = {key_id(k): k for k in (active, *previous)}

    @classmethod
    def from_base64(cls, active_b64: str, previous_b64: list[str] | None = None) -> "KeyRing":
        if not active_b64:
            raise DataEncryptionError("DATA_ENCRYPTION_KEY is not configured")
        return cls(decode_key(active_b64), tuple(decode_key(k) for k in (previous_b64 or [])))

    @property
    def active_kid(self) -> str:
        return self._active_kid

    def active(self) -> tuple[str, bytes]:
        return self._active_kid, self._keys[self._active_kid]

    def get(self, kid: str) -> bytes:
        try:
            return self._keys[kid]
        except KeyError:
            raise DataEncryptionError(f"No key available for key id {kid}") from None


def is_encrypted(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


class EnvelopeCipher:
    def __init__(self, keyring: KeyRing):
        self._ring = keyring

    def encrypt(self, plaintext: bytes, context: bytes = b"") -> bytes:
        kid, kek = self._ring.active()
        dek = os.urandom(_KEY_BYTES)
        wrap_nonce = os.urandom(_NONCE_BYTES)
        data_nonce = os.urandom(_NONCE_BYTES)
        header = {
            "v": 1,
            "kid": kid,
            "wn": _b64e(wrap_nonce),
            "wdek": _b64e(AESGCM(kek).encrypt(wrap_nonce, dek, kid.encode())),
            "n": _b64e(data_nonce),
        }
        header_bytes = json.dumps(header, separators=(",", ":")).encode()
        ciphertext = AESGCM(dek).encrypt(data_nonce, plaintext, header_bytes + context)
        return MAGIC + len(header_bytes).to_bytes(_HEADER_LEN_BYTES, "big") + header_bytes + ciphertext

    def decrypt(self, blob: bytes, context: bytes = b"") -> bytes:
        header, header_bytes, ciphertext = self._split(blob)
        dek = self._unwrap(header)
        try:
            return AESGCM(dek).decrypt(_b64d(header["n"]), ciphertext, header_bytes + context)
        except (InvalidTag, ValueError, KeyError) as e:
            raise DataEncryptionError("Stored data failed integrity check") from e

    def key_id_of(self, blob: bytes) -> str:
        return self._split(blob)[0]["kid"]

    def rewrap(self, blob: bytes, context: bytes = b"") -> bytes:
        """Re-seal the blob under the active key (no-op if already current)."""
        header, _, _ = self._split(blob)
        kid, _ = self._ring.active()
        if header["kid"] == kid:
            return blob
        return self.encrypt(self.decrypt(blob, context), context)

    def _unwrap(self, header: dict) -> bytes:
        kek = self._ring.get(header["kid"])
        try:
            return AESGCM(kek).decrypt(
                _b64d(header["wn"]), _b64d(header["wdek"]), header["kid"].encode()
            )
        except (InvalidTag, ValueError, KeyError) as e:
            raise DataEncryptionError("Stored data key failed integrity check") from e

    @staticmethod
    def _split(blob: bytes) -> tuple[dict, bytes, bytes]:
        if not is_encrypted(blob):
            raise DataEncryptionError("Not an encrypted blob")
        start = len(MAGIC)
        length = int.from_bytes(blob[start:start + _HEADER_LEN_BYTES], "big")
        if length <= 0 or length > _MAX_HEADER:
            raise DataEncryptionError("Corrupt header")
        head_start = start + _HEADER_LEN_BYTES
        header_bytes = blob[head_start:head_start + length]
        if len(header_bytes) != length:
            raise DataEncryptionError("Corrupt header")
        try:
            header = json.loads(header_bytes)
        except ValueError as e:
            raise DataEncryptionError("Corrupt header") from e
        if header.get("v") != 1 or not all(k in header for k in ("kid", "wn", "wdek", "n")):
            raise DataEncryptionError("Unsupported header")
        return header, header_bytes, blob[head_start + length:]


def cipher_from_settings() -> EnvelopeCipher:
    from app.config import settings

    return EnvelopeCipher(
        KeyRing.from_base64(settings.DATA_ENCRYPTION_KEY, settings.data_encryption_keys_previous)
    )
