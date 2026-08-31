import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class R4ProductionContractTests(unittest.TestCase):
    def test_vercel_wrapper_exposes_fleet_and_provenance(self):
        text = (ROOT / "api/index.py").read_text(encoding="utf-8")
        for route in [
            '"fleet"', '"fleet/events"', '"fleet/jobs"', '"fleet/claim"',
            '"fleet/heartbeat"', '"fleet/complete"', '"fleet/fail"',
            '"fleet/verify/claim"', '"fleet/verify/complete"',
        ]:
            self.assertIn(route, text)
        self.assertIn("VOODOO_CANONICAL_SHA", text)
        self.assertIn("VERCEL_GIT_COMMIT_SHA", text)
        self.assertIn("X-Canonical-SHA", text)

    def test_main_ruleset_is_fail_closed(self):
        ruleset = json.loads((ROOT / "infra/r4/github/main-ruleset.json").read_text(encoding="utf-8"))
        self.assertEqual(ruleset["enforcement"], "active")
        self.assertEqual(ruleset["conditions"]["ref_name"]["include"], ["refs/heads/main"])
        types = {rule["type"] for rule in ruleset["rules"]}
        self.assertTrue({"deletion", "non_fast_forward", "required_linear_history", "required_signatures", "pull_request", "required_status_checks"} <= types)
        pr = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")
        self.assertEqual(pr["parameters"]["allowed_merge_methods"], ["squash"])
        self.assertTrue(pr["parameters"]["required_review_thread_resolution"])
        checks = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
        contexts = {item["context"] for item in checks["parameters"]["required_status_checks"]}
        self.assertEqual(contexts, {"test (3.12)", "test (3.13)"})
        self.assertTrue(checks["parameters"]["strict_required_status_checks_policy"])

    def test_secret_boundaries_are_separate(self):
        worker = (ROOT / "infra/r4/executor/worker.env.example").read_text(encoding="utf-8")
        verifier = (ROOT / "infra/r4/executor/verifier.env.example").read_text(encoding="utf-8")
        self.assertIn("VOODOO_FLEET_WORKER_TOKEN=", worker)
        self.assertIn("VOODOO_EXECUTOR_SHARED_SECRET=", worker)
        self.assertNotIn("VOODOO_FLEET_VERIFIER_TOKEN=REPLACE", worker)
        self.assertNotIn("VOODOO_FLEET_SUPABASE_SERVICE_ROLE_KEY=REPLACE", worker)
        self.assertIn("VOODOO_FLEET_VERIFIER_TOKEN=", verifier)
        self.assertNotIn("VOODOO_EXECUTOR_SHARED_SECRET=REPLACE", verifier)
        self.assertNotIn("VOODOO_FLEET_WORKER_TOKEN=REPLACE", verifier)

    def test_persistent_services_use_forever_and_lease_heartbeat_configuration(self):
        worker = (ROOT / "infra/r4/executor/voodoo-fleet-worker.service").read_text(encoding="utf-8")
        verifier = (ROOT / "infra/r4/executor/voodoo-fleet-verifier.service").read_text(encoding="utf-8")
        self.assertIn("--forever", worker)
        self.assertIn("--lease-seconds=90", worker)
        self.assertIn("SupplementaryGroups=docker", worker)
        self.assertIn("--forever", verifier)
        self.assertNotIn("SupplementaryGroups=docker", verifier)
        self.assertIn("ReadOnlyPaths=/srv/voodoo/workspaces", verifier)

    def test_supabase_security_hardening_is_least_privilege(self):
        migration = (ROOT / "supabase/migrations/20260831_r4_fleet_security_hardening.sql").read_text(encoding="utf-8")
        self.assertEqual(migration.count("set search_path = pg_catalog, public;"), 14)
        for table in ["voodoo_plans", "voodoo_jobs", "voodoo_fleet_events"]:
            self.assertIn(f"revoke insert, update, delete on table public.{table} from service_role;", migration)
            self.assertIn(f"grant select on table public.{table} to service_role;", migration)
        self.assertIn("alter function public.voodoo_append_event(text,text,text,jsonb,timestamptz) security definer;", migration)
        self.assertIn("revoke execute on function public.voodoo_append_event(text,text,text,jsonb,timestamptz) from service_role;", migration)
        self.assertIn("revoke all on sequence public.voodoo_fleet_events_seq_seq from service_role;", migration)

    def test_hosted_supabase_pgcrypto_schema_is_in_fixed_path(self):
        migration = (ROOT / "supabase/migrations/20260831_r4_pgcrypto_schema_parity.sql").read_text(encoding="utf-8")
        self.assertEqual(migration.count("set search_path = pg_catalog, public, extensions;"), 14)
        self.assertIn("hosted Supabase", migration)
        self.assertIn("pgcrypto", migration)

    def test_plan_foreign_key_has_covering_index_migration(self):
        migration = (ROOT / "supabase/migrations/20260831_r4_plan_fk_index.sql").read_text(encoding="utf-8")
        self.assertIn("create index if not exists voodoo_jobs_plan_id_idx", migration)
        self.assertIn("on public.voodoo_jobs(plan_id)", migration)


if __name__ == "__main__":
    unittest.main()
