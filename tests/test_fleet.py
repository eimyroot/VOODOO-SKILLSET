import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from voodoo_skillset.fleet import DurableFleetStore, workspace_manifest_digest


class Clock:
    def __init__(self, value=1_800_000_000):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def verified_plan(plan_id="PLAN-1"):
    return {"plan_id": plan_id, "status": "VERIFIED_PLAN", "goal": "test", "mode": "ALL"}


def receipt(plan_id="PLAN-1", operation_id="OP-1"):
    return {
        "protocol": "executor-v1",
        "executor_id": "worker-node",
        "operation_id": operation_id,
        "plan_id": plan_id,
        "request_sha256": "a" * 64,
        "issued_at": 1_800_000_001,
        "verification_status": "UNKNOWN",
        "result": {
            "status": "EXECUTED",
            "exit_code": 0,
            "verification_status": "UNKNOWN",
            "runner": "docker-container-v1",
            "persistent_effect": "NONE",
            "stdout": "ok\n",
        },
    }


class FleetTests(unittest.TestCase):
    def make_store(self, root, clock=None):
        return DurableFleetStore(Path(root) / "fleet.sqlite3", clock or Clock())

    def prepare_job(self, store, **kwargs):
        store.record_plan(verified_plan())
        return store.enqueue(
            plan_id="PLAN-1",
            workspace_id="demo",
            capability_id="test-engineer",
            argv=["python3", "-c", "print('ok')"],
            verification_spec={"expected_exit_code": 0},
            **kwargs,
        )

    def test_enqueue_requires_durable_verified_plan(self):
        with tempfile.TemporaryDirectory() as d:
            store = self.make_store(d)
            with self.assertRaises(PermissionError):
                store.enqueue(
                    plan_id="MISSING",
                    workspace_id="demo",
                    capability_id="test-engineer",
                    argv=["python3", "-c", "print(1)"],
                )

    def test_concurrent_claim_is_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            store = self.make_store(d)
            job = self.prepare_job(store)
            barrier = threading.Barrier(3)
            leases = []
            errors = []

            def claim(worker):
                try:
                    barrier.wait()
                    leases.append(store.claim_execution(worker))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=claim, args=(f"worker-{i}",)) for i in range(2)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()
            self.assertFalse(errors)
            winners = [lease for lease in leases if lease is not None]
            self.assertEqual(len(winners), 1)
            self.assertEqual(winners[0].job_id, job["job_id"])
            stored = store.get_job(job["job_id"])
            self.assertEqual(stored["state"], "LEASED")
            self.assertNotIn("execution_lease_hash", stored)

    def test_wrong_token_cannot_heartbeat_or_complete(self):
        with tempfile.TemporaryDirectory() as d:
            store = self.make_store(d)
            job = self.prepare_job(store)
            lease = store.claim_execution("worker-a")
            self.assertIsNotNone(lease)
            with self.assertRaises(PermissionError):
                store.heartbeat_execution(job["job_id"], "worker-a", "wrong")
            with self.assertRaises(PermissionError):
                store.complete_execution(job["job_id"], "worker-a", "wrong", receipt(), receipt_signature_verified=True)

    def test_expired_execution_lease_is_reaped_and_reassigned(self):
        with tempfile.TemporaryDirectory() as d:
            clock = Clock()
            store = self.make_store(d, clock)
            job = self.prepare_job(store, max_attempts=2)
            first = store.claim_execution("worker-a", lease_seconds=5)
            self.assertIsNotNone(first)
            clock.advance(6)
            second = store.claim_execution("worker-b", lease_seconds=5)
            self.assertIsNotNone(second)
            self.assertEqual(second.job_id, job["job_id"])
            self.assertEqual(store.get_job(job["job_id"])["attempts"], 2)

    def test_execution_receipt_cannot_claim_verified(self):
        with tempfile.TemporaryDirectory() as d:
            store = self.make_store(d)
            job = self.prepare_job(store)
            lease = store.claim_execution("worker-a")
            bad = receipt()
            bad["verification_status"] = "VERIFIED"
            with self.assertRaises(PermissionError):
                store.complete_execution(job["job_id"], "worker-a", lease.token, bad, receipt_signature_verified=True)

    def test_unverified_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store = self.make_store(d)
            job = self.prepare_job(store)
            lease = store.claim_execution("worker-a")
            with self.assertRaises(PermissionError):
                store.complete_execution(job["job_id"], "worker-a", lease.token, receipt(), receipt_signature_verified=False)

    def test_independent_verifier_must_be_different_worker(self):
        with tempfile.TemporaryDirectory() as d:
            store = self.make_store(d)
            job = self.prepare_job(store)
            lease = store.claim_execution("worker-a")
            store.complete_execution(job["job_id"], "worker-a", lease.token, receipt(), receipt_signature_verified=True)
            self.assertIsNone(store.claim_verification("worker-a"))
            verify_lease = store.claim_verification("verifier-b")
            self.assertIsNotNone(verify_lease)
            with self.assertRaises(PermissionError):
                store.complete_verification(job["job_id"], "verifier-b", verify_lease.token, "VERIFIED", {"checks": {}})
            final = store.complete_verification(
                job["job_id"],
                "verifier-b",
                verify_lease.token,
                "VERIFIED",
                {"checks": {"exit_code": True, "workspace_unchanged": True}},
            )
            self.assertEqual(final["state"], "VERIFIED")
            self.assertEqual(final["verification"]["verifier_id"], "verifier-b")

    def test_failed_execution_retries_then_stops(self):
        with tempfile.TemporaryDirectory() as d:
            store = self.make_store(d)
            job = self.prepare_job(store, max_attempts=2)
            first = store.claim_execution("worker-a")
            out = store.fail_execution(job["job_id"], "worker-a", first.token, "boom", retry_delay_seconds=0)
            self.assertEqual(out["state"], "QUEUED")
            second = store.claim_execution("worker-b")
            out = store.fail_execution(job["job_id"], "worker-b", second.token, "boom again", retry_delay_seconds=0)
            self.assertEqual(out["state"], "FAILED")
            self.assertIsNone(store.claim_execution("worker-c"))

    def test_event_chain_detects_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            store = self.make_store(d)
            self.prepare_job(store)
            ok, _ = store.verify_event_chain()
            self.assertTrue(ok)
            db = sqlite3.connect(store.path)
            try:
                db.execute("UPDATE fleet_events SET payload_json='{}' WHERE seq=(SELECT MIN(seq) FROM fleet_events)")
                db.commit()
            finally:
                db.close()
            ok, reason = store.verify_event_chain()
            self.assertFalse(ok)
            self.assertIn("hash mismatch", reason)

    def test_workspace_manifest_digest_changes_with_content(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.txt").write_text("one", encoding="utf-8")
            first = workspace_manifest_digest(root)
            (root / "a.txt").write_text("two", encoding="utf-8")
            self.assertNotEqual(first, workspace_manifest_digest(root))


if __name__ == "__main__":
    unittest.main()
