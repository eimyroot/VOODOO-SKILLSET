from __future__ import annotations

import argparse
import os
from pathlib import Path

from .container_executor import configured_executor_adapter
from .executor_bridge import build_executor_server


def main(argv=None):
    parser = argparse.ArgumentParser(prog="voodoo-executor")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)

    secret = os.environ.get("VOODOO_EXECUTOR_SHARED_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        parser.error("VOODOO_EXECUTOR_SHARED_SECRET must contain at least 32 bytes")

    adapter = configured_executor_adapter()
    ok, reason = adapter.available()
    if not ok:
        parser.error(f"safe executor backend unavailable: {reason}")

    root = Path(args.workspace_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    server = build_executor_server(root, secret, host=args.host, port=args.port, adapter=adapter)
    print(f"VOODOO CASTER-MINAL executor http://{args.host}:{server.server_address[1]} backend={getattr(adapter, 'active_backend_name', getattr(adapter, 'backend_name', adapter.__class__.__name__))}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
