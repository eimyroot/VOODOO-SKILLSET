from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

from .execution import ExecutionEnvelope, LinuxNamespaceExecutor, _file_manifest, _sha256_text

PINNED_IMAGE_RE = re.compile(r"^[^\s@]+(?:/[^\s@]+)*@sha256:[0-9a-f]{64}$")


class DockerSandboxExecutor:
    """Ephemeral container COMPUTE runner using a pre-pulled digest-pinned image.

    The Docker daemon itself is a host-level authority, so this backend is intended
    for a dedicated executor node. Runtime containers get no network, no extra caps,
    a read-only root filesystem, no inherited environment, bounded resources, and
    only an ephemeral copy of the selected CASER workspace mounted read/write.
    """

    backend_name = "docker-container-v1"

    def __init__(self, docker_path: str | None = None, image: str | None = None):
        self.docker_path = docker_path or shutil.which("docker") or ""
        self.image = image or os.environ.get("VOODOO_EXECUTOR_CONTAINER_IMAGE", "").strip()

    @staticmethod
    def validate_image(image: str) -> None:
        if not PINNED_IMAGE_RE.fullmatch(image):
            raise ValueError("container image must be digest-pinned: name@sha256:<64 hex>")

    def available(self) -> tuple[bool, str]:
        if not self.docker_path:
            return False, "docker executable not found"
        if not self.image:
            return False, "VOODOO_EXECUTOR_CONTAINER_IMAGE is not configured"
        try:
            self.validate_image(self.image)
        except ValueError as exc:
            return False, str(exc)
        try:
            proc = subprocess.run(
                [self.docker_path, "image", "inspect", self.image],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
                check=False,
                env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"container capability probe failed: {exc}"
        if proc.returncode != 0:
            return False, "digest-pinned container image is not pre-pulled on executor node"
        return True, f"docker available with pinned image {self.image}"

    @staticmethod
    def _validate_cwd(raw: Any) -> Path:
        cwd = Path(str(raw if raw is not None else "."))
        if cwd.is_absolute() or ".." in cwd.parts:
            raise ValueError("cwd must stay relative to staged workspace")
        return cwd

    def _command(self, staged: Path, cwd: Path, argv: tuple[str, ...], envelope: ExecutionEnvelope) -> list[str]:
        self.validate_image(self.image)
        uid = os.getuid() if hasattr(os, "getuid") else 65534
        gid = os.getgid() if hasattr(os, "getgid") else 65534
        workdir = "/workspace" if str(cwd) in {".", ""} else f"/workspace/{cwd.as_posix()}"
        return [
            self.docker_path,
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit=128",
            f"--memory={envelope.memory_limit_bytes}",
            f"--memory-swap={envelope.memory_limit_bytes}",
            "--cpus=1.0",
            f"--ulimit=nofile={envelope.nofile_limit}:{envelope.nofile_limit}",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=67108864",
            f"--user={uid}:{gid}",
            "--hostname=voodoo-sandbox",
            "--env=HOME=/tmp",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            f"--mount=type=bind,src={staged},dst=/workspace,rw",
            f"--workdir={workdir}",
            self.image,
            *argv,
        ]

    def execute(self, capability_id: str, payload: dict[str, Any], envelope: ExecutionEnvelope) -> dict[str, Any]:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)
        if envelope.network_policy.default != "DENY":
            raise PermissionError("container runner supports DENY network policy only")
        if envelope.network_policy.allowed_hosts:
            raise PermissionError("selective egress requires a governed network broker; fail-closed")

        argv = LinuxNamespaceExecutor._validate_argv(payload)
        cwd = self._validate_cwd(payload.get("cwd", "."))
        target = Path(envelope.target).resolve()
        if not target.is_dir():
            raise RuntimeError(f"execution target is not a directory: {target}")

        source_manifest = _file_manifest(target)
        started = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory(prefix="voodoo-container-") as tmp:
            staged = Path(tmp) / "stage"
            LinuxNamespaceExecutor._copy_workspace(target, staged)
            command = self._command(staged, cwd, argv, envelope)
            proc = subprocess.run(
                command,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=envelope.timeout_seconds,
                check=False,
                env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
            )
            staged_manifest = _file_manifest(staged)

        finished = datetime.now(timezone.utc)
        changed = sorted(
            key for key in set(source_manifest) | set(staged_manifest)
            if source_manifest.get(key) != staged_manifest.get(key)
        )
        return {
            "status": "EXECUTED" if proc.returncode == 0 else "FAILED",
            "verification_status": "UNKNOWN",
            "capability_id": capability_id,
            "operation_id": envelope.operation_id,
            "runner": self.backend_name,
            "container_image": self.image,
            "isolation": {
                "container": True,
                "network_namespace": True,
                "network_default": "DENY",
                "root_filesystem": "READ_ONLY",
                "workspace": "EPHEMERAL_COPY_ONLY",
                "capabilities": "ALL_DROPPED",
                "no_new_privileges": True,
                "environment_inherited": False,
                "pids_limit": 128,
                "cpu_limit": "1.0",
                "memory_limit_bytes": envelope.memory_limit_bytes,
                "nofile_limit": envelope.nofile_limit,
            },
            "argv": list(argv),
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "stdout_sha256": _sha256_text(proc.stdout),
            "stderr_sha256": _sha256_text(proc.stderr),
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "finished_at": finished.isoformat().replace("+00:00", "Z"),
            "staged_changes": changed,
            "persistent_effect": "NONE",
        }


class AutoSandboxExecutor:
    """Prefer kernel namespace isolation; fall back to the pinned container backend."""

    backend_name = "auto-sandbox-v1"

    def __init__(self):
        self.backends = (LinuxNamespaceExecutor(), DockerSandboxExecutor())

    def _select(self):
        reasons: list[str] = []
        for backend in self.backends:
            ok, reason = backend.available()
            if ok:
                return backend, reason
            reasons.append(f"{getattr(backend, 'backend_name', backend.__class__.__name__)}: {reason}")
        return None, "; ".join(reasons)

    def available(self) -> tuple[bool, str]:
        backend, reason = self._select()
        if backend is None:
            return False, reason
        return True, f"selected {getattr(backend, 'backend_name', backend.__class__.__name__)}: {reason}"

    @property
    def active_backend_name(self) -> str | None:
        backend, _ = self._select()
        return None if backend is None else getattr(backend, "backend_name", backend.__class__.__name__)

    def execute(self, capability_id: str, payload: dict[str, Any], envelope: ExecutionEnvelope) -> dict[str, Any]:
        backend, reason = self._select()
        if backend is None:
            raise RuntimeError(f"no safe executor backend available: {reason}")
        return backend.execute(capability_id, payload, envelope)


def configured_executor_adapter():
    backend = os.environ.get("VOODOO_EXECUTOR_BACKEND", "auto").strip().lower()
    if backend == "auto":
        return AutoSandboxExecutor()
    if backend == "namespace":
        return LinuxNamespaceExecutor()
    if backend == "container":
        return DockerSandboxExecutor()
    raise ValueError("VOODOO_EXECUTOR_BACKEND must be one of: auto, namespace, container")
