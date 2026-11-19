import uvicorn

from .app import create_app
from .config import from_env

if __name__ == "__main__":
    cfg = from_env()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1")
