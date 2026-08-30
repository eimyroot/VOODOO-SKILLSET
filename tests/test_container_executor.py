import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voodoo_skillset.container_executor import MAX_CAPTURE_BYTES, DockerSandboxExecutor, configured_executor_adapter
from voodoo_skillset.execution import ExecutionEnvelope, NetworkPolicy

PINNED = "python@sha256:" + ("a" * 64)


class ContainerExecutorTests(unittest.TestCase):
    def fake_docker(self, root: Path, run_body: str = "exit 0") -> str:
        path = root / "docker"
        path.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"image\" ]; then exit 0; fi\n"
            "if [ \"$1\" = \"rm\" ]; then exit 0; fi\n"
            + run_body + "\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return str(path)

    def test_container_image_must_be_digest_pinned(self):
        with self.assertRaises(ValueError):
            DockerSandboxExecutor.validate_image("python:3.12-slim")
        with self.assertRaises(ValueError):
            DockerSandboxExecutor.validate_image("--help@sha256:" + ("a" * 64))
        DockerSandboxExecutor.validate_image(PINNED)

    def test_available_requires_prepulled_pinned_image(self):
        with tempfile.TemporaryDirectory() as d:
            runner = DockerSandboxExecutor(self.fake_docker(Path(d)), PINNED)
            ok, reason = runner.available()
            self.assertTrue(ok, reason)

    def test_command_is_hardened_and_never_privileged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            runner = DockerSandboxExecutor(self.fake_docker(root), PINNED)
            envelope = ExecutionEnvelope.local_reference(root)
            cmd = runner._command(root / "stage", Path("."), ("python3", "-c", "print(1)"), envelope)
            joined = " ".join(cmd)
            self.assertIn("--pull=never", cmd)
            self.assertIn("--network=none", cmd)
            self.assertIn("--read-only", cmd)
            self.assertIn("--cap-drop=ALL", cmd)
            self.assertIn("--security-opt=no-new-privileges:true", cmd)
            self.assertTrue(any(x.startswith("--name=voodoo-") for x in cmd))
            self.assertTrue(any(x.startswith("--pids-limit=") for x in cmd))
            self.assertTrue(any(x.startswith("--memory=") for x in cmd))
            self.assertTrue(any(x.startswith("--ulimit=fsize=") for x in cmd))
            self.assertTrue(any(x.startswith("--tmpfs=/tmp:") for x in cmd))
            self.assertNotIn("--privileged", cmd)
            self.assertNotIn("--network=host", cmd)
            self.assertNotIn("/var/run/docker.sock", joined)
            self.assertEqual(cmd[-3:], ["python3", "-c", "print(1)"])

    def test_execute_receipt_remains_unverified_and_ephemeral(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "marker.txt").write_text("v1", encoding="utf-8")
            runner = DockerSandboxExecutor(self.fake_docker(root), PINNED)
            out = runner.execute(
                "test-engineer",
                {"argv": ["python3", "-c", "print(1)"]},
                ExecutionEnvelope.local_reference(root),
            )
            self.assertEqual(out["status"], "EXECUTED")
            self.assertEqual(out["verification_status"], "UNKNOWN")
            self.assertEqual(out["persistent_effect"], "NONE")
            self.assertEqual(out["runner"], "docker-container-v1")
            self.assertIsNone(out["termination_reason"])
            self.assertTrue(out["isolation"]["no_new_privileges"])
            self.assertEqual(out["isolation"]["capabilities"], "ALL_DROPPED")

    def test_output_is_bounded_and_execution_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            docker = self.fake_docker(
                root,
                "python3 -c 'import sys; sys.stdout.write(\"x\" * 5000000)'",
            )
            runner = DockerSandboxExecutor(docker, PINNED)
            out = runner.execute("x", {"argv": ["python3", "-c", "print(1)"]}, ExecutionEnvelope.local_reference(root))
            self.assertEqual(out["status"], "FAILED")
            self.assertEqual(out["termination_reason"], "output limit exceeded")
            self.assertLessEqual(len(out["stdout"].encode("utf-8")), MAX_CAPTURE_BYTES)
            self.assertEqual(out["verification_status"], "UNKNOWN")

    def test_cwd_symlink_escape_is_denied(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "escape").symlink_to("/tmp")
            runner = DockerSandboxExecutor(self.fake_docker(root), PINNED)
            with self.assertRaises(ValueError):
                runner.execute(
                    "x",
                    {"argv": ["python3", "-c", "print(1)"], "cwd": "escape"},
                    ExecutionEnvelope.local_reference(root),
                )

    def test_container_backend_rejects_selective_egress(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            runner = DockerSandboxExecutor(self.fake_docker(root), PINNED)
            envelope = ExecutionEnvelope(
                operation_id="OP-test",
                target=str(root),
                network_policy=NetworkPolicy("DENY", ("api.github.com",)),
            )
            with self.assertRaises(PermissionError):
                runner.execute("x", {"argv": ["python3", "-c", "print(1)"]}, envelope)

    def test_explicit_backend_configuration_fails_closed(self):
        with patch.dict(os.environ, {"VOODOO_EXECUTOR_BACKEND": "unsafe-magic"}, clear=False):
            with self.assertRaises(ValueError):
                configured_executor_adapter()


if __name__ == "__main__":
    unittest.main()
