import logging
import os

import uvicorn

from . import providers
from .app import create_app
from .config import Config, from_env


async def fake_generate(provider, api_key, model, system, user, schema, http) -> providers.Generation:
    """Canned provider for local UI checks (TRANSLATOR_FAKE_PROVIDER=1). Never used by default."""
    reply = "<received_message>" in user
    tweaked = "<change_request>" in user
    message = "Sehr geehrter Herr Müller,\n\nich kann leider nur am Dienstag. Passt Ihnen das?\n\nMit freundlichen Grüßen"
    back = "Dear Mr Müller, unfortunately I can only do Tuesday. Does that suit you?\n\nKind regards"
    if tweaked:
        message, back = "Ich kann nur am Dienstag. Passt das?", "I can only do Tuesday. Does that work?"
    return providers.Generation(
        {"received_gist": "The landlord asks when you can meet." if reply else "",
         "message": message, "back_translation": back},
        providers.Usage(10, 10))


def build_app(cfg: Config):
    if os.environ.get("TRANSLATOR_FAKE_PROVIDER") == "1":
        logging.getLogger("uvicorn.error").warning(
            "TRANSLATOR_FAKE_PROVIDER=1: using a FAKE provider, no real model is called. Never use in production.")
        return create_app(cfg, generate=fake_generate)
    return create_app(cfg)


if __name__ == "__main__":
    cfg = from_env()
    # limit_concurrency: answer 503 instead of buffering hundreds of request bodies inside the 128 MB container.
    uvicorn.run(build_app(cfg), host=cfg.host, port=cfg.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1",
                limit_concurrency=100)
