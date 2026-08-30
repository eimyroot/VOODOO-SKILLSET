from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .execution import ExecutionEnvelope, LinuxNamespaceExecutor, NetworkPolicy

SIGNATURE_HEADER = "X-VOODOO-Signature"
PROTOCOL_HEADER = "X-VOODOO-Protocol"
PROTOCOL_VERSION = "executor-v1"
MAX_REQUEST_BYTES = 65_536
MAX_TTL_SECONDS = 120
CLOCK_SKEW_SECONDS = 5
WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CAPABILITY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ExecutorProtocolError(RuntimeError):
    pass


class ExecutorAuthError(ExecutorProtocolError):
    pass


class ExecutorPolicyError(ExecutorProtocolError):
    pass


class ExecutionAdapter(Protocol):
    def execute(self, capability_id: str, payload: dict[str, Any], envelope: ExecutionEnvelope) -> dict[str, Any]: ...


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _secret_bytes(secret: str | bytes) -> bytes:
    raw = secret if isinstance(secret, bytes) else secret.encode("utf-8")
    if len(raw) < 32:
        raise ValueError("executor shared secret must be at least 32 bytes")
    return raw


def payload_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sign_payload(value: dict[str, Any], secret: str | bytes) -> str:
    digest = hmac.new(_secret_bytes(secret), canonical_json(value), hashlib.sha256).hexdigest()
    return f"v1={digest}"


def verify_signature(value: dict[str, Any], signature: str, secret: str | bytes) -> bool:
    if not isinstance(signature, str) or not signature.startswith("v1="):
        return False
    return hmac.compare_digest(sign_payload(value, secret), signature)


