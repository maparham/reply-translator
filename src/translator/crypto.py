from __future__ import annotations

import base64
import hashlib
import hmac
import json

from cryptography.fernet import Fernet


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Crypto:
    def __init__(self, secret_key: str):
        self._fernet = Fernet(secret_key.encode())
        self._sign_key = hashlib.sha256(b"session:" + secret_key.encode()).digest()

    def encrypt(self, s: str) -> str:
        return self._fernet.encrypt(s.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()

    def _mac(self, body: str) -> str:
        return _b64(hmac.new(self._sign_key, body.encode(), hashlib.sha256).digest())

    def sign(self, payload: dict) -> str:
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        return f"{body}.{self._mac(body)}"

    def unsign(self, token: str) -> dict | None:
        try:
            body, mac = token.split(".", 1)
            if not hmac.compare_digest(mac, self._mac(body)):
                return None
            payload = json.loads(_unb64(body))
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None
