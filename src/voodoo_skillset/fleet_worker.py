from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from .container_executor import configured_executor_adapter
from .executor_bridge import ExecutorService, ExecutionRequest, sign_payload, verify_signature
from .fleet import DurableFleetStore, workspace_manifest_digest


class FleetWorker:
    def __init__(
        self,
        store: DurableFleetStore,
        workspace_root: str | Path,
        shared_secret: str,
        worker_id: str,
        *,
        adapter=None,
    ):
        self.store = store
        self.workspace_root = Path(workspace_root).resolve()
        self.shared_secret = shared_secret
        self.worker_id = worker_id
        self.service = ExecutorService(
            self.workspace_root,
            shared_secret,
            executor_id=worker_id,
            adapter=adapter or configured_executor_adapter(),
        )

    def run_once(self) -> dict[str, Any]:
        lease = self.store.claim_execution(self.worker_id)
        if lease is None:
            return {"status": "IDLE", "worker_id": self.worker_id}
        job = lease.job
        try:
            request = ExecutionRequest.create(
                plan_id=job["plan_id"],
                capability_id=job["capability_id"],
                workspace_id=job["workspace_id"],
                argv=job["argv"],
                cwd=job["cwd"],
                requested_by=f"fleet:{self.worker_id}",
            )
            value = request.to_dict()
            response = self.service.execute_signed(value, sign_payload(value, self.shared_secret))
            receipt = response["receipt"]
            signature_ok = verify_signature(receipt, response["signature"], self.shared_secret)
            final = self.store.complete_execution(
                lease.job_id,
                self.worker_id,
                lease.token,
                receipt,
                receipt_signature_verified=signature_ok,
            )
            return {
                "status": "EXECUTED",
                "worker_id": self.worker_id,
                "job_id": lease.job_id,
                "receipt_sha256": final["receipt_sha256"],
                "verification_status": receipt["verification_status"],
            }
        except Exception as exc:
            try:
                failed = self.store.fail_execution(lease.job_id, self.worker_id, lease.token, str(exc))
                state = failed["state"]
            except Exception:
                state = "LEASE_UNCERTAIN"
            return {
                "status": "FAILED",
                "worker_id": self.worker_id,
                "job_id": lease.job_id,
                "queue_state": state,
                "error": str(exc),
            }


