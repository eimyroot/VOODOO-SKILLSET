from __future__ import annotations

import hmac
import json
import mimetypes
import os
import tempfile
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .evidence import EvidenceLedger
from .execution import LinuxNamespaceExecutor, RunStore, run_record
from .executor_bridge import ExecutionRequest, ExecutorProtocolError, RemoteExecutorClient
from .learning import LearningStore
from .models import Mode, RuntimeManifest
from .observability import Metrics
from .orchestrator import Orchestrator
from .registry import CapabilityRegistry


class App:
    def __init__(self, repo_root: Path, state_dir: Path | None = None):
        self.repo_root = repo_root
        if state_dir is None:
            if os.environ.get("VERCEL"):
                state_dir = Path(tempfile.gettempdir()) / "voodoo-skillset-state"
            else:
                state_dir = repo_root / "evidence"
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_persistence = "EPHEMERAL" if os.environ.get("VERCEL") or str(self.state_dir).startswith(tempfile.gettempdir()) else "PERSISTENT_LOCAL"

        self.registry = CapabilityRegistry.from_path(repo_root / "registry/capabilities.json")
        self.learning = LearningStore(self.state_dir / "learning.json")
        self.orchestrator = Orchestrator(self.registry, self.learning)
        self.runtime = RuntimeManifest(
            tools=("web-search", "filesystem-write", "test-runner", "isolated-runner"),
            connectors=("github",),
        )
        self.runs = RunStore(self.state_dir / "runs.jsonl")
        self.ledger = EvidenceLedger(self.state_dir / "runtime-evidence.json")
        self.metrics = Metrics()
        self.lock = threading.Lock()

    @staticmethod
    def executor_configuration():
        url = os.environ.get("VOODOO_EXECUTOR_URL", "").strip()
        secret = os.environ.get("VOODOO_EXECUTOR_SHARED_SECRET", "")
        if not url or not secret:
            return {
                "status": "UNCONFIGURED",
                "execution": "BLOCKED",
                "reason": "VOODOO_EXECUTOR_URL and VOODOO_EXECUTOR_SHARED_SECRET are both required",
                "url_configured": bool(url),
                "secret_configured": bool(secret),
            }
        return {
            "status": "CONFIGURED",
            "execution": "PROBE_REQUIRED",
            "reason": None,
            "url_configured": True,
            "secret_configured": True,
        }

    def executor_status(self):
        config = self.executor_configuration()
        if config["status"] != "CONFIGURED":
            return config
        try:
            client = RemoteExecutorClient(
                os.environ["VOODOO_EXECUTOR_URL"],
                os.environ["VOODOO_EXECUTOR_SHARED_SECRET"],
                timeout=3.0,
            )
            remote = client.health()
            return {
                **config,
                "status": "AVAILABLE" if remote.get("execution") == "AVAILABLE" else "BLOCKED",
                "execution": remote.get("execution", "BLOCKED"),
                "remote": remote,
            }
        except (ValueError, ExecutorProtocolError) as exc:
            return {**config, "status": "UNAVAILABLE", "execution": "BLOCKED", "reason": str(exc)}

    def health(self):
        sandbox_ok, sandbox_reason = LinuxNamespaceExecutor().available()
        executor = self.executor_configuration()
        return {
            "status": "ok",
            "service": "voodoo-skillset",
            "version": "0.4.0",
            "trust_model": "fail-closed",
            "capabilities": len(self.registry.all()),
            "sandbox": "AVAILABLE" if sandbox_ok else "UNAVAILABLE",
            "sandbox_reason": sandbox_reason,
            "remote_executor": executor["status"],
            "remote_execution": executor["execution"],
            "state_persistence": self.state_persistence,
        }

    def capabilities(self):
        return [asdict(c) for c in self.registry.all()]

    def runtime_status(self):
        sandbox_ok, sandbox_reason = LinuxNamespaceExecutor().available()
        return {
            "tools": list(self.runtime.tools),
            "connectors": list(self.runtime.connectors),
            "standing_grants": list(self.runtime.standing_grants),
            "network_default": "DENY",
            "production_mutation": "BLOCKED_BY_DEFAULT",
            "sandbox": {
                "status": "AVAILABLE" if sandbox_ok else "UNAVAILABLE",
                "backend": "linux-namespace-chroot-v1" if sandbox_ok else None,
                "reason": sandbox_reason,
                "egress_allowlist": "BROKER_REQUIRED",
            },
            "remote_executor": self.executor_configuration(),
            "state_persistence": self.state_persistence,
        }

    def learning_status(self):
        return {
            key: {**asdict(value), "routing_signal": value.signal()}
            for key, value in sorted(self.learning.stats.items())
        }

    def evidence_status(self):
        ok, reason = self.ledger.verify()
        return {
            "integrity": "VERIFIED" if ok else "FAILED",
            "reason": reason,
            "head": self.ledger.events[-1].event_hash if self.ledger.events else None,
            "events": [asdict(e) for e in self.ledger.events[-50:]][::-1],
        }

    def verifier_status(self):
        rows = self.runs.list(50)
        verified = [r for r in rows if r.get("metadata", {}).get("plan_status") == "VERIFIED_PLAN"]
        blocked = [r for r in rows if r.get("metadata", {}).get("plan_status") == "BLOCKED"]
        return {
            "independent_verifier": "REQUIRED_FOR_PRO_ALL_REDTEAM",
            "receipt_is_verification": False,
            "verified_plans": len(verified),
            "blocked_plans": len(blocked),
            "last_plan": rows[0] if rows else None,
        }

    @staticmethod
    def policy_status():
        return {
            "invariants": [
                "PROJECT IDENTITY != EXECUTION AUTHORITY",
                "UNKNOWN != PASS",
                "MISSING != PASS",
                "UNVERIFIED != PASS",
                "EXECUTION RECEIPT != INDEPENDENT VERIFICATION",
            ],
            "authority": {
                "READ": "bounded automatic",
                "COMPUTE": "isolated runner required",
                "WRITE": "bounded approval or standing grant",
                "REMOTE_WRITE": "bounded approval or standing grant",
                "DEPLOY": "dedicated approval/grant",
                "DESTRUCTIVE": "explicit one-operation approval",
                "PRIVILEGED": "explicit one-operation approval",
            },
            "network": {"default": "DENY", "selective_egress": "BROKER_REQUIRED"},
            "remote_executor": {
                "protocol": "executor-v1",
                "transport": "HTTPS_REQUIRED_EXCEPT_LOCALHOST",
                "operation_classes": ["COMPUTE"],
                "receipt_is_verification": False,
            },
        }

    def plan(self, payload):
        mode = Mode(payload.get("mode", "ALL").upper())
        rt = RuntimeManifest(
            tuple(payload.get("tools", self.runtime.tools)),
            tuple(payload.get("connectors", self.runtime.connectors)),
            tuple(payload.get("standing_grants", ())),
        )
        self.metrics.inc("plans_requested")
        plan = self.orchestrator.plan(payload["goal"], mode, rt, set(payload.get("exclude", ())))
        with self.lock:
            self.runs.append(run_record(plan.plan_id, "PLANNED", {"plan_status": plan.status, "mode": plan.mode, "goal": plan.goal}))
            self.ledger.append("PLAN", "orchestrator", {"plan_id": plan.plan_id, "status": plan.status, "goal": plan.goal, "mode": plan.mode})
            self.ledger.append("DAG", "composer", {"plan_id": plan.plan_id, "stages": plan.stages})
            self.ledger.append("AUTHORITY_GATES", "policy", {"plan_id": plan.plan_id, "gates": plan.authority_gates})
            self.ledger.append("PLAN_VERIFICATION", "independent-verifier", {"plan_id": plan.plan_id, "status": plan.status})
        if plan.status == "BLOCKED":
            self.metrics.inc("plans_blocked")
        else:
            self.metrics.inc("plans_verified")
        return plan.to_dict()

    def _verified_plan_exists(self, plan_id: str) -> bool:
        return any(
            row.get("plan_id") == plan_id and row.get("metadata", {}).get("plan_status") == "VERIFIED_PLAN"
            for row in self.runs.list(200)
        )

    @staticmethod
    def _require_control_api_token(authorization: str):
        expected = os.environ.get("VOODOO_CONTROL_API_TOKEN", "")
        if not expected:
            raise RuntimeError("execution API disabled: VOODOO_CONTROL_API_TOKEN is not configured")
        prefix = "Bearer "
        if not authorization.startswith(prefix) or not hmac.compare_digest(authorization[len(prefix):], expected):
            raise PermissionError("execution API authorization failed")

    def execute_remote(self, payload, authorization: str):
        self._require_control_api_token(authorization)
        config = self.executor_configuration()
        if config["status"] != "CONFIGURED":
            raise RuntimeError(config["reason"])
        plan_id = payload.get("plan_id")
        if not isinstance(plan_id, str) or not self._verified_plan_exists(plan_id):
            raise PermissionError("execution requires a locally recorded VERIFIED_PLAN")
        if not isinstance(payload.get("workspace_id"), str):
            raise ValueError("workspace_id is required")
        if not isinstance(payload.get("capability_id"), str):
            raise ValueError("capability_id is required")
        argv = payload.get("argv")
        if not isinstance(argv, list):
            raise ValueError("argv must be an array")
        request = ExecutionRequest.create(
            plan_id=plan_id,
            capability_id=payload["capability_id"],
            workspace_id=payload["workspace_id"],
            argv=argv,
            cwd=str(payload.get("cwd", ".")),
            requested_by="control-plane-api",
        )
        client = RemoteExecutorClient(
            os.environ["VOODOO_EXECUTOR_URL"],
            os.environ["VOODOO_EXECUTOR_SHARED_SECRET"],
        )
        self.metrics.inc("executions_requested")
        out = client.execute(request)
        receipt = out["receipt"]
        with self.lock:
            self.runs.append(run_record(plan_id, "EXECUTED", {
                "operation_id": request.operation_id,
                "capability_id": request.capability_id,
                "verification_status": receipt.get("verification_status", "UNKNOWN"),
            }))
            self.ledger.append("EXECUTION_REQUEST", "control-plane", {
                "plan_id": plan_id,
                "operation_id": request.operation_id,
                "capability_id": request.capability_id,
                "workspace_id": request.workspace_id,
                "operation_class": request.operation_class,
            })
            self.ledger.append("EXECUTION_RECEIPT", receipt.get("executor_id", "executor"), {
                "plan_id": plan_id,
                "operation_id": request.operation_id,
                "request_sha256": receipt.get("request_sha256"),
                "verification_status": receipt.get("verification_status", "UNKNOWN"),
                "receipt_signature_verified": out["receipt_signature_verified"],
            })
        self.metrics.inc("executions_receipted")
        return out