@dataclass(frozen=True)
class ExecutionRequest:
    operation_id: str
    plan_id: str
    capability_id: str
    operation_class: str
    workspace_id: str
    argv: tuple[str, ...]
    cwd: str
    network_default: str
    allowed_hosts: tuple[str, ...]
    issued_at: int
    expires_at: int
    nonce: str
    requested_by: str

    @classmethod
    def create(
        cls,
        *,
        plan_id: str,
        capability_id: str,
        workspace_id: str,
        argv: list[str] | tuple[str, ...],
        cwd: str = ".",
        requested_by: str = "control-plane",
        ttl_seconds: int = 60,
        now: int | None = None,
    ) -> "ExecutionRequest":
        current = int(time.time() if now is None else now)
        if ttl_seconds < 1 or ttl_seconds > MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")
        req = cls(
            operation_id=f"OP-{uuid.uuid4().hex[:16]}",
            plan_id=plan_id,
            capability_id=capability_id,
            operation_class="COMPUTE",
            workspace_id=workspace_id,
            argv=tuple(argv),
            cwd=cwd,
            network_default="DENY",
            allowed_hosts=(),
            issued_at=current,
            expires_at=current + ttl_seconds,
            nonce=uuid.uuid4().hex,
            requested_by=requested_by,
        )
        req.validate(current)
        return req

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionRequest":
        try:
            req = cls(
                operation_id=str(value["operation_id"]),
                plan_id=str(value["plan_id"]),
                capability_id=str(value["capability_id"]),
                operation_class=str(value["operation_class"]),
                workspace_id=str(value["workspace_id"]),
                argv=tuple(value["argv"]),
                cwd=str(value.get("cwd", ".")),
                network_default=str(value["network_default"]),
                allowed_hosts=tuple(value.get("allowed_hosts", ())),
                issued_at=int(value["issued_at"]),
                expires_at=int(value["expires_at"]),
                nonce=str(value["nonce"]),
                requested_by=str(value["requested_by"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutorProtocolError(f"invalid execution request: {exc}") from exc
        return req

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["argv"] = list(self.argv)
        value["allowed_hosts"] = list(self.allowed_hosts)
        return value

    def validate(self, now: int | None = None) -> None:
        current = int(time.time() if now is None else now)
        if not self.operation_id.startswith("OP-") or len(self.operation_id) > 64:
            raise ExecutorProtocolError("invalid operation_id")
        if not self.plan_id or len(self.plan_id) > 128:
            raise ExecutorProtocolError("invalid plan_id")
        if not CAPABILITY_ID_RE.fullmatch(self.capability_id):
            raise ExecutorProtocolError("invalid capability_id")
        if self.operation_class != "COMPUTE":
            raise ExecutorPolicyError("executor-v1 authorizes COMPUTE only")
        if not WORKSPACE_ID_RE.fullmatch(self.workspace_id):
            raise ExecutorPolicyError("invalid workspace_id")
        if not self.argv or len(self.argv) > 64:
            raise ExecutorProtocolError("argv must contain 1..64 arguments")
        if any(not isinstance(arg, str) or not arg or len(arg) > 4096 for arg in self.argv):
            raise ExecutorProtocolError("invalid argv")
        cwd = Path(self.cwd)
        if cwd.is_absolute() or ".." in cwd.parts or len(self.cwd) > 512:
            raise ExecutorPolicyError("cwd must stay relative to the workspace")
        if self.network_default != "DENY":
            raise ExecutorPolicyError("executor-v1 requires deny-by-default network")
        if self.allowed_hosts:
            raise ExecutorPolicyError("selective egress is unavailable in executor-v1")
        if not self.nonce or len(self.nonce) > 128:
            raise ExecutorProtocolError("invalid nonce")
        if not self.requested_by or len(self.requested_by) > 128:
            raise ExecutorProtocolError("invalid requested_by")
        ttl = self.expires_at - self.issued_at
        if ttl < 1 or ttl > MAX_TTL_SECONDS:
            raise ExecutorAuthError("request TTL outside allowed window")
        if self.issued_at > current + CLOCK_SKEW_SECONDS:
            raise ExecutorAuthError("request issued in the future")
        if self.expires_at < current:
            raise ExecutorAuthError("request expired")


class ReplayGuard:
    """Persistent nonce ledger. SQLite UNIQUE constraint makes replay fail closed across restarts."""

    def __init__(self, path: str | Path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._lock = threading.Lock()
        db = sqlite3.connect(self.path)
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)"
            )
            db.commit()
        finally:
            db.close()

    def claim(self, nonce: str, expires_at: int) -> bool:
        now = int(self.clock())
        with self._lock:
            db = sqlite3.connect(self.path, timeout=5)
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM nonces WHERE expires_at < ?", (now,))
                db.execute("INSERT INTO nonces(nonce, expires_at) VALUES(?, ?)", (nonce, expires_at))
                db.commit()
                return True
            except sqlite3.IntegrityError:
                db.rollback()
                return False
            finally:
                db.close()


class ExecutorService:
    def __init__(
        self,
        workspace_root: str | Path,
        shared_secret: str | bytes,
        *,
        executor_id: str = "caster-minal-r1",
        adapter: ExecutionAdapter | None = None,
        replay_guard: ReplayGuard | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.shared_secret = _secret_bytes(shared_secret)
        self.executor_id = executor_id
        self.adapter = adapter or LinuxNamespaceExecutor()
        self.clock = clock
        self.replay_guard = replay_guard or ReplayGuard(self.workspace_root / ".voodoo-executor-replay.sqlite3", clock)

    def health(self) -> dict[str, Any]:
        if hasattr(self.adapter, "available"):
            ok, reason = self.adapter.available()  # type: ignore[attr-defined]
        else:
            ok, reason = True, "adapter does not expose availability probe"
        return {
            "status": "ok" if ok else "blocked",
            "service": "voodoo-skillset-executor",
            "protocol": PROTOCOL_VERSION,
            "executor_id": self.executor_id,
            "execution": "AVAILABLE" if ok else "BLOCKED",
            "reason": reason,
            "operation_classes": ["COMPUTE"],
            "network_default": "DENY",
            "receipt_is_verification": False,
            "replay_protection": "SQLITE_PERSISTENT",
        }

    def _workspace(self, workspace_id: str) -> Path:
        if not WORKSPACE_ID_RE.fullmatch(workspace_id):
            raise ExecutorPolicyError("invalid workspace_id")
        target = (self.workspace_root / workspace_id).resolve()
        if target.parent != self.workspace_root:
            raise ExecutorPolicyError("workspace escaped executor root")
        if not target.is_dir():
            raise ExecutorPolicyError("workspace does not exist")
        return target

    def execute_signed(self, value: dict[str, Any], signature: str) -> dict[str, Any]:
        if not verify_signature(value, signature, self.shared_secret):
            raise ExecutorAuthError("request signature invalid")
        req = ExecutionRequest.from_dict(value)
        now = int(self.clock())
        req.validate(now)
        if not self.replay_guard.claim(req.nonce, req.expires_at):
            raise ExecutorAuthError("request replay detected")
        target = self._workspace(req.workspace_id)
        envelope = ExecutionEnvelope(
            operation_id=req.operation_id,
            target=str(target),
            network_policy=NetworkPolicy("DENY", ()),
            isolation_required=True,
        )
        result = self.adapter.execute(
            req.capability_id,
            {"argv": list(req.argv), "cwd": req.cwd},
            envelope,
        )
        receipt = {
            "protocol": PROTOCOL_VERSION,
            "executor_id": self.executor_id,
            "operation_id": req.operation_id,
            "plan_id": req.plan_id,
            "request_sha256": payload_sha256(value),
            "issued_at": int(self.clock()),
            "verification_status": result.get("verification_status", "UNKNOWN"),
            "result": result,
        }
        return {"receipt": receipt, "signature": sign_payload(receipt, self.shared_secret)}


def executor_handler_factory(service: ExecutorService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VOODOOExecutor/1"

        def _json(self, value: dict[str, Any], status: int = 200):
            body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(PROTOCOL_HEADER, PROTOCOL_VERSION)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlparse(self.path).path == "/health":
                return self._json(service.health())
            return self._json({"error": "not found"}, 404)

        def do_POST(self):
            if urlparse(self.path).path != "/v1/execute":
                return self._json({"error": "not found"}, 404)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > MAX_REQUEST_BYTES:
                    return self._json({"error": "request size invalid"}, 413)
                value = json.loads(self.rfile.read(size))
                if not isinstance(value, dict):
                    raise ExecutorProtocolError("JSON object required")
                signature = self.headers.get(SIGNATURE_HEADER, "")
                return self._json(service.execute_signed(value, signature))
            except ExecutorAuthError as exc:
                return self._json({"error": str(exc)}, 401)
            except ExecutorPolicyError as exc:
                return self._json({"error": str(exc)}, 403)
            except (ExecutorProtocolError, json.JSONDecodeError, ValueError) as exc:
                return self._json({"error": str(exc)}, 400)
            except Exception:
                return self._json({"error": "executor failure"}, 500)

        def log_message(self, fmt, *args):
            pass

    return Handler


def build_executor_server(
    workspace_root: str | Path,
    shared_secret: str | bytes,
    *,
    host: str = "127.0.0.1",
    port: int = 8790,
    adapter: ExecutionAdapter | None = None,
) -> ThreadingHTTPServer:
    service = ExecutorService(workspace_root, shared_secret, adapter=adapter)
    return ThreadingHTTPServer((host, port), executor_handler_factory(service))


def serve_executor(
    workspace_root: str | Path,
    shared_secret: str | bytes,
    *,
    host: str = "127.0.0.1",
    port: int = 8790,
) -> None:
    server = build_executor_server(workspace_root, shared_secret, host=host, port=port)
    print(f"VOODOO executor {PROTOCOL_VERSION} http://{host}:{server.server_address[1]}")
    server.serve_forever()


class RemoteExecutorClient:
    def __init__(self, base_url: str, shared_secret: str | bytes, *, timeout: float = 30.0):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("executor URL must be http(s)")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("remote executor requires HTTPS; plaintext HTTP is localhost-only")
        self.base_url = base_url.rstrip("/")
        self.shared_secret = _secret_bytes(shared_secret)
        self.timeout = timeout

    def _request(self, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"User-Agent": "VOODOO-SKILLSET-control-plane/1.0", PROTOCOL_HEADER: PROTOCOL_VERSION}
        method = "GET"
        if payload is not None:
            data = canonical_json(payload)
            headers["Content-Type"] = "application/json"
            headers[SIGNATURE_HEADER] = sign_payload(payload, self.shared_secret)
            method = "POST"
        req = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as response:
                body = response.read(MAX_REQUEST_BYTES + 1)
                if len(body) > MAX_REQUEST_BYTES:
                    raise ExecutorProtocolError("executor response too large")
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise ExecutorProtocolError("executor returned non-object JSON")
                return value
        except HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise ExecutorProtocolError(f"executor HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ExecutorProtocolError(f"executor unavailable: {exc}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("/health")

    def execute(self, request: ExecutionRequest) -> dict[str, Any]:
        value = request.to_dict()
        response = self._request("/v1/execute", payload=value)
        receipt = response.get("receipt")
        signature = response.get("signature")
        if not isinstance(receipt, dict) or not isinstance(signature, str):
            raise ExecutorProtocolError("executor response missing signed receipt")
        if not verify_signature(receipt, signature, self.shared_secret):
            raise ExecutorAuthError("receipt signature invalid")
        if receipt.get("operation_id") != request.operation_id:
            raise ExecutorProtocolError("receipt operation_id mismatch")
        if receipt.get("request_sha256") != payload_sha256(value):
            raise ExecutorProtocolError("receipt request hash mismatch")
        return {
            "receipt": receipt,
            "receipt_signature_verified": True,
            "independent_verification": "PENDING",
        }


def client_from_env() -> RemoteExecutorClient | None:
    url = os.environ.get("VOODOO_EXECUTOR_URL", "").strip()
    secret = os.environ.get("VOODOO_EXECUTOR_SHARED_SECRET", "")
    if not url or not secret:
        return None
    return RemoteExecutorClient(url, secret)
