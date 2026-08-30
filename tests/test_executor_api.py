import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from voodoo_skillset.api import App, handler_factory
from voodoo_skillset.executor_bridge import ExecutorProtocolError, build_executor_server

ROOT = Path(__file__).resolve().parents[1]
SECRET = "s" * 48
CONTROL_TOKEN = "control-token-for-tests"


class FakeExecutor:
    def available(self):
        return True, "test adapter available"

    def execute(self, capability_id, payload, envelope):
        return {
            "status": "EXECUTED",
            "verification_status": "UNKNOWN",
            "capability_id": capability_id,
            "operation_id": envelope.operation_id,
            "network_default": envelope.network_policy.default,
            "persistent_effect": "NONE",
            "stdout": "ok\n",
            "stderr": "",
        }


class ExecutorApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.tmp.name) / "workspaces"
        (self.workspace_root / "demo").mkdir(parents=True)
        self.executor = build_executor_server(
            self.workspace_root,
            SECRET,
            host="127.0.0.1",
            port=0,
            adapter=FakeExecutor(),
        )
        self.executor_thread = threading.Thread(target=self.executor.serve_forever, daemon=True)
        self.executor_thread.start()
        executor_url = f"http://127.0.0.1:{self.executor.server_address[1]}"
        self.env = patch.dict(os.environ, {
            "VOODOO_EXECUTOR_URL": executor_url,
            "VOODOO_EXECUTOR_SHARED_SECRET": SECRET,
            "VOODOO_CONTROL_API_TOKEN": CONTROL_TOKEN,
        }, clear=False)
        self.env.start()
        self.app = App(ROOT, state_dir=Path(self.tmp.name) / "state")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.executor.shutdown()
        self.executor.server_close()
        self.env.stop()
        self.tmp.cleanup()

    def request(self, path, payload=None, token=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method="POST" if payload is not None else "GET")
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def verified_plan(self):
        status, plan = self.request("/api/plan", {
            "goal": "audit github repo security implement fixes test verify",
            "mode": "ALL",
        })
        self.assertEqual(status, 200)
        self.assertEqual(plan["status"], "VERIFIED_PLAN")
        return plan

    def execution_payload(self, plan_id):
        return {
            "plan_id": plan_id,
            "workspace_id": "demo",
            "capability_id": "governed-terminal",
            "argv": ["python3", "-c", "print('ok')"],
        }

    def test_executor_status_is_available(self):
        status, body = self.request("/api/executor")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "AVAILABLE")
        self.assertEqual(body["remote"]["protocol"], "executor-v1")

    def test_control_plane_to_executor_round_trip(self):
        plan = self.verified_plan()
        payload = self.execution_payload(plan["plan_id"])

        status, denied = self.request("/api/executor/execute", payload)
        self.assertEqual(status, 403)
        self.assertIn("authorization", denied["error"])

        status, out = self.request("/api/executor/execute", payload, CONTROL_TOKEN)
        self.assertEqual(status, 200)
        self.assertTrue(out["receipt_signature_verified"])
        self.assertEqual(out["independent_verification"], "PENDING")
        self.assertEqual(out["receipt"]["verification_status"], "UNKNOWN")
        self.assertEqual(out["receipt"]["result"]["network_default"], "DENY")

    def test_executor_protocol_failure_is_bad_gateway(self):
        plan = self.verified_plan()
        payload = self.execution_payload(plan["plan_id"])
        with patch(
            "voodoo_skillset.api.RemoteExecutorClient.execute",
            side_effect=ExecutorProtocolError("downstream executor protocol failure"),
        ):
            status, body = self.request("/api/executor/execute", payload, CONTROL_TOKEN)
        self.assertEqual(status, 502)
        self.assertIn("protocol failure", body["error"])

    def test_unknown_plan_is_fail_closed(self):
        status, body = self.request("/api/executor/execute", {
            "plan_id": "PLAN-does-not-exist",
            "workspace_id": "demo",
            "capability_id": "governed-terminal",
            "argv": ["python3", "-c", "print(1)"],
        }, CONTROL_TOKEN)
        self.assertEqual(status, 403)
        self.assertIn("VERIFIED_PLAN", body["error"])


if __name__ == "__main__":
    unittest.main()
