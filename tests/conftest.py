import pytest
from cryptography.fernet import Fernet

from translator import db
from translator.config import Config
from translator.crypto import Crypto
from translator.settings import Settings


@pytest.fixture
def cfg(tmp_path):
    return Config(
        app_url="http://testserver",
        secret_key=Fernet.generate_key().decode(),
        clerk_publishable_key="",
        clerk_secret_key="",
        admin_emails=frozenset({"admin@x.test"}),
        db_path=str(tmp_path / "translator.db"),
        host="127.0.0.1",
        port=18490,
    )


@pytest.fixture
def conn(cfg):
    c = db.connect(cfg.db_path)
    yield c
    c.close()


@pytest.fixture
def crypto(cfg):
    return Crypto(cfg.secret_key)


@pytest.fixture
def settings(conn, crypto):
    return Settings(conn, crypto)


from fastapi.testclient import TestClient

from translator import clerk as clerk_mod
from translator.app import create_app
from translator.providers import Generation, ProviderError, Usage


class FakeClerk:
    _USERS = {"admin": ("user_admin", "admin@x.test"), "user": ("user_u", "u@x.test"), "user2": ("user_v", "v@x.test")}

    async def verify(self, token):
        if token not in self._USERS:
            raise clerk_mod.ClerkError("bad token")
        return {"sub": self._USERS[token][0]}

    async def email(self, uid):
        return next(e for u, e in self._USERS.values() if u == uid)


class FakeGen:
    def __init__(self):
        self.data = {"received_gist": "", "message": "Hallo", "back_translation": "Hello"}
        self.fail = None
        self.calls = []

    async def __call__(self, provider, api_key, model, system, user, schema, http):
        self.calls.append({"provider": provider, "api_key": api_key, "model": model, "system": system, "user": user})
        if self.fail == "provider_error":
            raise ProviderError("fake failure")
        if self.fail == "billed_error":
            raise ProviderError("fake failure after the provider billed", usage=Usage(10, 4096))
        if self.fail == "bad_json":
            return Generation([], Usage(10, 5))
        return Generation(self.data, Usage(10, 5))


@pytest.fixture
def fake_gen():
    return FakeGen()


@pytest.fixture
def turnstile_state():
    return {"ok": True}


@pytest.fixture
def app(cfg, settings, fake_gen, turnstile_state):
    settings.set("turnstile_site_key", "site-key")
    settings.set_secret("turnstile_secret", "ts-secret")
    settings.set_secret("anthropic_api_key", "sk-ant-test")

    async def verify_turnstile(secret, token, ip, hostname=None):
        return turnstile_state["ok"]

    return create_app(cfg, generate=fake_gen, verify_turnstile=verify_turnstile, clerk_verifier=FakeClerk())


@pytest.fixture
def client_factory(app, turnstile_state):
    def make(turnstile_ok=True):
        turnstile_state["ok"] = turnstile_ok
        return TestClient(app, headers={"Origin": "http://testserver"})
    return make


@pytest.fixture
def client(client_factory):
    return client_factory()


@pytest.fixture
def anon_client(client_factory):
    c = client_factory()
    assert c.post("/api/session", json={"turnstile_token": "t"}).status_code == 200
    return c


@pytest.fixture
def user_client(client_factory):
    c = client_factory()
    assert c.post("/api/login/clerk", json={"token": "user"}).status_code == 200
    return c


@pytest.fixture
def admin_client(client_factory):
    c = client_factory()
    assert c.post("/api/login/clerk", json={"token": "admin"}).status_code == 200
    return c
