from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any, Callable
import uuid

from .executor_bridge import CAPABILITY_ID_RE, WORKSPACE_ID_RE, canonical_json

JOB_STATES = {
    "QUEUED",
    "LEASED",
    "EXECUTED",
    "VERIFYING",
    "VERIFIED",
    "FAILED",
    "BLOCKED",
}
FINAL_STATES = {"VERIFIED", "FAILED", "BLOCKED"}
WORKER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
GENESIS_HASH = "0" * 64


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _token_hash(token: str) -> str:
    return _sha256_bytes(token.encode("utf-8"))


def workspace_manifest_digest(root: str | Path) -> str:
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError("workspace must be a directory")
    rows: list[tuple[str, str, int]] = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            rows.append((path.relative_to(base).as_posix(), f"SYMLINK:{path.readlink()}", 0))
            continue
        if path.is_file():
            data = path.read_bytes()
            rows.append((path.relative_to(base).as_posix(), _sha256_bytes(data), len(data)))
    return _sha256_bytes(json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


@dataclass(frozen=True)
class Lease:
    job_id: str
    owner_id: str
    token: str
    expires_at: int
    job: dict[str, Any]


class DurableFleetStore:
    """SQLite durable reference for fleet state, leases and append-only evidence.

    This is appropriate for one durable coordinator volume. Production multi-instance
    serverless deployments should use the equivalent Postgres/Supabase contract.
    """

    def __init__(self, path: str | Path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _init_db(self) -> None:
        db = self._connect()
        try:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL REFERENCES plans(plan_id),
                    workspace_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    argv_json TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    verification_spec_json TEXT NOT NULL,
                    workspace_before_sha256 TEXT,
                    state TEXT NOT NULL CHECK(state IN ('QUEUED','LEASED','EXECUTED','VERIFYING','VERIFIED','FAILED','BLOCKED')),
                    priority INTEGER NOT NULL DEFAULT 100,
                    available_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    execution_worker_id TEXT,
                    execution_lease_hash TEXT,
                    execution_lease_expires_at INTEGER,
                    receipt_json TEXT,
                    receipt_sha256 TEXT,
                    verifier_id TEXT,
                    verification_lease_hash TEXT,
                    verification_lease_expires_at INTEGER,
                    verification_json TEXT,
                    last_error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_exec_claim
                    ON jobs(state, available_at, priority, created_at);
                CREATE INDEX IF NOT EXISTS idx_jobs_verify_claim
                    ON jobs(state, updated_at);

                CREATE TABLE IF NOT EXISTS fleet_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    kind TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                );
                """
            )
        finally:
            db.close()

    @staticmethod
    def _validate_owner(owner_id: str) -> None:
        if not WORKER_ID_RE.fullmatch(owner_id):
            raise ValueError("invalid worker/verifier id")

    @staticmethod
    def _validate_job_input(
        workspace_id: str,
        capability_id: str,
        argv: list[str] | tuple[str, ...],
        cwd: str,
        max_attempts: int,
    ) -> None:
        if not WORKSPACE_ID_RE.fullmatch(workspace_id):
            raise ValueError("invalid workspace_id")
        if not CAPABILITY_ID_RE.fullmatch(capability_id):
            raise ValueError("invalid capability_id")
        if not argv or len(argv) > 64 or any(not isinstance(x, str) or not x or len(x) > 4096 for x in argv):
            raise ValueError("argv must contain 1..64 bounded string arguments")
        cwd_path = Path(cwd)
        if cwd_path.is_absolute() or ".." in cwd_path.parts or len(cwd) > 512:
            raise ValueError("cwd must stay relative to workspace")
        if max_attempts < 1 or max_attempts > 10:
            raise ValueError("max_attempts must be between 1 and 10")

    def _event(self, db: sqlite3.Connection, job_id: str | None, kind: str, actor: str, payload: dict[str, Any], now: int) -> str:
        previous = db.execute("SELECT event_hash FROM fleet_events ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = previous["event_hash"] if previous else GENESIS_HASH
        body = {
            "job_id": job_id,
            "kind": kind,
            "actor": actor,
            "payload": payload,
            "created_at": now,
            "prev_hash": prev_hash,
        }
        event_hash = _sha256_bytes(canonical_json(body))
        db.execute(
            "INSERT INTO fleet_events(job_id,kind,actor,payload_json,created_at,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?)",
            (job_id, kind, actor, json.dumps(payload, sort_keys=True, separators=(",", ":")), now, prev_hash, event_hash),
        )
        return event_hash

    def record_plan(self, plan: dict[str, Any]) -> None:
        plan_id = str(plan.get("plan_id", ""))
        status = str(plan.get("status", ""))
        if not plan_id or status not in {"VERIFIED_PLAN", "BLOCKED"}:
            raise ValueError("plan must have plan_id and terminal planning status")
        now = int(self.clock())
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO plans(plan_id,status,plan_json,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(plan_id) DO UPDATE SET status=excluded.status, plan_json=excluded.plan_json",
                (plan_id, status, json.dumps(plan, sort_keys=True, separators=(",", ":")), now),
            )
            self._event(db, None, "PLAN_RECORDED", "control-plane", {"plan_id": plan_id, "status": status}, now)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def verified_plan_exists(self, plan_id: str) -> bool:
        db = self._connect()
        try:
            row = db.execute("SELECT status FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
            return bool(row and row["status"] == "VERIFIED_PLAN")
        finally:
            db.close()

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
        self._validate_job_input(workspace_id, capability_id, argv, cwd, max_attempts)
        verification_spec = verification_spec or {}
        if not isinstance(verification_spec, dict):
            raise ValueError("verification_spec must be an object")
        now = int(self.clock())
        job_id = job_id or f"JOB-{uuid.uuid4().hex}"
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            plan = db.execute("SELECT status FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
            if not plan or plan["status"] != "VERIFIED_PLAN":
                raise PermissionError("job enqueue requires a durable VERIFIED_PLAN")
            db.execute(
                """
                INSERT INTO jobs(
                    job_id,plan_id,workspace_id,capability_id,argv_json,cwd,
                    verification_spec_json,workspace_before_sha256,state,priority,
                    available_at,created_at,updated_at,max_attempts
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id, plan_id, workspace_id, capability_id,
                    json.dumps(list(argv), separators=(",", ":")), cwd,
                    json.dumps(verification_spec, sort_keys=True, separators=(",", ":")),
                    workspace_before_sha256, "QUEUED", int(priority), now, now, now, max_attempts,
                ),
            )
            self._event(db, job_id, "JOB_ENQUEUED", "control-plane", {
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "capability_id": capability_id,
                "priority": int(priority),
                "max_attempts": max_attempts,
            }, now)
            db.commit()
            return self.get_job(job_id)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _decode_job(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["argv"] = json.loads(out.pop("argv_json"))
        out["verification_spec"] = json.loads(out.pop("verification_spec_json"))
        if out.get("receipt_json"):
            out["receipt"] = json.loads(out["receipt_json"])
        else:
            out["receipt"] = None
        if out.get("verification_json"):
            out["verification"] = json.loads(out["verification_json"])
        else:
            out["verification"] = None
        out.pop("execution_lease_hash", None)
        out.pop("verification_lease_hash", None)
        return out

    def get_job(self, job_id: str) -> dict[str, Any]:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            return self._decode_job(row)
        finally:
            db.close()

    def _reap_expired(self, db: sqlite3.Connection, now: int) -> None:
        rows = db.execute(
            "SELECT job_id,state,attempts,max_attempts,execution_worker_id,verifier_id FROM jobs "
            "WHERE (state='LEASED' AND execution_lease_expires_at < ?) "
            "OR (state='VERIFYING' AND verification_lease_expires_at < ?)",
            (now, now),
        ).fetchall()
        for row in rows:
            if row["state"] == "LEASED":
                next_state = "QUEUED" if row["attempts"] < row["max_attempts"] else "FAILED"
                db.execute(
                    "UPDATE jobs SET state=?,execution_worker_id=NULL,execution_lease_hash=NULL,"
                    "execution_lease_expires_at=NULL,updated_at=?,last_error=? WHERE job_id=?",
                    (next_state, now, "execution lease expired", row["job_id"]),
                )
                self._event(db, row["job_id"], "EXECUTION_LEASE_EXPIRED", "fleet-coordinator", {
                    "previous_owner": row["execution_worker_id"], "next_state": next_state,
                }, now)
            else:
                db.execute(
                    "UPDATE jobs SET state='EXECUTED',verifier_id=NULL,verification_lease_hash=NULL,"
                    "verification_lease_expires_at=NULL,updated_at=?,last_error=? WHERE job_id=?",
                    (now, "verification lease expired", row["job_id"]),
                )
                self._event(db, row["job_id"], "VERIFICATION_LEASE_EXPIRED", "fleet-coordinator", {
                    "previous_verifier": row["verifier_id"], "next_state": "EXECUTED",
                }, now)

    def claim_execution(self, worker_id: str, lease_seconds: int = 30) -> Lease | None:
        self._validate_owner(worker_id)
        if lease_seconds < 5 or lease_seconds > 300:
            raise ValueError("lease_seconds must be between 5 and 300")
        now = int(self.clock())
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._reap_expired(db, now)
            row = db.execute(
                "SELECT * FROM jobs WHERE state='QUEUED' AND available_at<=? AND attempts<max_attempts "
                "ORDER BY priority ASC, created_at ASC, job_id ASC LIMIT 1",
                (now,),
            ).fetchone()
            if not row:
                db.commit()
                return None
            token = secrets.token_urlsafe(32)
            expires = now + lease_seconds
            db.execute(
                "UPDATE jobs SET state='LEASED',execution_worker_id=?,execution_lease_hash=?,"
                "execution_lease_expires_at=?,attempts=attempts+1,updated_at=?,last_error=NULL WHERE job_id=? AND state='QUEUED'",
                (worker_id, _token_hash(token), expires, now, row["job_id"]),
            )
            self._event(db, row["job_id"], "EXECUTION_LEASE_GRANTED", worker_id, {
                "expires_at": expires, "attempt": row["attempts"] + 1,
            }, now)
            db.commit()
            job = self.get_job(row["job_id"])
            return Lease(row["job_id"], worker_id, token, expires, job)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def heartbeat_execution(self, job_id: str, worker_id: str, token: str, lease_seconds: int = 30) -> int:
        self._validate_owner(worker_id)
        now = int(self.clock())
        expires = now + lease_seconds
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["state"] != "LEASED" or row["execution_worker_id"] != worker_id:
                raise PermissionError("execution lease ownership mismatch")
            if row["execution_lease_expires_at"] < now or row["execution_lease_hash"] != _token_hash(token):
                raise PermissionError("execution lease expired or token invalid")
            db.execute("UPDATE jobs SET execution_lease_expires_at=?,updated_at=? WHERE job_id=?", (expires, now, job_id))
            self._event(db, job_id, "EXECUTION_HEARTBEAT", worker_id, {"expires_at": expires}, now)
            db.commit()
            return expires
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def complete_execution(
        self,
        job_id: str,
        worker_id: str,
        token: str,
        receipt: dict[str, Any],
        *,
        receipt_signature_verified: bool,
    ) -> dict[str, Any]:
        self._validate_owner(worker_id)
        if not receipt_signature_verified:
            raise PermissionError("unverified execution receipt cannot enter durable queue")
        if receipt.get("verification_status") != "UNKNOWN":
            raise PermissionError("execution receipt must remain UNKNOWN until independent verification")
        result = receipt.get("result")
        if not isinstance(result, dict) or result.get("status") != "EXECUTED" or result.get("exit_code") != 0:
            raise RuntimeError("only successful execution receipts can advance to verification")
        now = int(self.clock())
        receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        receipt_sha = _sha256_bytes(receipt_json.encode("utf-8"))
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["state"] != "LEASED" or row["execution_worker_id"] != worker_id:
                raise PermissionError("execution lease ownership mismatch")
            if row["execution_lease_expires_at"] < now or row["execution_lease_hash"] != _token_hash(token):
                raise PermissionError("execution lease expired or token invalid")
            db.execute(
                "UPDATE jobs SET state='EXECUTED',receipt_json=?,receipt_sha256=?,"
                "execution_lease_hash=NULL,execution_lease_expires_at=NULL,updated_at=? WHERE job_id=?",
                (receipt_json, receipt_sha, now, job_id),
            )
            self._event(db, job_id, "EXECUTION_RECEIPT_ACCEPTED", worker_id, {
                "receipt_sha256": receipt_sha,
                "verification_status": "UNKNOWN",
                "executor_id": receipt.get("executor_id"),
            }, now)
            db.commit()
            return self.get_job(job_id)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def fail_execution(self, job_id: str, worker_id: str, token: str, error: str, retry_delay_seconds: int = 1) -> dict[str, Any]:
        self._validate_owner(worker_id)
        now = int(self.clock())
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["state"] != "LEASED" or row["execution_worker_id"] != worker_id:
                raise PermissionError("execution lease ownership mismatch")
            if row["execution_lease_hash"] != _token_hash(token):
                raise PermissionError("execution lease token invalid")
            next_state = "QUEUED" if row["attempts"] < row["max_attempts"] else "FAILED"
            available = now + max(0, int(retry_delay_seconds))
            db.execute(
                "UPDATE jobs SET state=?,available_at=?,execution_worker_id=NULL,execution_lease_hash=NULL,"
                "execution_lease_expires_at=NULL,updated_at=?,last_error=? WHERE job_id=?",
                (next_state, available, now, error[:2048], job_id),
            )
            self._event(db, job_id, "EXECUTION_FAILED", worker_id, {
                "next_state": next_state, "attempt": row["attempts"], "error": error[:512],
            }, now)
            db.commit()
            return self.get_job(job_id)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def claim_verification(self, verifier_id: str, lease_seconds: int = 30) -> Lease | None:
        self._validate_owner(verifier_id)
        now = int(self.clock())
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._reap_expired(db, now)
            row = db.execute(
                "SELECT * FROM jobs WHERE state='EXECUTED' AND (execution_worker_id IS NULL OR execution_worker_id<>?) "
                "ORDER BY updated_at ASC, job_id ASC LIMIT 1",
                (verifier_id,),
            ).fetchone()
            if not row:
                db.commit()
                return None
            token = secrets.token_urlsafe(32)
            expires = now + lease_seconds
            db.execute(
                "UPDATE jobs SET state='VERIFYING',verifier_id=?,verification_lease_hash=?,"
                "verification_lease_expires_at=?,updated_at=? WHERE job_id=? AND state='EXECUTED'",
                (verifier_id, _token_hash(token), expires, now, row["job_id"]),
            )
            self._event(db, row["job_id"], "VERIFICATION_LEASE_GRANTED", verifier_id, {"expires_at": expires}, now)
            db.commit()
            return Lease(row["job_id"], verifier_id, token, expires, self.get_job(row["job_id"]))
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def complete_verification(
        self,
        job_id: str,
        verifier_id: str,
        token: str,
        verdict: str,
        proof: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_owner(verifier_id)
        if verdict not in {"VERIFIED", "FAILED", "BLOCKED"}:
            raise ValueError("verdict must be VERIFIED, FAILED or BLOCKED")
        if not isinstance(proof, dict):
            raise ValueError("verification proof must be an object")
        checks = proof.get("checks")
        if verdict == "VERIFIED" and (not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values())):
            raise PermissionError("VERIFIED requires non-empty independently passing checks")
        now = int(self.clock())
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["state"] != "VERIFYING" or row["verifier_id"] != verifier_id:
                raise PermissionError("verification lease ownership mismatch")
            if row["execution_worker_id"] == verifier_id:
                raise PermissionError("executor worker cannot verify its own job")
            if row["verification_lease_expires_at"] < now or row["verification_lease_hash"] != _token_hash(token):
                raise PermissionError("verification lease expired or token invalid")
            verification = {
                "verdict": verdict,
                "verifier_id": verifier_id,
                "proof": proof,
                "receipt_sha256": row["receipt_sha256"],
                "verified_at": now,
            }
            if verdict == "VERIFIED":
                last_error = None
            elif verdict == "BLOCKED":
                last_error = "independent verification blocked"
            else:
                last_error = "independent verification failed"
            db.execute(
                "UPDATE jobs SET state=?,verification_json=?,verification_lease_hash=NULL,"
                "verification_lease_expires_at=NULL,updated_at=?,last_error=? WHERE job_id=?",
                (
                    verdict,
                    json.dumps(verification, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                    now,
                    last_error,
                    job_id,
                ),
            )
            self._event(db, job_id, "INDEPENDENT_VERIFICATION", verifier_id, verification, now)
            db.commit()
            return self.get_job(job_id)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def stats(self) -> dict[str, Any]:
        db = self._connect()
        try:
            rows = db.execute("SELECT state,COUNT(*) AS n FROM jobs GROUP BY state").fetchall()
            counts = {state: 0 for state in sorted(JOB_STATES)}
            counts.update({row["state"]: row["n"] for row in rows})
            event_count = db.execute("SELECT COUNT(*) AS n FROM fleet_events").fetchone()["n"]
            head = db.execute("SELECT event_hash FROM fleet_events ORDER BY seq DESC LIMIT 1").fetchone()
            return {
                "backend": "sqlite-durable-reference",
                "counts": counts,
                "event_count": event_count,
                "event_head": head["event_hash"] if head else None,
                "receipt_is_verification": False,
            }
        finally:
            db.close()

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            rows = db.execute("SELECT * FROM fleet_events ORDER BY seq DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
            out = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json"))
                out.append(item)
            return out
        finally:
            db.close()

    def verify_event_chain(self) -> tuple[bool, str]:
        db = self._connect()
        try:
            rows = db.execute("SELECT * FROM fleet_events ORDER BY seq ASC").fetchall()
        finally:
            db.close()
        previous = GENESIS_HASH
        for row in rows:
            if row["prev_hash"] != previous:
                return False, f"event {row['seq']} prev_hash mismatch"
            payload = json.loads(row["payload_json"])
            body = {
                "job_id": row["job_id"],
                "kind": row["kind"],
                "actor": row["actor"],
                "payload": payload,
                "created_at": row["created_at"],
                "prev_hash": row["prev_hash"],
            }
            expected = _sha256_bytes(canonical_json(body))
            if row["event_hash"] != expected:
                return False, f"event {row['seq']} hash mismatch"
            previous = row["event_hash"]
        return True, f"{len(rows)} events verified"
