# Architecture

VOODOO-SKILLSET is a governance-first orchestration control plane. Discovery, planning, authority, execution, verification and evidence are intentionally separated so that no single component can silently turn an unverified action into trusted state.

## System flow

```text
USER / OPERATOR
      |
      v
Intent Compiler
      |
      v
Capability Router <------ bounded learning signal
      |
      v
Dynamic DAG Composer
      |
      v
Independent Plan Verifier
      |
      v
Authority Gate --------------------------+
      |                                   |
      | ALLOW / APPROVAL                  | BLOCK
      v                                   v
Durable VERIFIED_PLAN                  Evidence
      |
      v
Control Plane Coordinator
      |
      +----------------------+----------------------+
      |                      |                      |
      | worker bearer        | verifier bearer      | browser read path
      v                      v                      v
CASTER-MINAL worker      Independent verifier    Control Room
      |
      v
executor-v1 signed request
      |
      v
Isolation backend probe
      |
      +----------------------+
      |                      |
      v                      v
Linux namespace/chroot   Docker/runc
                         digest-pinned image
      |                      |
      +----------+-----------+
                 |
                 v
         signed execution receipt
         verification = UNKNOWN
                 |
                 v
       durable verification lease
                 |
                 v
      VERIFIED / FAILED / BLOCKED
                 |
                 v
       hash-chained fleet events
       + Evidence Ledger
```

## Authority domains

| Domain | Authority | Must not receive |
| --- | --- | --- |
| Control Plane | plan, policy, durable queue, coordinator state | executor host authority by implication |
| Worker | claim/heartbeat/execute/report | database service-role, verifier token |
| Verifier | claim verification, inspect proof, issue verdict | executor secret, worker authority |
| Browser cockpit | read runtime truth, compile governed plan | database secrets, executor secrets |
| CASER workspace | bounded project state | repository/deploy authority by identity alone |

Core invariants:

```text
PROJECT IDENTITY != EXECUTION AUTHORITY
EXECUTOR IDENTITY != VERIFIER IDENTITY
UNKNOWN != PASS
MISSING != PASS
UNVERIFIED != PASS
ExecutionReceipt != IndependentVerification
ExclusiveLease != ExactlyOnce
```

## Control Plane

The Control Plane owns capability selection, DAG composition, policy evaluation, run/evidence recording and durable fleet coordination. A plan may enter the durable execution queue only when it is recorded as `VERIFIED_PLAN`.

The browser Control Room is intentionally not an administrative secret surface. It can display runtime/fleet/evidence truth and request planning, but production mutation remains separately governed.

## Execution Plane

Execution is COMPUTE-only at the remote executor boundary.

`VOODOO_EXECUTOR_BACKEND=auto` performs a real capability probe and selects only a supported isolated backend:

1. Linux namespace/chroot when the kernel/user-namespace contract is available.
2. Digest-pinned Docker/runc when an immutable image is already provisioned.
3. Otherwise execution is blocked. There is no unisolated fallback.

The Docker/runc contract uses:

- `--pull=never`
- `--network=none`
- read-only root filesystem
- all Linux capabilities dropped
- `no-new-privileges`
- bounded PID, CPU, memory, file-size, fd and output limits
- ephemeral CASER workspace copy only
- no Docker socket inside the child workload
- no executor/control-plane secret mounts

Docker daemon access itself remains host-level authority and therefore belongs on a dedicated executor host.

## Durable Fleet

The fleet separates credentials by function:

```text
CONTROL token   -> enqueue durable VERIFIED_PLAN work
WORKER token    -> claim / heartbeat / receipt / failure
VERIFIER token  -> verification claim / verdict
DB service role -> Control Plane only
```

The reference backend is SQLite for one persistent coordinator. The multi-instance contract is Supabase/Postgres with `FOR UPDATE SKIP LOCKED`, RLS, hashed lease tokens and append-only hash-chain events.

Execution leases use TTL + heartbeat + retry. The model prevents concurrent valid ownership but is intentionally described as at-least-once capable rather than exactly-once.

## Evidence and Verification

An execution receipt proves that an executor produced a signed result for a signed request. It does **not** prove that the requested objective was satisfied.

Independent verifier workers use a separate identity and lease. Final fleet state is one of:

- `VERIFIED`
- `FAILED`
- `BLOCKED`

Evidence is recorded in hash-chained ledgers. Missing proof remains missing; it is never inferred into PASS.

## CASER boundaries

CASER provides bounded workspace/orchestration context. `SCRATCH -> WORKSPACE -> VAULT` is an explicit state progression; VAULT overwrite is denied by default. Workspace identity still does not grant repository, deployment or privileged execution authority.

CASER-SOURCER is responsible for provenance/truth boundaries. CASER-MINER is research intelligence only. CASTER-MINAL is the governed execution boundary.

## Deployment topology

```text
Browser
  |
  v
Vercel Control Plane
  |
  v
Dedicated Supabase/Postgres
  |
  +------------------------+
  |                        |
  v                        v
Persistent worker(s)    independent verifier(s)
  |
  v
Dedicated Linux executor isolation
```

The repository contains deployment contracts for this topology, but source code alone does not imply that dedicated production Supabase, persistent Linux executor capacity, artifact transport or browser-to-production authorization have been provisioned.

## Repository boundaries

```text
api/                 hosting adapter only
src/voodoo_skillset/ product runtime and trust logic
web/                 zero-build browser cockpit
tests/               unit + contract + integration proof
registry/            capability source of truth
schemas/             machine-readable contracts
integrations/        external integration contracts
infra/               production infrastructure definitions
deploy/              host deployment examples
tools/               operator/verification tooling
docs/                explanatory contracts and runbooks
evidence/            runtime/local evidence state boundary
```

Runtime logic should remain in `src/voodoo_skillset/`; hosting adapters should stay thin, and documentation must not redefine security semantics independently from executable contracts/tests.
