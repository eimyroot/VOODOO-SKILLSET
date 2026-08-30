from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

from .execution import ExecutionEnvelope, LinuxNamespaceExecutor, _file_manifest, _sha256_text

PINNED_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
MAX_CAPTURE_BYTES = 4_194_304


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

    @staticmethod
    def _runtime_env() -> dict[str, str]:
        return {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}

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
                env=self._runtime_env(),
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

    @staticmethod
    def _container_name(operation_id: str) -> str:
        safe = re.sub(r"[^a-z0-9_.-]+", "-", operation_id.lower()).strip("-.")
        return ("voodoo-" + (safe or "operation"))[:63]

    def _command(self, staged: Path, cwd: Path, argv: tuple[str, ...], envelope: ExecutionEnvelope) -> list[str]:
        self.validate_image(self.image)
        uid = os.getuid() if hasattr(os, "getuid") else 65534
        gid = os.getgid() if hasattr(os, "getgid") else 65534
        workdir = "/workspace" if str(cwd) in {".", ""} else f"/workspace/{cwd.as_posix()}"
        return [
            self.docker_path,
            "run",
            "--rm",
            f"--name={self._container_name(envelope.operation_id)}",
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
            f"--ulimit=fsize={envelope.file_size_limit_bytes}:{envelope.file_size_limit_bytes}",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=67108864",
            f"--user={uid}:{gid}",
            "--hostname=voodoo-sandbox",
            "--env=HOME=/tmp",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            f"--mount=type=bind,src={staged},dst=/workspace",
            f"--workdir={workdir}",
            self.image,
            *argv,
        ]

    def _force_remove(self, name: str) -> None:
        try:
            subprocess.run(
                [self.docker_path, "rm", "-f", name],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                env=self._runtime_env(),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _run_bounded(self, command: list[str], name: str, timeout_seconds: int) -> tuple[int, str, str, str | None]:
        proc = subprocess.Popen(
            command,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._runtime_env(),
        )
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        overflow = threading.Event()
        lock = threading.Lock()

        def drain(pipe, key: str):
            try:
                while True:
                    chunk = pipe.read(65_536)
                    if not chunk:
                        break
                    with lock:
                        remaining = MAX_CAPTURE_BYTES - len(buffers[key])
                        if remaining > 0:
                            buffers[key].extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            overflow.set()
                            break
            finally:
                pipe.close()

        assert proc.stdout is not None and proc.stderr is not None
        threads = [
            threading.Thread(target=drain, args=(proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=drain, args=(proc.stderr, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        deadline = time.monotonic() + timeout_seconds
        termination: str | None = None
        while proc.poll() is None:
            if overflow.is_set():
                termination = "output limit exceeded"
                self._force_remove(name)
                if proc.poll() is None:
                    proc.kill()
                break
            if time.monotonic() >= deadline:
                termination = "execution timeout"
                self._force_remove(name)
                if proc.poll() is None:
                    proc.kill()
                break
            time.sleep(0.02)

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._force_remove(name)
            proc.kill()
            proc.wait(timeout=5)
            termination = termination or "executor cleanup timeout"

        for thread in threads:
            thread.join(timeout=2)

        if termination:
            marker = ("\nVOODOO: " + termination + "\n").encode("utf-8")
            with lock:
                remaining = MAX_CAPTURE_BYTES - len(buffers["stderr"])
                if remaining > 0:
                    buffers["stderr"].extend(marker[:remaining])

        stdout = bytes(buffers["stdout"]).decode("utf-8", errors="replace")
        stderr = bytes(buffers["stderr"]).decode("utf-8", errors="replace")
        if termination == "execution timeout":
            return 124, stdout, stderr, termination
        if termination:
            return 125, stdout, stderr, termination
        return int(proc.returncode or 0), stdout, stderr, None

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
            staged_root = staged.resolve()
            staged_cwd = (staged / cwd).resolve()
            if staged_cwd != staged_root and staged_root not in staged_cwd.parents:
                raise ValueError("cwd escaped staged workspace through symlink resolution")
            if not staged_cwd.is_dir():
                raise ValueError("cwd does not exist in staged workspace")
            command = self._command(staged, cwd, argv, envelope)
            name = self._container_name(envelope.operation_id)
            exit_code, stdout, stderr, termination = self._run_bounded(command, name, envelope.timeout_seconds)
            staged_manifest = _file_manifest(staged)

        finished = datetime.now(timezone.utc)
        changed = sorted(
            key for key in set(source_manifest) | set(staged_manifest)
            if source_manifest.get(key) != staged_manifest.get(key)
        )
        return {
            "status": "EXECUTED" if exit_code == 0 else "FAILED",
            "verification_status": "UNKNOWN",
            "capability_id": capability_id,
            "operation_id": envelope.operation_id,
            "runner": self.backend_name,
            "container_image": self.image,
            "termination_reason": termination,
            "output_limit_bytes_per_stream": MAX_CAPTURE_BYTES,
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
                "file_size_limit_bytes": envelope.file_size_limit_bytes,
                "nofile_limit": envelope.nofile_limit,
            },
            "argv": list(argv),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_sha256": _sha256_text(stdout),
            "stderr_sha256": _sha256_text(stderr),
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
