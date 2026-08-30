import json
import unittest
from unittest.mock import patch

from voodoo_skillset.fleet_supabase import SupabaseFleetStore


class FakeResponse:
    def __init__(self, value):
        self.body = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit=None):
        return self.body


class SupabaseFleetTests(unittest.TestCase):
    def test_requires_https(self):
        with self.assertRaises(ValueError):
            SupabaseFleetStore("http://example.supabase.co", "x" * 32)

    def test_record_plan_uses_server_side_rpc_and_bearer(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["authorization"] = req.headers.get("Authorization")
            captured["apikey"] = req.headers.get("Apikey")
            captured["body"] = json.loads(req.data)
            return FakeResponse({"plan_id": "PLAN-1", "status": "VERIFIED_PLAN"})

        store = SupabaseFleetStore("https://example.supabase.co", "service-role-secret-1234567890")
        with patch("voodoo_skillset.fleet_supabase.urlopen", fake_urlopen):
            store.record_plan({"plan_id": "PLAN-1", "status": "VERIFIED_PLAN"})
        self.assertTrue(captured["url"].endswith("/rest/v1/rpc/voodoo_record_plan"))
        self.assertEqual(captured["authorization"], "Bearer service-role-secret-1234567890")
        self.assertEqual(captured["apikey"], "service-role-secret-1234567890")
        self.assertEqual(captured["body"]["p_plan"]["plan_id"], "PLAN-1")

    def test_claim_returns_token_separately_from_job(self):
        value = {
            "job_id": "JOB-1",
            "plan_id": "PLAN-1",
            "workspace_id": "demo",
            "capability_id": "test-engineer",
            "argv": ["python3", "-c", "print(1)"],
            "cwd": ".",
            "verification_spec": {"expected_exit_code": 0},
            "state": "LEASED",
            "lease_token": "raw-one-time-token",
            "lease_expires_at": "2026-08-30T12:00:00+00:00",
        }
        store = SupabaseFleetStore("https://example.supabase.co", "service-role-secret-1234567890")
        with patch("voodoo_skillset.fleet_supabase.urlopen", lambda req, timeout: FakeResponse(value)):
            lease = store.claim_execution("worker-a")
        self.assertEqual(lease.token, "raw-one-time-token")
        self.assertNotIn("lease_token", lease.job)
        self.assertEqual(lease.job["job_id"], "JOB-1")

    def test_enqueue_requires_verification_spec_before_network(self):
        store = SupabaseFleetStore("https://example.supabase.co", "service-role-secret-1234567890")
        with self.assertRaises(ValueError):
            store.enqueue(
                plan_id="PLAN-1",
                workspace_id="demo",
                capability_id="test-engineer",
                argv=["python3", "-c", "print(1)"],
                verification_spec={},
            )


if __name__ == "__main__":
    unittest.main()
