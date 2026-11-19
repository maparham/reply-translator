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
