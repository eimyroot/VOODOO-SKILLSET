from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import Protocol, Any


@dataclass(frozen=True)
class NetworkPolicy:
    default: str = "DENY"
    allowed_hosts: tuple[str, ...] = ()

    def allows(self, host: str) -> bool:
        return self.default == "ALLOW" or host in self.allowed_hosts


@dataclass(frozen=True)
class ExecutionEnvelope:
    operation_id: str
    target: str
    network_policy: NetworkPolicy
    timeout_seconds: int = 120
    cpu_limit_seconds: int = 30
    memory_limit_bytes: int = 536_870_912
    file_size_limit_bytes: int = 67_108_864
    nofile_limit: int = 256
    isolation_required: bool = True

    @classmethod
    def local_reference(cls, target: str | Path, allowed_hosts=()):
        return cls(
            f"OP-{uuid.uuid4().hex[:12]}",
            str(Path(target).resolve()),
            NetworkPolicy("DENY", tuple(allowed_hosts)),
        )


class ExecutionAdapter(Protocol):
    def execute(self, capability_id: str, payload: dict[str, Any], envelope: ExecutionEnvelope) -> dict[str, Any]: ...


class DryRunExecutor:
    """No-side-effect adapter used to test orchestration wiring."""

    def execute(self, capability_id, payload, envelope):
        return {
            "status": "SIMULATED",
            "capability_id": capability_id,
            "operation_id": envelope.operation_id,
            "effect": "NONE",
            "network_default": envelope.network_policy.default,
        }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _file_manifest(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in root.rglob("*"):
        if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        rel = str(p.relative_to(root))
        try:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
    return out


class LinuxNamespaceExecutor:
    """Ephemeral Linux compute runner with real kernel namespace isolation.

    Security properties:
    - user + mount + network + PID namespaces via ``unshare``;
    - chroot built inside the mount namespace;
    - read-only system runtime mounts;
    - staged project copy as the only writable project surface;
    - private tmpfs; no inherited environment/secrets;
    - CPU, address-space, file-size and fd limits;
    - network is physically absent in the namespace.

    This runner deliberately rejects non-empty network allowlists until a governed
    egress broker exists. It is a COMPUTE runner, not FILE_WRITE/REPO_WRITE authority.
    """

    FORBIDDEN_EXECUTABLES = {"bash", "sh", "zsh", "fish", "sudo", "su", "doas", "env", "printenv"}
    SECRET_PATTERNS = (".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519", ".npmrc", ".pypirc")

    def __init__(self, unshare_path: str | None = None):
        self.unshare_path = unshare_path or shutil.which("unshare") or ""

    def available(self) -> tuple[bool, str]:
        if sys.platform != "linux":
            return False, "linux namespaces unavailable on this platform"
        if not self.unshare_path:
            return False, "unshare executable not found"
        try:
            probe = subprocess.run(
                [
                    self.unshare_path,
                    "--user",
                    "--map-root-user",
                    "--mount",
                    "--net",
                    "--pid",
                    "--fork",
                    "true",
                ],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
                check=False,
                env={"PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"namespace capability probe failed: {exc}"
        if probe.returncode != 0:
            reason = probe.stderr.strip() or f"unshare probe exit {probe.returncode}"
            return False, f"namespace isolation unavailable: {reason}"
        return True, "linux user/mount/network/pid namespaces available"

    @staticmethod
    def _validate_argv(payload: dict[str, Any]) -> tuple[str, ...]:
        raw = payload.get("argv")
        if not isinstance(raw, list) or not raw or not all(isinstance(x, str) and x for x in raw):
            raise ValueError("payload.argv must be a non-empty string array")
        exe = Path(raw[0]).name
        if exe in LinuxNamespaceExecutor.FORBIDDEN_EXECUTABLES:
            raise PermissionError(f"shell/privileged wrapper blocked in isolated runner: {exe}")
        return tuple(raw)

    @staticmethod
    def _copy_workspace(source: Path, destination: Path) -> None:
        ignored = shutil.ignore_patterns(
            ".git",
            "__pycache__",
            "*.pyc",
            *LinuxNamespaceExecutor.SECRET_PATTERNS,
        )
        shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True, ignore=ignored)

    def execute(self, capability_id: str, payload: dict[str, Any], envelope: ExecutionEnvelope) -> dict[str, Any]:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)
        if envelope.network_policy.default != "DENY":
            raise PermissionError("namespace runner supports DENY network policy only")
        if envelope.network_policy.allowed_hosts:
            raise PermissionError("selective egress requires a governed network broker; fail-closed")

        argv = self._validate_argv(payload)
        target = Path(envelope.target).resolve()
        if not target.is_dir():
            raise RuntimeError(f"execution target is not a directory: {target}")

        rel_cwd = Path(str(payload.get("cwd", ".")))
        if rel_cwd.is_absolute() or ".." in rel_cwd.parts:
            raise ValueError("cwd must stay relative to staged workspace")

        source_manifest = _file_manifest(target)
        started = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory(prefix="voodoo-sandbox-") as tmp:
            tmp_root = Path(tmp)
            staged = tmp_root / "stage"
            rootfs = tmp_root / "rootfs"
            self._copy_workspace(target, staged)

            helper_pythonpath = str(Path(__file__).resolve().parents[1])
            command = [
                self.unshare_path,
                "--user",
                "--map-root-user",
                "--mount",
                "--net",
                "--pid",
                "--fork",
                "--kill-child",
                "--propagation",
                "private",
                sys.executable,
                "-m",
                "voodoo_skillset.sandbox_child",
                "--root",
                str(rootfs),
                "--workspace",
                str(staged),
                "--cwd",
                str(rel_cwd),
                "--cpu-seconds",
                str(envelope.cpu_limit_seconds),
                "--memory-bytes",
                str(envelope.memory_limit_bytes),
                "--file-size-bytes",
                str(envelope.file_size_limit_bytes),
                "--nofile",
                str(envelope.nofile_limit),
                *argv,
            ]
            proc = subprocess.run(
                command,
                cwd=str(target),
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=envelope.timeout_seconds,
                check=False,
                env={
                    "PATH": "/usr/bin:/bin",
                    "PYTHONPATH": helper_pythonpath,
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                },
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
            "runner": "linux-namespace-chroot-v1",
            "isolation": {
                "user_namespace": True,
                "mount_namespace": True,
                "network_namespace": True,
                "pid_namespace": True,
                "network_default": "DENY",
                "filesystem": "CHROOT_STAGE_ONLY",
                "system_mounts": "READ_ONLY",
                "workspace": "EPHEMERAL_COPY",
                "tmp": "TMPFS",
                "environment_inherited": False,
                "cpu_limit_seconds": envelope.cpu_limit_seconds,
                "memory_limit_bytes": envelope.memory_limit_bytes,
                "file_size_limit_bytes": envelope.file_size_limit_bytes,
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


class RunStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, record: dict[str, Any]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return rows[-limit:][::-1]


def run_record(plan_id: str, status: str, metadata: dict[str, Any] | None = None):
    return {
        "run_id": f"RUN-{uuid.uuid4().hex[:12]}",
        "plan_id": plan_id,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metadata": metadata or {},
    }
