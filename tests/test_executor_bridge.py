import tempfile
import threading
import time
import unittest
from pathlib import Path

from voodoo_skillset.executor_bridge import (
    ExecutionRequest,
    ExecutorAuthError,
    ExecutorPolicyError,
    ExecutorProtocolError,
    ExecutorService,
    RemoteExecutorClient,
    build_executor_server,
    sign_payload,
    verify_signature,
)

SECRET = "x" * 48


class FakeExecutor:
    def available(self):
        return True, "test adapter available"

    def execute(self, capability_id, payload, envelope):
        return {
            "status": "EXECUTED",
            "verification_status": "UNKNOWN",
            "capability_id": capability_id,
            "operation_id": envelope.operation_id,
            "argv": payload["argv"],
            "cwd": payload["cwd"],
            "network_default": envelope.network_policy.default,
            "persistent_effect": "NONE",
        }


class BridgeUnitTests(unittest.TestCase):
    def test_signature_rejects_tamper(self):
        value = {"a": 1, "b": "x"}
        sig = sign_payload(value, SECRET)
        self.assertTrue(verify_signature(value, sig, SECRET))
        self.assertFalse(verify_signature({"a": 2, "b": "x"}, sig, SECRET))

    def test_request_rejects_traversal(self):
        now = int(time.time())
        with self.assertRaises(ExecutorPolicyError):
            ExecutionRequest.create(
                plan_id="PLAN-1",
                capability_id="governed-terminal",
                workspace_id="../escape",
                argv=["python3", "-c", "print(1)"],
                now=now,
            )

    def test_remote_http_requires_localhost(self):
        with self.assertRaises(ValueError):
            RemoteExecutorClient("http://executor.example.com", SECRET)


class BridgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "demo").mkdir()
        self.server = build_executor_server(root, SECRET, host="127.0.0.1", port=0, adapter=FakeExecutor())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = RemoteExecutorClient(f"http://127.0.0.1:{self.server.server_address[1]}", SECRET)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self):
        return ExecutionRequest.create(
            plan_id="PLAN-1",
            capability_id="governed-terminal",
            workspace_id="demo",
            argv=["python3", "-c", "print(1)"],
        )

    def test_health(self):
        health = self.client.health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["execution"], "AVAILABLE")
        self.assertEqual(health["operation_classes"], ["COMPUTE"])
        self.assertEqual(health["replay_protection"], "SQLITE_PERSISTENT")

    def test_signed_execute_returns_unknown_receipt(self):
        out = self.client.execute(self.request())
        self.assertTrue(out["receipt_signature_verified"])
        self.assertEqual(out["independent_verification"], "PENDING")
        self.assertEqual(out["receipt"]["verification_status"], "UNKNOWN")
        self.assertEqual(out["receipt"]["result"]["network_default"], "DENY")

    def test_replay_is_rejected(self):
        req = self.request()
        self.client.execute(req)
        with self.assertRaises(ExecutorProtocolError) as ctx:
            self.client.execute(req)
        self.assertIn("replay", str(ctx.exception).lower())

    def test_replay_persists_across_service_restart(self):
        req = self.request()
        value = req.to_dict()
        signature = sign_payload(value, SECRET)
        root = Path(self.tmp.name)
        service1 = ExecutorService(root, SECRET, adapter=FakeExecutor())
        service1.execute_signed(value, signature)
        service2 = ExecutorService(root, SECRET, adapter=FakeExecutor())
        with self.assertRaises(ExecutorAuthError):
            service2.execute_signed(value, signature)

    def test_wrong_secret_is_rejected(self):
        client = RemoteExecutorClient(self.client.base_url, "y" * 48)
        with self.assertRaises(ExecutorProtocolError) as ctx:
            client.execute(self.request())
        self.assertIn("401", str(ctx.exception))

    def test_missing_workspace_is_blocked(self):
        req = ExecutionRequest.create(
            plan_id="PLAN-1",
            capability_id="governed-terminal",
            workspace_id="missing",
            argv=["python3", "-c", "print(1)"],
        )
        with self.assertRaises(ExecutorProtocolError) as ctx:
            self.client.execute(req)
        self.assertIn("403", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
