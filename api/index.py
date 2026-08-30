from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from voodoo_skillset.api import App  # noqa: E402
from voodoo_skillset.executor_bridge import ExecutorProtocolError  # noqa: E402

_APP = App(ROOT)


class handler(BaseHTTPRequestHandler):
    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        q = parse_qs(urlparse(self.path).query)
        return q.get("route", [""])[0].strip("/")

    def do_GET(self):
        route = self._route()
        endpoints = {
            "health": _APP.health,
            "capabilities": _APP.capabilities,
            "runtime": _APP.runtime_status,
            "executor": _APP.executor_status,
            "runs": _APP.runs.list,
            "metrics": _APP.metrics.snapshot,
            "learning": _APP.learning_status,
            "evidence": _APP.evidence_status,
            "verifier": _APP.verifier_status,
            "policies": _APP.policy_status,
        }
        fn = endpoints.get(route)
        return self._json(fn()) if fn else self._json({"error": "not found"}, 404)

    def do_POST(self):
        route = self._route()
        if route not in {"plan", "executor/execute"}:
            return self._json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 131_072:
                return self._json({"error": "request too large"}, 413)
            payload = json.loads(self.rfile.read(n) or b"{}")
            if route == "plan":
                if not isinstance(payload.get("goal"), str) or not payload["goal"].strip():
                    raise ValueError("goal is required")
                return self._json(_APP.plan(payload))
            return self._json(_APP.execute_remote(payload, self.headers.get("Authorization", "")))
        except PermissionError as exc:
            return self._json({"error": str(exc)}, 403)
        except ExecutorProtocolError as exc:
            return self._json({"error": str(exc)}, 502)
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 503)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return self._json({"error": str(exc)}, 400)
