from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import resource

MS_RDONLY = 1
MS_NOSUID = 2
MS_NODEV = 4
MS_REMOUNT = 32
MS_BIND = 4096
MS_REC = 16384


def _mount(source: str | None, target: Path, flags: int = 0, fstype: str | None = None, data: str | None = None) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source_b = source.encode() if source is not None else None
    target_b = str(target).encode()
    fstype_b = fstype.encode() if fstype else None
    data_b = data.encode() if data else None
    rc = libc.mount(source_b, target_b, fstype_b, flags, data_b)
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), f"mount {source!r} -> {target}")


def _prepare_target(source: Path, target: Path) -> None:
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)


def _bind(source: Path, target: Path, *, read_only: bool) -> None:
    _prepare_target(source, target)
    _mount(str(source), target, MS_BIND | (MS_REC if source.is_dir() else 0))
    if read_only:
        _mount(None, target, MS_BIND | MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV)


def _apply_limits(cpu_seconds: int, memory_bytes: int, file_size_bytes: int, nofile: int) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_size_bytes, file_size_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VOODOO isolated namespace child")
    parser.add_argument("--root", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--cpu-seconds", type=int, default=30)
    parser.add_argument("--memory-bytes", type=int, default=536_870_912)
    parser.add_argument("--file-size-bytes", type=int, default=67_108_864)
    parser.add_argument("--nofile", type=int, default=256)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.command:
        raise SystemExit("missing command")

    root = Path(args.root).resolve()
    workspace = Path(args.workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)

    for rel in ("usr", "bin", "lib", "lib64", "etc", "workspace", "tmp", "dev"):
        (root / rel).mkdir(parents=True, exist_ok=True)

    for source_s in ("/usr", "/bin", "/lib", "/lib64", "/etc"):
        source = Path(source_s)
        if source.exists():
            _bind(source, root / source_s.lstrip("/"), read_only=True)

    _bind(workspace, root / "workspace", read_only=False)

    for source_s in ("/dev/null", "/dev/zero", "/dev/urandom", "/dev/random"):
        source = Path(source_s)
        if source.exists():
            _bind(source, root / source_s.lstrip("/"), read_only=False)

    _mount("tmpfs", root / "tmp", fstype="tmpfs", data="size=64m,mode=1777")
    _apply_limits(args.cpu_seconds, args.memory_bytes, args.file_size_bytes, args.nofile)

    os.chroot(root)
    work_cwd = (Path("/workspace") / args.cwd).resolve()
    if work_cwd != Path("/workspace") and Path("/workspace") not in work_cwd.parents:
        raise SystemExit("cwd escapes workspace")
    os.chdir(work_cwd)

    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": "/workspace/src",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    os.execvpe(args.command[0], args.command, env)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
