from __future__ import annotations

import argparse
import sys
from pathlib import Path

from uvicorn import Config, Server


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from app.main import app

    parser = argparse.ArgumentParser(description="Run Agent Krypto web server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    config = Config(app=app, host=args.host, port=args.port, reload=False, access_log=True)
    server = Server(config=config)
    server.run()


if __name__ == "__main__":
    main()