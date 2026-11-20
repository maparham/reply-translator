"""Clerk session-token checks with a locally generated RSA key: these decide who can sign in, and who is admin."""
import base64
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from translator import clerk

FAPI = "clerk.translate.example"
PK = "pk_live_" + base64.b64encode(f"{FAPI}$".encode()).decode().rstrip("=")
ORIGIN = "https://translate.example"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwk(key, kid="k1"):
    n = key.public_key().public_numbers()
    return {"kty": "RSA", "kid": kid, "n": _b64(n.n.to_bytes(256, "big")), "e": _b64(n.e.to_bytes(3, "big"))}


def _claims(**over):
    now = int(time.time())
    return {"iss": f"https://{FAPI}", "azp": ORIGIN, "sub": "user_1", "sid": "sess_1",
            "iat": now, "nbf": now, "exp": now + 60} | over


def token(claims=None, key=KEY, head=None):
    h = head or {"alg": "RS256", "kid": "k1", "typ": "JWT"}
    signing = f"{_b64(json.dumps(h).encode())}.{_b64(json.dumps(claims or _claims()).encode())}"
    sig = key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing}.{_b64(sig)}"


def verifier(user=None):
    def h(req):
        if req.url.path == "/.well-known/jwks.json":
            return httpx.Response(200, json={"keys": [_jwk(KEY)]})
        return httpx.Response(200, json=user or {})
    return clerk.Verifier(PK, "sk_test", ORIGIN, httpx.AsyncClient(transport=httpx.MockTransport(h)))


async def test_valid_session_token():
    assert (await verifier().verify(token()))["sub"] == "user_1"


@pytest.mark.parametrize("bad", [
    pytest.param(lambda: token(key=OTHER_KEY), id="signed-by-another-key"),
    pytest.param(lambda: token(head={"alg": "none", "kid": "k1"}), id="alg-none"),
    pytest.param(lambda: token(head={"alg": "HS256", "kid": "k1"}), id="alg-hs256"),
    pytest.param(lambda: token(head={"alg": "RS256", "kid": "unknown"}), id="unknown-kid"),
    pytest.param(lambda: token(_claims(exp=int(time.time()) - 60)), id="expired"),
    pytest.param(lambda: token(_claims(nbf=int(time.time()) + 600)), id="not-yet-valid"),
    pytest.param(lambda: token(_claims(iss="https://clerk.other.example")), id="other-instance"),
    pytest.param(lambda: token(_claims(azp="https://evil.example")), id="other-site"),
    pytest.param(lambda: token(_claims(sid=None)), id="no-session-id"),
    pytest.param(lambda: token(_claims(sub="org_1")), id="not-a-user"),
    pytest.param(lambda: token()[:-4] + "AAAA", id="tampered-signature"),
    pytest.param(lambda: "a.b", id="not-a-jwt"),
])
async def test_rejected_tokens(bad):
    with pytest.raises(clerk.ClerkError):
        await verifier().verify(bad())


async def test_tampered_claims_rejected():
    # Swap in claims for another user while keeping the original signature.
    head, _, sig = token().split(".")
    forged = f"{head}.{_b64(json.dumps(_claims(sub='user_admin')).encode())}.{sig}"
    with pytest.raises(clerk.ClerkError):
        await verifier().verify(forged)


def _user(status="verified", primary="e1"):
    return {"primary_email_address_id": primary,
            "email_addresses": [{"id": "e1", "email_address": " Admin@X.test ", "verification": {"status": status}}]}


async def test_email_is_verified_primary_lowercased():
    assert await verifier(_user()).email("user_1") == "admin@x.test"


@pytest.mark.parametrize("user", [_user(status="unverified"), _user(primary="e2"), {}])
async def test_email_requires_verified_primary(user):
    with pytest.raises(clerk.ClerkError):
        await verifier(user).email("user_1")
