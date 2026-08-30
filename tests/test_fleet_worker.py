import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from voodoo_skillset.execution import ExecutionEnvelope
from voodoo_skillset.fleet import DurableFleetStore, Lease, workspace_manifest_digest
from voodoo_skillset.fleet_worker import ExecutionLeaseHeartbeat, FleetWorker, IndependentFleetVerifier

SECRET = "fleet-worker-secret-0123456789abcdef"


class FakeAdapter:
    backend_name = "fake-isolated-v1"

    def execute(self, capability_id, payload, envelope: ExecutionEnvelope):
        return {
            "status": "EXECUTED",
            "verification_status": "UNKNOWN",
            "capability_id": capability_id,
            "operation_id": envelope.operation_id,
            "runner": self.backend_name,
            "exit_code": 0,
            "stdout": "expected-output\n",
            "stderr": "",
            "persistent_effect": "NONE",
            "isolation": {
                "network_default": "DENY",
                "root_filesystem": "READ_ONLY",
                "capabilities": "ALL_DROPPED",
            },
        }


class FailingAdapter:
    def execute(self, capability_id, payload, envelope):
        raise RuntimeError("synthetic worker failure")


class HeartbeatStore:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def heartbeat_execution(self, job_id, worker_id, token, lease_seconds):
        self.calls += 1
        if self.fail:
            raise RuntimeError("lost coordinator lease")
        return int(time.time()) + lease_seconds


class FleetWorkerTests(unittest.TestCase):
    def setup_job(self, root: Path, *, max_attempts=3):
        workspace_root = root / "workspaces"
        workspace = workspace_root / "demo"
        workspace.mkdir(parents=True)
        (workspace / "marker.txt").write_text("source", encoding="utf-8")
        store = DurableFleetStore(root / "fleet.sqlite3")
        store.record_plan({"plan_id": "PLAN-1", "status": "VERIFIED_PLAN", "goal": "x", "mode": "ALL"})
        job = store.enqueue(
            plan_id="PLAN-1",
            workspace_id="demo",
            capability_id="test-engineer",
            argv=["python3", "-c", "print('expected-output')"],
            verification_spec={
                "expected_exit_code": 0,
                "runner": "fake-isolated-v1",
                "persistent_effect": "NONE",
                "network_default": "DENY",
                "root_filesystem": "READ_ONLY",
                "capabilities": "ALL_DROPPED",
                "stdout_contains": ["expected-output"],
                "require_workspace_unchanged": True,
            },
            workspace_before_sha256=workspace_manifest_digest(workspace),
            max_attempts=max_attempts,
        )
        return store, workspace_root, job

    def test_execution_heartbeat_renews_lease_until_stopped(self):
        store = HeartbeatStore()
        lease = Lease("JOB-1", "worker-a", "token", int(time.time()) + 15, {})
        heartbeat = ExecutionLeaseHeartbeat(store, lease, "worker-a", 15)
        heartbeat.interval = 0.01
        heartbeat.start()
        time.sleep(0.05)
        heartbeat.stop()
        self.assertGreaterEqual(store.calls, 2)
        self.assertIsNone(heartbeat.error)

    def test_execution_heartbeat_records_ownership_loss_fail_closed(self):
        store = HeartbeatStore(fail=True)
        lease = Lease("JOB-1", "worker-a", "token", int(time.time()) + 15, {})
        heartbeat = ExecutionLeaseHeartbeat(store, lease, "worker-a", 15)
        heartbeat.interval = 0.01
        heartbeat.start()
        time.sleep(0.03)
        heartbeat.stop()
        self.assertIsInstance(heartbeat.error, RuntimeError)
        self.assertEqual(store.calls, 1)

    def test_worker_then_independent_verifier(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store, workspace_root, job = self.setup_job(root)
            worker = FleetWorker(store, workspace_root, SECRET, "worker-a", adapter=FakeAdapter())
            out = worker.run_once()
            self.assertEqual(out["status"], "EXECUTED")
            self.assertEqual(store.get_job(job["job_id"])["state"], "EXECUTED")

            same_identity = IndependentFleetVerifier(store, workspace_root, "worker-a")
            self.assertEqual(same_identity.run_once()["status"], "IDLE")

            verifier = IndependentFleetVerifier(store, workspace_root, "verifier-b")
            verified = verifier.run_once()
            self.assertEqual(verified["status"], "VERIFIED")
            self.assertTrue(all(verified["checks"].values()))
            self.assertEqual(store.get_job(job["job_id"])["state"], "VERIFIED")
            ok, reason = store.verify_event_chain()
            self.assertTrue(ok, reason)

    def test_verifier_missing_outcome_evidence_persists_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store, workspace_root, job = self.setup_job(root)
            worker = FleetWorker(store, workspace_root, SECRET, "worker-a", adapter=FakeAdapter())
            self.assertEqual(worker.run_once()["status"], "EXECUTED")

            db = sqlite3.connect(store.path)
            try:
                db.execute("UPDATE jobs SET verification_spec_json='{}' WHERE job_id=?", (job["job_id"],))
                db.commit()
            finally:
                db.close()

            verifier = IndependentFleetVerifier(store, workspace_root, "verifier-b")
            blocked = verifier.run_once()
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertEqual(blocked["queue_state"], "BLOCKED")
            durable = store.get_job(job["job_id"])
            self.assertEqual(durable["state"], "BLOCKED")
            self.assertEqual(durable["verification"]["verdict"], "BLOCKED")
            ok, reason = store.verify_event_chain()
            self.assertTrue(ok, reason)

    def test_worker_failure_consumes_retry_budget(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store, workspace_root, job = self.setup_job(root, max_attempts=1)
            worker = FleetWorker(store, workspace_root, SECRET, "worker-a", adapter=FailingAdapter())
            out = worker.run_once()
            self.assertEqual(out["status"], "FAILED")
            self.assertEqual(store.get_job(job["job_id"])["state"], "FAILED")


if __name__ == "__main__":
    unittest.main()
