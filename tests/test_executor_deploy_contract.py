import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExecutorDeployContractTests(unittest.TestCase):
    def test_systemd_uses_hardened_executor_node(self):
        unit = (ROOT / "deploy/executor/voodoo-skillset-executor.service").read_text(encoding="utf-8")
        self.assertIn("/voodoo-executor --workspace-root /srv/voodoo/workspaces", unit)
        self.assertNotIn("voodoo-skillset executor-serve", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("CapabilityBoundingSet=", unit)
        self.assertNotIn("--privileged", unit)

    def test_environment_contract_requires_backend_and_pinned_image(self):
        env = (ROOT / "deploy/executor/executor.env.example").read_text(encoding="utf-8")
        self.assertIn("VOODOO_EXECUTOR_SHARED_SECRET=", env)
        self.assertIn("VOODOO_EXECUTOR_BACKEND=auto", env)
        self.assertIn("VOODOO_EXECUTOR_CONTAINER_IMAGE=", env)
        self.assertIn("@sha256:", env)
        self.assertIn("--pull=never", env)

    def test_r2_docs_state_docker_host_authority_and_ephemeral_ci_boundary(self):
        docs = (ROOT / "docs/EXECUTOR_R2.md").read_text(encoding="utf-8")
        self.assertIn("Docker daemon access is host-level authority", docs)
        self.assertIn("ephemeral verification node", docs)
        self.assertIn("not the persistent production executor", docs)
        self.assertIn("ExecutionReceipt != IndependentVerification", docs)


if __name__ == "__main__":
    unittest.main()
