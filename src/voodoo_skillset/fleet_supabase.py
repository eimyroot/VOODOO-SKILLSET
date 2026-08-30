from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from .fleet import Lease


class SupabaseFleetError(RuntimeError):
    pass


class SupabaseFleetStore:
    """Server-side PostgREST adapter for the R3 durable fleet RPC contract."""

    def __init__(self, project_url: str, service_role_key: str, *, timeout: float = 15.0):
        parsed = urlparse(project_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Supabase project URL must use HTTPS")
        if len(service_role_key) < 20:
            raise ValueError("Supabase service role key is missing or invalid")
        self.project_url = project_url.rstrip("/")
        self.service_role_key = service_role_key
        self.timeout = timeout

    def _request(self, path: str, *, method: str = "GET", payload: Any = None, prefer: str | None = None) -> Any:
        data = None
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Accept": "application/json",
            "User-Agent": "VOODOO-SKILLSET-fleet/0.6",
        }
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        req = Request(self.project_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as response:
                body = response.read(2_097_153)
                if len(body) > 2_097_152:
                    raise SupabaseFleetError("Supabase fleet response too large")
                if not body:
                    return None
                return json.loads(body)
        except HTTPError as exc:
            detail = exc.read(16_384).decode("utf-8", errors="replace")
            raise SupabaseFleetError(f"Supabase fleet HTTP {exc.code}: {detail[:2048]}") from exc
        except URLError as exc:
            raise SupabaseFleetError(f"Supabase fleet unavailable: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise SupabaseFleetError("Supabase fleet returned invalid JSON") from exc

    def _rpc(self, name: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request(f"/rest/v1/rpc/{quote(name, safe='')}", method="POST", payload=payload or {})

    @staticmethod
    def _lease(value: dict[str, Any] | None, owner_id: str) -> Lease | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise SupabaseFleetError("claim RPC returned invalid payload")
        token = value.pop("lease_token", None)
        expires = value.pop("lease_expires_at", None)
        if not isinstance(token, str) or not token:
            raise SupabaseFleetError("claim RPC omitted lease token")
        if isinstance(expires, str):
            try:
                expires_at = int(datetime.fromisoformat(expires.replace("Z", "+00:00")).timestamp())
            except ValueError:
                expires_at = 0
        else:
            expires_at = 0
        job_id = value.get("job_id")
        if not isinstance(job_id, str):
            raise SupabaseFleetError("claim RPC omitted job_id")
        return Lease(job_id, owner_id, token, expires_at, value)

    def record_plan(self, plan: dict[str, Any]) -> None:
        self._rpc("voodoo_record_plan", {"p_plan": plan})

    def verified_plan_exists(self, plan_id: str) -> bool:
        return bool(self._rpc("voodoo_verified_plan_exists", {"p_plan_id": plan_id}))

    def enqueue(
        self,
        *,
        plan_id: str,
        workspace_id: str,
        capability_id: str,
        argv: list[str] | tuple[str, ...],
        cwd: str = ".",
        verification_spec: dict[str, Any] | None = None,
        workspace_before_sha256: str | None = None,
        priority: int = 100,
        max_attempts: int = 3,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        spec = verification_spec or {}
        if not spec:
            raise ValueError("non-empty verification_spec required for durable fleet jobs")
        out = self._rpc("voodoo_enqueue_job", {
            "p_plan_id": plan_id,
            "p_workspace_id": workspace_id,
            "p_capability_id": capability_id,
            "p_argv": list(argv),
            "p_cwd": cwd,
            "p_verification_spec": spec,
            "p_workspace_before_sha256": workspace_before_sha256,
            "p_priority": int(priority),
            "p_max_attempts": int(max_attempts),
            "p_job_id": job_id,
        })
        if not isinstance(out, dict):
            raise SupabaseFleetError("enqueue RPC returned invalid payload")
        return out

    def get_job(self, job_id: str) -> dict[str, Any]:
        query = urlencode({"job_id": f"eq.{job_id}", "select": "*", "limit": "1"})
        rows = self._request(f"/rest/v1/voodoo_jobs?{query}")
        if not isinstance(rows, list) or not rows:
            raise KeyError(job_id)
        row = dict(rows[0])
        row.pop("execution_lease_hash", None)
        row.pop("verification_lease_hash", None)
        return row

    def claim_execution(self, worker_id: str, lease_seconds: int = 30) -> Lease | None:
        return self._lease(self._rpc("voodoo_claim_execution", {
            "p_worker_id": worker_id,
            "p_lease_seconds": int(lease_seconds),
        }), worker_id)

    def heartbeat_execution(self, job_id: str, worker_id: str, token: str, lease_seconds: int = 30):
        return self._rpc("voodoo_heartbeat_execution", {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
            "p_token": token,
            "p_lease_seconds": int(lease_seconds),
        })

    def complete_execution(self, job_id: str, worker_id: str, token: str, receipt: dict[str, Any], *, receipt_signature_verified: bool) -> dict[str, Any]:
        out = self._rpc("voodoo_complete_execution", {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
            "p_token": token,
            "p_receipt": receipt,
            "p_receipt_signature_verified": bool(receipt_signature_verified),
        })
        if not isinstance(out, dict):
            raise SupabaseFleetError("complete execution RPC returned invalid payload")
        return out

    def fail_execution(self, job_id: str, worker_id: str, token: str, error: str, retry_delay_seconds: int = 1) -> dict[str, Any]:
        out = self._rpc("voodoo_fail_execution", {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
            "p_token": token,
            "p_error": error,
            "p_retry_delay_seconds": int(retry_delay_seconds),
        })
        if not isinstance(out, dict):
            raise SupabaseFleetError("fail execution RPC returned invalid payload")
        return out

    def claim_verification(self, verifier_id: str, lease_seconds: int = 30) -> Lease | None:
        return self._lease(self._rpc("voodoo_claim_verification", {
            "p_verifier_id": verifier_id,
            "p_lease_seconds": int(lease_seconds),
        }), verifier_id)

    def complete_verification(self, job_id: str, verifier_id: str, token: str, verdict: str, proof: dict[str, Any]) -> dict[str, Any]:
        out = self._rpc("voodoo_complete_verification", {
            "p_job_id": job_id,
            "p_verifier_id": verifier_id,
            "p_token": token,
            "p_verdict": verdict,
            "p_proof": proof,
        })
        if not isinstance(out, dict):
            raise SupabaseFleetError("complete verification RPC returned invalid payload")
        return out

    def stats(self) -> dict[str, Any]:
        out = self._rpc("voodoo_fleet_stats")
        if not isinstance(out, dict):
            raise SupabaseFleetError("fleet stats RPC returned invalid payload")
        return out

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        query = urlencode({
            "select": "seq,job_id,kind,actor,payload,created_at,prev_hash,event_hash",
            "order": "seq.desc",
            "limit": str(max(1, min(int(limit), 1000))),
        })
        rows = self._request(f"/rest/v1/voodoo_fleet_events?{query}")
        if not isinstance(rows, list):
            raise SupabaseFleetError("fleet events response invalid")
        return rows

    def verify_event_chain(self) -> tuple[bool, str]:
        out = self._rpc("voodoo_verify_event_chain")
        if not isinstance(out, dict):
            raise SupabaseFleetError("event verification RPC returned invalid payload")
        return bool(out.get("ok")), str(out.get("reason", "unknown"))
