"""Shared crypto for node links: AES-256-GCM + HMAC over a PSK-derived key.

Used by the coordinator's node server and by every node client. The node-side
modules are kept self-contained (stdlib + cryptography only) so a fresh node can
run them standalone from its install dir.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_LEN = 32
NONCE_LEN = 12


class CryptoError(RuntimeError):
    """Any authentication/decryption failure. Callers must treat it as fatal for
    the message: decryption fails closed."""


def derive_key(psk: str | bytes) -> bytes:
    """Derive the AES/HMAC key from the shared passphrase (deterministic)."""
    if isinstance(psk, str):
        psk = psk.encode("utf-8")
    kdf = HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=b"eef-node-salt", info=b"eef-node-v1")
    return kdf.derive(psk)


class NodeCrypto:
    """AES-256-GCM secrecy + HMAC-SHA256 authenticity on top of one PSK."""

    def __init__(self, psk: str | bytes) -> None:
        self.key = derive_key(psk)

    # -- secrecy (AES-256-GCM) -------------------------------------------
    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> str:
        nonce = os.urandom(NONCE_LEN)
        try:
            ct = AESGCM(self.key).encrypt(nonce, plaintext, aad or None)
        except Exception as exc:
            raise CryptoError(f"encrypt failed: {exc}") from exc
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str, aad: bytes = b"") -> bytes:
        try:
            raw = base64.b64decode(token)
        except Exception as exc:
            raise CryptoError("malformed ciphertext") from exc
        nonce, ct = raw[:NONCE_LEN], raw[NONCE_LEN:]
        try:
            return AESGCM(self.key).decrypt(nonce, ct, aad or None)
        except InvalidTag as exc:
            raise CryptoError("decryption failed (bad key / tampered message)") from exc

    # -- authenticity (HMAC) ---------------------------------------------
    def sign(self, data: bytes) -> str:
        return base64.b64encode(hmac.new(self.key, data, hashlib.sha256).digest()).decode("ascii")

    def verify(self, data: bytes, signature: str) -> bool:
        try:
            expected = hmac.new(self.key, data, hashlib.sha256).digest()
            return hmac.compare_digest(expected, base64.b64decode(signature))
        except Exception:
            return False