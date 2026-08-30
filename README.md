# VOODOO-SKILLSET

Governed orchestration control plane for selecting, composing, executing and verifying AI capabilities without granting unrestricted authority.

## What is implemented

- Intent Compiler
- Capability Router with bounded learning signal
- Dynamic DAG Composer
- Governed Runtime contracts for skills / agents / subagents / plugins / tools
- CASER role model and source-of-truth boundaries
- CASTER-MINAL-compatible governed-terminal integration
- **Remote CASTER-MINAL executor bridge (`executor-v1`)**
- **Signed requests + signed receipts + persistent replay protection**
- **Workspace-scoped COMPUTE execution with deny-by-default network**
- **Fail-closed executor node with namespace or digest-pinned Docker/runc isolation**
- Authority Gate + fail-closed policy decisions
- Hash-chained Evidence Ledger
- Independent plan Verifier
- Red-team mode
- Zero-dependency REST API
- Responsive Web Control Room
- CLI
- CI matrix for Python 3.12 / 3.13

## Trust invariants

```text
PROJECT IDENTITY != EXECUTION AUTHORITY
UNKNOWN    != PASS
MISSING    != PASS
UNVERIFIED != PASS
ExecutionReceipt != IndependentVerification
```

## Local run

```bash
export PYTHONPATH=src
python -m unittest discover -s tests -p 'test_*.py' -v
python -m voodoo_skillset.cli plan \
  'Audit GitHub repo, review security, implement fixes, test and verify' \
  --mode ALL --connector github --tool filesystem-write --tool test-runner --tool isolated-runner --tool web-search
python -m voodoo_skillset.cli serve --port 8787
```

Open `http://127.0.0.1:8787`.

## Remote executor

The public Control Plane and the executor are deliberately separate trust domains.

```text
Control Plane / Control Room
        |
        | HTTPS + HMAC signed request
        v
CASTER-MINAL executor node
        |
        | bounded workspace_id
        v
safe backend probe
   |                 |
   v                 v
Linux namespaces   Docker/runc container
                  digest-pinned image
        |
        v
signed execution receipt
        |
        v
independent verification (separate)
```

The remote bridge accepts **COMPUTE only**. WRITE, REMOTE_WRITE, DEPLOY, DESTRUCTIVE and PRIVILEGED requests fail closed. Remote plaintext HTTP is refused; it is allowed only on localhost for development. Replay nonces persist in SQLite across executor restarts.

`VOODOO_EXECUTOR_BACKEND=auto` prefers the kernel namespace/chroot backend when its real capability probe succeeds. If user namespaces are blocked, it can use the container backend only when an immutable digest-pinned image has already been provisioned. There is no unisolated fallback.

The container sandbox uses `--pull=never`, `--network=none`, a read-only root filesystem, all Linux capabilities dropped, no-new-privileges, bounded PID/CPU/memory/fd limits and only an ephemeral CASER workspace copy. The Docker socket and executor secrets are not mounted/inherited by the child workload.

See [`docs/EXECUTOR_R1.md`](docs/EXECUTOR_R1.md) for the signed protocol and [`docs/EXECUTOR_R2.md`](docs/EXECUTOR_R2.md) for the real executor-node/container isolation model.

## Executor node

A provisioned Linux node runs:

```bash
VOODOO_EXECUTOR_SHARED_SECRET='...' \
VOODOO_EXECUTOR_BACKEND=auto \
VOODOO_EXECUTOR_CONTAINER_IMAGE='name@sha256:<digest>' \
voodoo-executor \
  --workspace-root /srv/voodoo/workspaces \
  --host 127.0.0.1 \
  --port 8790
```

The configured container image must be pre-pulled during host provisioning and referenced by its exact digest. Runtime execution never pulls a mutable image.

**Docker daemon access is host-level authority.** If the container backend uses the conventional Docker daemon, deploy it only on a dedicated CASTER-MINAL executor host. The application repository does not silently install Docker, add users to privileged groups or modify host package repositories.

## Reality boundary

v0.5 provides a real networked executor service/client protocol plus a real container-isolated COMPUTE backend. A live Linux CI node has executed the full Control Plane → signed executor → Docker/runc sandbox → signed receipt path with network denied, read-only rootfs, all capabilities dropped, no host/Docker-socket/secret exposure and no persistent workspace mutation.

That CI node is **ephemeral verification infrastructure, not a persistent production executor**. A persistent Linux VPS/VM still has to be provisioned and owned explicitly before the public Control Plane can be attached to a durable executor endpoint.

The Vercel Control Plane itself cannot provide this kernel/container executor trust boundary. The public browser Control Room does **not** receive executor secrets. Server-side remote execution requires `VOODOO_CONTROL_API_TOKEN`, a configured executor URL/secret, and a locally recorded `VERIFIED_PLAN`.

Current Vercel run/plan state is ephemeral, so durable multi-instance plan/evidence storage and user/session identity remain required before browser-driven production execution should be considered resilient.
