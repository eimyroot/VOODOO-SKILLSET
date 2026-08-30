# VOODOO-SKILLSET

Governed orchestration control plane for selecting, composing, executing and independently verifying AI capabilities without granting unrestricted authority.

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
- **R3 durable Executor Fleet with atomic leases, TTL/heartbeat, retries and separate verifier leases**
- **SQLite durable reference backend + Supabase/Postgres multi-instance contract**
- **Worker/verifier coordinator clients that never receive database service-role credentials**
- Authority Gate + fail-closed policy decisions
- Hash-chained Evidence Ledger + hash-chained fleet events
- Independent plan Verifier + independent fleet verifier workers
- Red-team mode
- Zero-dependency REST API
- Responsive Web Control Room including Executor Fleet truth
- CLI
- CI matrix for Python 3.12 / 3.13
- Real Linux Docker/runc executor and multi-worker fleet E2E gates

## Trust invariants

```text
PROJECT IDENTITY != EXECUTION AUTHORITY
EXECUTOR IDENTITY != VERIFIER IDENTITY
UNKNOWN    != PASS
MISSING    != PASS
UNVERIFIED != PASS
ExecutionReceipt != IndependentVerification
ExclusiveLease != ExactlyOnce
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

## Executor architecture

```text
Operator / Browser
       |
       v
VOODOO Control Plane
       |
       +---- durable VERIFIED_PLAN / queue / evidence ----+
       |                                                   |
       | WORKER bearer                                     | VERIFIER bearer
       v                                                   v
CASTER-MINAL workers 1..N                         independent verifier workers
       |
       | signed executor-v1
       v
safe backend probe
   |                 |
   v                 v
Linux namespaces   Docker/runc container
                  digest-pinned image
       |
       v
signed receipt: UNKNOWN
       |
       +--------------------> durable coordinator ---------> VERIFIED / FAILED / BLOCKED
```

The executor accepts **COMPUTE only**. WRITE, REMOTE_WRITE, DEPLOY, DESTRUCTIVE and PRIVILEGED requests fail closed. Remote plaintext coordinator/executor HTTP is refused except on localhost for development and CI.

`VOODOO_EXECUTOR_BACKEND=auto` prefers the kernel namespace/chroot backend when its real capability probe succeeds. If user namespaces are blocked, it can use the container backend only when an immutable digest-pinned image has already been provisioned. There is no unisolated fallback.

The Docker/runc sandbox uses `--pull=never`, `--network=none`, a read-only root filesystem, all Linux capabilities dropped, no-new-privileges, bounded PID/CPU/memory/file-size/fd/output limits and only an ephemeral CASER workspace copy. The Docker socket and executor/control-plane secrets are not mounted into the child workload.

See:

- [`docs/EXECUTOR_R1.md`](docs/EXECUTOR_R1.md) — signed remote protocol
- [`docs/EXECUTOR_R2.md`](docs/EXECUTOR_R2.md) — real isolated executor node
- [`docs/EXECUTOR_R3.md`](docs/EXECUTOR_R3.md) — durable executor fleet and independent verifier workers

## R3 durable fleet

R3 separates four authority domains:

```text
CONTROL token   -> enqueue jobs for durable VERIFIED_PLAN only
WORKER token    -> claim / heartbeat / receipt / failure only
VERIFIER token  -> verification claim / verdict only
DB service role -> Control Plane only
```

Workers and verifiers use the HTTP coordinator API. They never receive the Supabase service-role key. A worker also cannot verify a job it executed.

The queue uses exclusive active leases with TTL and retry. This prevents legitimate concurrent double ownership, but retries make delivery at-least-once capable, so VOODOO does **not** mislabel this as mathematical exactly-once.

### Durable backends

**SQLite reference** is suitable for one persistent coordinator volume:

```bash
VOODOO_FLEET_DB=/srv/voodoo/fleet.sqlite3
```

**Supabase/Postgres** is the intended multi-instance Vercel backend:

```text
VOODOO_FLEET_SUPABASE_URL
VOODOO_FLEET_SUPABASE_SERVICE_ROLE_KEY
VOODOO_CONTROL_API_TOKEN
VOODOO_FLEET_WORKER_TOKEN
VOODOO_FLEET_VERIFIER_TOKEN
VOODOO_EXECUTOR_SHARED_SECRET
```

The Postgres contract uses `FOR UPDATE SKIP LOCKED`, RLS, deny-by-default client roles, hashed lease tokens and append-only hash-chain events.

## Executor node

A provisioned Linux node can run the standalone service:

```bash
VOODOO_EXECUTOR_SHARED_SECRET='...' \
VOODOO_EXECUTOR_BACKEND=auto \
VOODOO_EXECUTOR_CONTAINER_IMAGE='name@sha256:<digest>' \
voodoo-executor \
  --workspace-root /srv/voodoo/workspaces \
  --host 127.0.0.1 \
  --port 8790
```

Fleet workers can instead claim work from the Control Plane coordinator:

```bash
VOODOO_FLEET_WORKER_TOKEN='...' \
VOODOO_EXECUTOR_SHARED_SECRET='...' \
VOODOO_EXECUTOR_BACKEND=container \
VOODOO_EXECUTOR_CONTAINER_IMAGE='name@sha256:<digest>' \
voodoo-fleet-worker \
  --coordinator-url https://control.example.com \
  --workspace-root /srv/voodoo/workspaces \
  --worker-id executor-01 \
  --drain
```

The independent verifier uses a different bearer and identity:

```bash
VOODOO_FLEET_VERIFIER_TOKEN='...' \
voodoo-fleet-verifier \
  --coordinator-url https://control.example.com \
  --workspace-root /srv/voodoo/workspaces \
  --verifier-id verifier-01 \
  --drain
```

**Docker daemon access is host-level authority.** Conventional Docker daemon access belongs only on a dedicated CASTER-MINAL executor host; rootless/daemonless isolation is preferred where operationally available.

## Reality boundary

v0.6 contains a real multi-worker fleet implementation and a deployable Supabase/Postgres contract. CI is designed to prove both the Postgres lease/RLS/event-chain behavior and a two-worker Docker/runc execution fleet with a separate independent verifier.

GitHub-hosted Linux runners are real execution evidence but remain ephemeral verification infrastructure, not a persistent production fleet.

A dedicated VOODOO Supabase project has **not** been silently created or mixed into existing unrelated projects. Creating that paid durable database is a separate infrastructure authorization step. Persistent/on-demand Linux executor capacity and durable workspace/artifact transport are also separate production infrastructure boundaries.

The browser Control Room exposes fleet truth but no execution/database secrets. Browser-driven production execution should remain blocked until durable identity/session authorization and the production fleet/database infrastructure are configured and independently verified.
