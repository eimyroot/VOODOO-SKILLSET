from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .fleet import Lease


class FleetCoordinatorError(RuntimeError):
    pass


class FleetCoordinatorClient:
    """Network client for executor/verifier nodes. It never receives database credentials."""

    def __init__(self, base_url: str, bearer_token: str, *, timeout: float = 30.0):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("fleet coordinator URL must be http(s)")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("remote fleet coordinator requires HTTPS; plaintext HTTP is localhost-only")
        if len(bearer_token) < 16:
            raise ValueError("fleet bearer token is missing or too short")
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        req = Request(
            self.base_url + path,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.bearer_token}",
                "User-Agent": "VOODOO-SKILLSET-fleet-node/0.6",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as response:
                raw = response.read(2_097_153)
                if len(raw) > 2_097_152:
                    raise FleetCoordinatorError("fleet coordinator response too large")
                value = json.loads(raw or b"{}")
        except HTTPError as exc:
            detail = exc.read(16_384).decode("utf-8", errors="replace")
            raise FleetCoordinatorError(f"fleet coordinator HTTP {exc.code}: {detail[:2048]}") from exc
        except URLError as exc:
            raise FleetCoordinatorError(f"fleet coordinator unavailable: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise FleetCoordinatorError("fleet coordinator returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise FleetCoordinatorError("fleet coordinator response must be a JSON object")
        return value

    @staticmethod
    def _lease(value: dict[str, Any], owner_id: str) -> Lease | None:
        if value.get("status") == "IDLE":
            return None
        raw = value.get("lease")
        if not isinstance(raw, dict):
            raise FleetCoordinatorError("coordinator omitted lease object")
        token = raw.get("token")
        job = raw.get("job")
        job_id = raw.get("job_id")
        if not isinstance(token, str) or not isinstance(job, dict) or not isinstance(job_id, str):
            raise FleetCoordinatorError("coordinator returned invalid lease")
        return Lease(job_id, owner_id, token, int(raw.get("expires_at") or 0), job)

    def claim_execution(self, worker_id: str, lease_seconds: int = 30) -> Lease | None:
        return self._lease(self._post("/api/fleet/claim", {
            "worker_id": worker_id,
            "lease_seconds": int(lease_seconds),
        }), worker_id)

    def heartbeat_execution(self, job_id: str, worker_id: str, token: str, lease_seconds: int = 30):
        return self._post("/api/fleet/heartbeat", {
            "job_id": job_id,
            "worker_id": worker_id,
            "lease_token": token,
            "lease_seconds": int(lease_seconds),
        }).get("expires_at")

    def complete_execution_signed(self, job_id: str, worker_id: str, token: str, receipt: dict[str, Any], receipt_signature: str) -> dict[str, Any]:
        return self._post("/api/fleet/complete", {
            "job_id": job_id,
            "worker_id": worker_id,
            "lease_token": token,
            "receipt": receipt,
            "receipt_signature": receipt_signature,
        })

    def fail_execution(self, job_id: str, worker_id: str, token: str, error: str, retry_delay_seconds: int = 1) -> dict[str, Any]:
        return self._post("/api/fleet/fail", {
            "job_id": job_id,
            "worker_id": worker_id,
            "lease_token": token,
            "error": error,
            "retry_delay_seconds": int(retry_delay_seconds),
        })

    def claim_verification(self, verifier_id: str, lease_seconds: int = 30) -> Lease | None:
        return self._lease(self._post("/api/fleet/verify/claim", {
            "verifier_id": verifier_id,
            "lease_seconds": int(lease_seconds),
        }), verifier_id)

    def complete_verification(self, job_id: str, verifier_id: str, token: str, verdict: str, proof: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/fleet/verify/complete", {
            "job_id": job_id,
            "verifier_id": verifier_id,
            "lease_token": token,
            "verdict": verdict,
            "proof": proof,
        })
