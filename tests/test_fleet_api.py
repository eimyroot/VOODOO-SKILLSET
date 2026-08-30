import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from voodoo_skillset.api import App, handler_factory
from voodoo_skillset.executor_bridge import sign_payload

ROOT = Path(__file__).resolve().parents[1]
SECRET = "executor-shared-secret-0123456789abcdef"
CONTROL = "control-token-0123456789"
WORKER = "worker-token-0123456789"
VERIFIER = "verifier-token-0123456789"


class FleetApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {
            "VOODOO_FLEET_DB": str(Path(self.tmp.name) / "fleet.sqlite3"),
            "VOODOO_CONTROL_API_TOKEN": CONTROL,
            "VOODOO_FLEET_WORKER_TOKEN": WORKER,
            "VOODOO_FLEET_VERIFIER_TOKEN": VERIFIER,
            "VOODOO_EXECUTOR_SHARED_SECRET": SECRET,
        }
        self.env = patch.dict(os.environ, env, clear=False)
        self.env.start()
        self.app = App(ROOT, state_dir=Path(self.tmp.name) / "state")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.app))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.env.stop()
        self.tmp.cleanup()

    def post(self, path, payload, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(req) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def get(self, path):
        with urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
            return response.status, json.loads(response.read())

    def plan_and_job(self):
        status, plan = self.post(
            "/api/plan",
            {"goal": "audit repository security implement fixes test independently verify", "mode": "ALL"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(plan["status"], "VERIFIED_PLAN")
        self.assertEqual(plan["durable_record"], "RECORDED")
        status, job = self.post(
            "/api/fleet/jobs",
            {
                "plan_id": plan["plan_id"],
                "workspace_id": "demo",
                "capability_id": "test-engineer",
                "argv": ["python3", "-c", "print('fleet-ok')"],
                "verification_spec": {"expected_exit_code": 0},
            },
            CONTROL,
        )
        self.assertEqual(status, 200)
        self.assertEqual(job["state"], "QUEUED")
        return plan, job

    def test_tokens_are_separate_and_full_flow_requires_verifier(self):
        plan, job = self.plan_and_job()
        status, body = self.post("/api/fleet/claim", {"worker_id": "worker-a"}, CONTROL)
        self.assertEqual(status, 403)
        self.assertIn("authorization failed", body["error"])

        status, claim = self.post("/api/fleet/claim", {"worker_id": "worker-a"}, WORKER)
        self.assertEqual(status, 200)
        lease = claim["lease"]
        receipt = {
            "protocol": "executor-v1",
            "executor_id": "worker-a",
            "operation_id": "OP-fleet-api",
            "plan_id": plan["plan_id"],
            "request_sha256": "a" * 64,
            "issued_at": 1,
            "verification_status": "UNKNOWN",
            "result": {
                "status": "EXECUTED",
                "exit_code": 0,
                "verification_status": "UNKNOWN",
                "runner": "docker-container-v1",
                "persistent_effect": "NONE",
                "stdout": "fleet-ok\n",
            },
        }
        status, completed = self.post(
            "/api/fleet/complete",
            {
                "job_id": job["job_id"],
                "worker_id": "worker-a",
                "lease_token": lease["token"],
                "receipt": receipt,
                "receipt_signature": sign_payload(receipt, SECRET),
            },
            WORKER,
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["state"], "EXECUTED")

        status, same_worker = self.post("/api/fleet/verify/claim", {"verifier_id": "worker-a"}, VERIFIER)
        self.assertEqual(status, 200)
        self.assertEqual(same_worker["status"], "IDLE")

        status, verify_claim = self.post("/api/fleet/verify/claim", {"verifier_id": "verifier-b"}, VERIFIER)
        self.assertEqual(status, 200)
        vlease = verify_claim["lease"]
        status, final = self.post(
            "/api/fleet/verify/complete",
            {
                "job_id": job["job_id"],
                "verifier_id": "verifier-b",
                "lease_token": vlease["token"],
                "verdict": "VERIFIED",
                "proof": {"checks": {"exit_code": True}},
            },
            VERIFIER,
        )
        self.assertEqual(status, 200)
        self.assertEqual(final["state"], "VERIFIED")

        status, fleet = self.get("/api/fleet")
        self.assertEqual(status, 200)
        self.assertEqual(fleet["event_chain"], "VERIFIED")
        self.assertEqual(fleet["stats"]["counts"]["VERIFIED"], 1)
        self.assertFalse(fleet["database_secret_exposed_to_workers"])

    def test_bad_receipt_signature_is_fail_closed(self):
        plan, job = self.plan_and_job()
        _, claim = self.post("/api/fleet/claim", {"worker_id": "worker-a"}, WORKER)
        receipt = {
            "protocol": "executor-v1",
            "executor_id": "worker-a",
            "operation_id": "OP-bad-signature",
            "plan_id": plan["plan_id"],
            "request_sha256": "b" * 64,
            "issued_at": 1,
            "verification_status": "UNKNOWN",
            "result": {"status": "EXECUTED", "exit_code": 0},
        }
        status, body = self.post(
            "/api/fleet/complete",
            {
                "job_id": job["job_id"],
                "worker_id": "worker-a",
                "lease_token": claim["lease"]["token"],
                "receipt": receipt,
                "receipt_signature": "v1=" + "0" * 64,
            },
            WORKER,
        )
        self.assertEqual(status, 403)
        self.assertIn("unverified execution receipt", body["error"])


if __name__ == "__main__":
    unittest.main()