class IndependentFleetVerifier:
    """Verifier process intentionally separate from the executor worker identity."""

    def __init__(self, store: DurableFleetStore, workspace_root: str | Path, verifier_id: str):
        self.store = store
        self.workspace_root = Path(workspace_root).resolve()
        self.verifier_id = verifier_id

    def _workspace(self, workspace_id: str) -> Path:
        target = (self.workspace_root / workspace_id).resolve()
        if target.parent != self.workspace_root or not target.is_dir():
            raise ValueError("verification workspace is missing or escaped root")
        return target

    def _checks(self, job: dict[str, Any]) -> tuple[dict[str, bool], dict[str, Any]]:
        receipt = job.get("receipt") or {}
        result = receipt.get("result") or {}
        spec = job.get("verification_spec") or {}
        if not spec:
            raise RuntimeError("independent verification spec is missing; cannot claim PASS")

        checks: dict[str, bool] = {
            "receipt_remains_unknown": receipt.get("verification_status") == "UNKNOWN",
            "receipt_hash_present": isinstance(job.get("receipt_sha256"), str) and len(job["receipt_sha256"]) == 64,
        }
        observed: dict[str, Any] = {
            "receipt_sha256": job.get("receipt_sha256"),
            "runner": result.get("runner"),
            "exit_code": result.get("exit_code"),
            "persistent_effect": result.get("persistent_effect"),
        }

        if "expected_exit_code" in spec:
            checks["exit_code"] = result.get("exit_code") == spec["expected_exit_code"]
        if "runner" in spec:
            checks["runner"] = result.get("runner") == spec["runner"]
        if "persistent_effect" in spec:
            checks["persistent_effect"] = result.get("persistent_effect") == spec["persistent_effect"]
        if "network_default" in spec:
            checks["network_default"] = (result.get("isolation") or {}).get("network_default") == spec["network_default"]
        if "root_filesystem" in spec:
            checks["root_filesystem"] = (result.get("isolation") or {}).get("root_filesystem") == spec["root_filesystem"]
        if "capabilities" in spec:
            checks["capabilities"] = (result.get("isolation") or {}).get("capabilities") == spec["capabilities"]
        if "stdout_contains" in spec:
            expected = spec["stdout_contains"]
            if not isinstance(expected, list) or not all(isinstance(item, str) and item for item in expected):
                raise ValueError("stdout_contains verification spec must be a non-empty string array")
            stdout = str(result.get("stdout", ""))
            for index, item in enumerate(expected):
                checks[f"stdout_contains_{index}"] = item in stdout
        if spec.get("require_workspace_unchanged"):
            before = job.get("workspace_before_sha256")
            after = workspace_manifest_digest(self._workspace(job["workspace_id"]))
            observed["workspace_before_sha256"] = before
            observed["workspace_after_sha256"] = after
            checks["workspace_unchanged"] = isinstance(before, str) and before == after

        outcome_keys = set(checks) - {"receipt_remains_unknown", "receipt_hash_present"}
        if not outcome_keys:
            raise RuntimeError("verification spec has no independent outcome assertions")
        return checks, observed

    def run_once(self) -> dict[str, Any]:
        lease = self.store.claim_verification(self.verifier_id)
        if lease is None:
            return {"status": "IDLE", "verifier_id": self.verifier_id}
        try:
            checks, observed = self._checks(lease.job)
            verdict = "VERIFIED" if all(checks.values()) else "FAILED"
            proof = {
                "checks": checks,
                "observed": observed,
                "method": "independent-fleet-verifier-v1",
            }
            final = self.store.complete_verification(
                lease.job_id,
                self.verifier_id,
                lease.token,
                verdict,
                proof,
            )
            return {
                "status": verdict,
                "verifier_id": self.verifier_id,
                "job_id": lease.job_id,
                "checks": checks,
                "queue_state": final["state"],
            }
        except Exception as exc:
            return {
                "status": "BLOCKED",
                "verifier_id": self.verifier_id,
                "job_id": lease.job_id,
                "error": str(exc),
                "queue_state": "VERIFYING_UNTIL_LEASE_EXPIRY",
            }


def _secret() -> str:
    secret = os.environ.get("VOODOO_EXECUTOR_SHARED_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise SystemExit("VOODOO_EXECUTOR_SHARED_SECRET must contain at least 32 bytes")
    return secret


def worker_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="voodoo-fleet-worker")
    parser.add_argument("--db", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--drain", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=100)
    args = parser.parse_args(argv)
    worker = FleetWorker(DurableFleetStore(args.db), args.workspace_root, _secret(), args.worker_id)
    done = 0
    while done < args.max_jobs:
        result = worker.run_once()
        print(json.dumps(result, sort_keys=True), flush=True)
        if result["status"] == "IDLE":
            break
        done += 1
        if not args.drain:
            break
        time.sleep(0.02)
    return 0 if all(True for _ in [0]) else 1


def verifier_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="voodoo-fleet-verifier")
    parser.add_argument("--db", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--verifier-id", required=True)
    parser.add_argument("--drain", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=100)
    args = parser.parse_args(argv)
    verifier = IndependentFleetVerifier(DurableFleetStore(args.db), args.workspace_root, args.verifier_id)
    done = 0
    blocked = False
    while done < args.max_jobs:
        result = verifier.run_once()
        print(json.dumps(result, sort_keys=True), flush=True)
        if result["status"] == "IDLE":
            break
        if result["status"] == "BLOCKED":
            blocked = True
            break
        done += 1
        if not args.drain:
            break
        time.sleep(0.02)
    return 2 if blocked else 0


if __name__ == "__main__":
    command = Path(sys.argv[0]).name
    if "verifier" in command:
        raise SystemExit(verifier_main())
    raise SystemExit(worker_main())
