"""
Field-level encryption — faithful port of field-crypto.ts.

For Restricted / Highly-Restricted values stored at rest: Netsuite IDs, MFA
secrets, password-reset tokens, partner payment metadata. AES-256-GCM
(authenticated) — tampering is detectable on decrypt. No external dependency
beyond the `cryptography` library.

Key: FIELD_ENCRYPTION_KEY = 32 bytes, hex (64 chars) or base64. Keep it in the
secret manager, SEPARATE from the database. Rotate by decrypting with the old
key and re-encrypting with the new (out-of-band migration).

Stored format:  v1:<iv_b64>:<authTag_b64>:<ciphertext_b64>
"""

from __future__ import annotations

import base64
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


VERSION = "v1"
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _load_key() -> bytes:
    raw = os.environ.get("FIELD_ENCRYPTION_KEY", "")
    if not raw:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY is not set — cannot encrypt/decrypt restricted fields."
        )
    key = bytes.fromhex(raw) if _HEX64.match(raw) else base64.b64decode(raw)
    if len(key) != 32:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY must be 32 bytes (64 hex chars or base64)."
        )
    return key


def is_encrypted(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(f"{VERSION}:")


def encrypt_field(plain: str) -> str:
    key = _load_key()
    iv = os.urandom(12)  # 96-bit nonce for GCM
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(iv, plain.encode("utf-8"), None)
    # AESGCM.encrypt returns ciphertext || tag (tag is last 16 bytes). Split
    # to match the legacy "<iv>:<authTag>:<ciphertext>" storage shape.
    tag, body = ct[-16:], ct[:-16]
    return ":".join(
        [
            VERSION,
            base64.b64encode(iv).decode("ascii"),
            base64.b64encode(tag).decode("ascii"),
            base64.b64encode(body).decode("ascii"),
        ]
    )


def decrypt_field(stored: str) -> str:
    if not is_encrypted(stored):
        return stored  # tolerate legacy plaintext during migration
    _, iv_b64, tag_b64, ct_b64 = stored.split(":")
    key = _load_key()
    aesgcm = AESGCM(key)
    iv = base64.b64decode(iv_b64)
    tag = base64.b64decode(tag_b64)
    body = base64.b64decode(ct_b64)
    plaintext = aesgcm.decrypt(iv, body + tag, None)
    return plaintext.decode("utf-8")


def encrypt_nullable(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return encrypt_field(value)


def decrypt_nullable(value: str | None) -> str | None:
    if value is None:
        return None
    return decrypt_field(value)


__all__ = [
    "is_encrypted",
    "encrypt_field",
    "decrypt_field",
    "encrypt_nullable",
    "decrypt_nullable",
]
