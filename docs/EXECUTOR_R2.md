# CASTER-MINAL Executor Node R2

R2 adds a production-oriented isolated COMPUTE backend for Linux hosts where unprivileged user namespaces are unavailable.

## Backend selection

`VOODOO_EXECUTOR_BACKEND=auto` probes in this order:

1. `LinuxNamespaceExecutor` — user/mount/network/PID namespaces + chroot.
2. `DockerSandboxExecutor` — digest-pinned, pre-pulled container image with a locked-down `docker run` contract.

If neither backend passes its capability probe, the executor node refuses to start. There is no unisolated fallback.

The GitHub-hosted Ubuntu verification environment rejects the namespace probe with `write failed /proc/self/uid_map: Operation not permitted`; R2 therefore exercised the real container backend instead of skipping execution or using `--privileged`.

## Container isolation contract

Runtime containers use:

```text
--pull=never
--network=none
--read-only
--cap-drop=ALL
--security-opt=no-new-privileges:true
--pids-limit=128
--memory=<bounded>
--memory-swap=<same bound>
--cpus=1.0
--ulimit=nofile=<bounded>
--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=67108864
--user=<executor uid>:<executor gid>
```

Only an ephemeral copy of the requested CASER workspace is bind-mounted at `/workspace`. The Docker socket is not mounted. The executor service secret and control-plane token are not inherited by the runtime container.

The container image must be configured as an immutable repository digest:

```text
name@sha256:<64 hexadecimal characters>
```

Mutable tags are rejected. The image must already exist on the executor node; the runtime uses `--pull=never` so executing a plan cannot silently change its base image or perform registry egress.

## Real-node evidence

The R2 live workflow performs an actual end-to-end execution on Linux:

```text
VERIFIED_PLAN
   -> authenticated Control Plane API
   -> HMAC signed executor-v1 request
   -> CASTER-MINAL executor node
   -> docker/runc isolated COMPUTE container
   -> signed execution receipt
   -> Control Plane evidence
```

The live assertions include:

- executor health `AVAILABLE`;
- Control Plane remote executor status `AVAILABLE`;
- receipt signature verified;
- runner is `docker-container-v1`;
- network connection attempt is denied;
- `/mnt/data` host path is absent;
- `/var/run/docker.sock` is absent;
- executor transport secret is absent from the child environment;
- write to container root filesystem is denied;
- Linux effective capabilities are zero;
- workspace writes occur only in the ephemeral staged copy;
- source workspace has no persistent mutation;
- receipt remains `verification_status=UNKNOWN`;
- independent verification remains `PENDING` until a separate verifier proves the result.

## Host authority boundary

**Docker daemon access is host-level authority.** Membership in the conventional `docker` group is effectively root-equivalent on that node. Therefore the example systemd service is suitable only for a dedicated CASTER-MINAL executor host with no unrelated workloads or secrets.

Preferred production hardening order:

1. dedicated minimal Linux executor host;
2. rootless Docker/Podman or another daemonless sandbox where operationally available;
3. immutable, digest-pinned executor images;
4. host firewall exposing only the TLS reverse proxy, never the Docker daemon or raw executor port;
5. executor service bound to `127.0.0.1:8790` behind TLS termination;
6. separate transport and Control Plane authorization secrets;
7. regular host rebuild/rotation instead of accumulating state;
8. durable evidence and plan store outside the executor host.

## Node provisioning contract

The repository intentionally does not install Docker or modify host package repositories automatically. Those are privileged supply-chain operations and belong to infrastructure provisioning with explicit host ownership.

Provisioning must establish:

```text
/opt/voodoo-skillset       immutable/release application tree
/etc/voodoo-skillset       root-owned executor.env
/srv/voodoo/workspaces     CASER workspace root
```

Then pre-pull and resolve the approved image digest during provisioning, write that exact digest into `VOODOO_EXECUTOR_CONTAINER_IMAGE`, install the systemd unit, and terminate TLS with the supplied Caddy example or equivalent.

## What R2 does not claim

- A GitHub-hosted runner is an ephemeral verification node, **not** the persistent production executor.
- No persistent public VPS was provisioned by this repository change.
- WRITE, REMOTE_WRITE, DEPLOY, DESTRUCTIVE and PRIVILEGED remain outside `executor-v1`.
- A signed execution receipt is not an outcome PASS.
- Browser-driven production execution still requires durable plan/evidence state and user/session identity in the Control Plane.

The core invariants remain:

```text
PROJECT IDENTITY != EXECUTION AUTHORITY
UNKNOWN != PASS
MISSING != PASS
UNVERIFIED != PASS
ExecutionReceipt != IndependentVerification
```
