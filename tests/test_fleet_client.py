import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from voodoo_skillset.fleet_client import FleetCoordinatorClient, FleetCoordinatorError


class FakeResponse:
    def __init__(self, value):
        self.body = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit=None):
        return self.body


class FleetCoordinatorClientTests(unittest.TestCase):
    def test_remote_plaintext_http_is_blocked(self):
        with self.assertRaises(ValueError):
            FleetCoordinatorClient("http://fleet.example.com", "worker-token-0123456789")

    def test_worker_bearer_and_signed_receipt_are_forwarded(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["authorization"] = req.headers.get("Authorization")
            captured["body"] = json.loads(req.data)
            return FakeResponse({"state": "EXECUTED", "receipt_sha256": "a" * 64})

        client = FleetCoordinatorClient("http://127.0.0.1:8787", "worker-token-0123456789")
        receipt = {"verification_status": "UNKNOWN", "result": {"status": "EXECUTED", "exit_code": 0}}
        with patch("voodoo_skillset.fleet_client.urlopen", fake_urlopen):
            out = client.complete_execution_signed("JOB-1", "worker-a", "lease-token", receipt, "v1=" + "b" * 64)
        self.assertTrue(captured["url"].endswith("/api/fleet/complete"))
        self.assertEqual(captured["authorization"], "Bearer worker-token-0123456789")
        self.assertEqual(captured["body"]["receipt_signature"], "v1=" + "b" * 64)
        self.assertEqual(out["state"], "EXECUTED")

    def test_claim_parses_one_time_lease_token_but_does_not_embed_it_in_job(self):
        payload = {
            "status": "LEASED",
            "lease": {
                "job_id": "JOB-1",
                "owner_id": "worker-a",
                "token": "one-time-token",
                "expires_at": 123,
                "job": {"job_id": "JOB-1", "state": "LEASED"},
            },
        }
        client = FleetCoordinatorClient("http://127.0.0.1:8787", "worker-token-0123456789")
        with patch("voodoo_skillset.fleet_client.urlopen", lambda req, timeout: FakeResponse(payload)):
            lease = client.claim_execution("worker-a")
        self.assertEqual(lease.token, "one-time-token")
        self.assertNotIn("token", lease.job)

    def test_idle_claim_returns_none(self):
        client = FleetCoordinatorClient("http://127.0.0.1:8787", "worker-token-0123456789")
        with patch("voodoo_skillset.fleet_client.urlopen", lambda req, timeout: FakeResponse({"status": "IDLE", "lease": None})):
            self.assertIsNone(client.claim_execution("worker-a"))


if __name__ == "__main__":
    unittest.main()
