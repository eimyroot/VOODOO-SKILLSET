import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest import mock

from voodoo_skillset.api import App, handler_factory

ROOT = Path(__file__).resolve().parents[1]


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        fleet_db = str(Path(cls.tmp.name) / "fleet.sqlite3")
        with mock.patch.dict(
            os.environ,
            {
                "VOODOO_FLEET_DB": fleet_db,
                "VOODOO_FLEET_SUPABASE_URL": "",
                "VOODOO_FLEET_SUPABASE_SERVICE_ROLE_KEY": "",
            },
            clear=False,
        ):
            cls.app = App(ROOT, state_dir=Path(cls.tmp.name) / "state")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(cls.app))
        cls.port = cls.server.server_address[1]
        cls.t = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
            return response.status, response.read().decode(), response.headers.get_content_type()

    def test_health(self):
        status, body, _ = self.get("/api/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["trust_model"], "fail-closed")
        self.assertEqual(data["version"], "0.6.0")
        self.assertEqual(data["fleet"], "CONFIGURED")
        self.assertEqual(data["fleet_backend"], "sqlite-durable-reference")

    def test_index(self):
        status, body, ctype = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("VOODOO", body)
        self.assertIn("Executor Fleet", body)
        self.assertEqual(ctype, "text/html")

    def test_plan(self):
        data = json.dumps({"goal": "audit github repo security implement fixes test verify", "mode": "ALL"}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/plan",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            plan = json.loads(response.read())
        self.assertEqual(plan["status"], "VERIFIED_PLAN")
        self.assertEqual(plan["durable_record"], "RECORDED")
        self.assertIn("independent-verifier", [x["capability_id"] for x in plan["selections"]])


if __name__ == "__main__":
    unittest.main()
