"""Decrypts the Meta token the API stored. Format (from lib/crypto.js): base64(iv).base64(tag).base64(ciphertext), AES-256-GCM."""
from __future__ import annotations
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from . import config

def decrypt(blob: str) -> str:
    key = base64.b64decode(config.ENCRYPTION_KEY)
    if len(key) != 32:
        raise RuntimeError("ENCRYPTION_KEY must be 32 bytes, base64 encoded")
    iv, tag, ct = (base64.b64decode(p) for p in blob.split("."))
    return AESGCM(key).decrypt(iv, ct + tag, None).decode("utf8")   # AESGCM expects tag appended to ciphertext

def encrypt(plain: str) -> str:            # used by tests to prove compatibility with the Node side
    import os
    key = base64.b64decode(config.ENCRYPTION_KEY)
    iv = os.urandom(12)
    out = AESGCM(key).encrypt(iv, plain.encode("utf8"), None)
    ct, tag = out[:-16], out[-16:]
    return ".".join(base64.b64encode(p).decode() for p in (iv, tag, ct))