def handler_factory(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            endpoints = {
                "/api/health": app.health,
                "/api/capabilities": app.capabilities,
                "/api/runtime": app.runtime_status,
                "/api/executor": app.executor_status,
                "/api/runs": app.runs.list,
                "/api/metrics": app.metrics.snapshot,
                "/api/learning": app.learning_status,
                "/api/evidence": app.evidence_status,
                "/api/verifier": app.verifier_status,
                "/api/policies": app.policy_status,
            }
            if path in endpoints:
                return self._json(endpoints[path]())
            rel = "index.html" if path in {"/", ""} else path.lstrip("/")
            file = (app.repo_root / "web" / rel).resolve()
            web = (app.repo_root / "web").resolve()
            if file != web and web not in file.parents:
                return self._json({"error": "not found"}, 404)
            if not file.exists() or not file.is_file():
                return self._json({"error": "not found"}, 404)
            body = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(file))[0] or "application/octet-stream")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in {"/api/plan", "/api/executor/execute"}:
                return self._json({"error": "not found"}, 404)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n > 131_072:
                    return self._json({"error": "request too large"}, 413)
                payload = json.loads(self.rfile.read(n) or b"{}")
                if path == "/api/plan":
                    if not isinstance(payload.get("goal"), str) or not payload["goal"].strip():
                        raise ValueError("goal is required")
                    return self._json(app.plan(payload))
                return self._json(app.execute_remote(payload, self.headers.get("Authorization", "")))
            except PermissionError as exc:
                return self._json({"error": str(exc)}, 403)
            except ExecutorProtocolError as exc:
                return self._json({"error": str(exc)}, 502)
            except RuntimeError as exc:
                return self._json({"error": str(exc)}, 503)
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                return self._json({"error": str(exc)}, 400)

        def log_message(self, fmt, *args):
            pass

    return Handler


def serve(repo_root: Path, host="127.0.0.1", port=8787):
    app = App(repo_root)
    server = ThreadingHTTPServer((host, port), handler_factory(app))
    print(f"VOODOO-SKILLSET http://{host}:{port}")
    server.serve_forever()
