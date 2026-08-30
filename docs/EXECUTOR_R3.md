# CASTER-MINAL Executor Fleet R3

R3 turns the single-node `executor-v1` path into a governed fleet model with durable planning authority, exclusive execution leases, retry semantics, a separate verifier lease and append-only fleet evidence.

## Architecture

```text
Browser / Operator
        |
        v
VOODOO Control Plane
        |
        | CONTROL authority
        v
Durable Fleet Coordinator
        |
        +--> durable VERIFIED_PLAN records
        +--> durable job queue
        +--> atomic execution leases
        +--> receipt verification
        +--> verifier leases
        +--> append-only hash-chain events
        |
        | WORKER bearer only
        v
CASTER-MINAL workers 1..N
        |
        | executor-v1 + isolated COMPUTE
        v
Docker/runc or namespace sandbox
        |
        | signed receipt; verification_status=UNKNOWN
        v
Durable Coordinator
        |
        | VERIFIER bearer only
        v
Independent verifier workers
        |
        v
VERIFIED | FAILED | BLOCKED
```

## Authority separation

R3 deliberately uses separate credentials and identities:

```text
CONTROL token   -> may enqueue jobs for a durable VERIFIED_PLAN
WORKER token    -> may claim/heartbeat/report execution jobs
VERIFIER token  -> may claim and submit independent verification
DB service role -> Control Plane only; never sent to workers/verifiers
executor secret -> worker + Control Plane receipt verification; never sent to verifier
```

A worker cannot claim the verification lease for a job it executed. A signed execution receipt is accepted into durable state only when its signature is verified by the Control Plane and the receipt still says `verification_status=UNKNOWN`.

## Queue semantics

R3 does **not** claim mathematical exactly-once execution.

The contract is:

- one active execution lease per job;
- lease token stored as a SHA-256 hash, raw token returned only to the lease owner;
- bounded TTL with heartbeat support;
- expired lease reaping;
- bounded retry budget;
- retries make delivery **at-least-once capable**;
- exclusive active leases prevent legitimate concurrent duplicate ownership;
- worker crashes can cause a retry after lease expiry;
- verifier ownership is a separate lease and identity.

This wording is intentional: `exclusive lease != exactly once`.

## Durable state backends

### SQLite durable reference

`DurableFleetStore` is the zero-dependency reference backend for one coordinator with a persistent volume. It is used for deterministic tests and single-host deployments.

It persists:

- plans;
- jobs and state transitions;
- execution/verifier owners and lease hashes;
- attempt counts and retry budget;
- signed execution receipts and receipt digest;
- independent verification result;
- global append-only hash-chain fleet events.

It is **not** the recommended backend for horizontally scaled Vercel instances.

### Supabase/Postgres production contract

`supabase/migrations/20260830_r3_executor_fleet.sql` defines the production database contract. Atomic job selection uses:

```sql
FOR UPDATE SKIP LOCKED
```

The schema enables RLS and revokes fleet table/RPC access from `anon` and `authenticated`. Only the server-side Supabase `service_role` receives the required database/RPC privileges.

`SupabaseFleetStore` is a zero-dependency PostgREST adapter used by the Control Plane. Executor and verifier nodes never receive the Supabase service-role key.

Required production environment variables:

```text
VOODOO_FLEET_SUPABASE_URL
VOODOO_FLEET_SUPABASE_SERVICE_ROLE_KEY
VOODOO_CONTROL_API_TOKEN
VOODOO_FLEET_WORKER_TOKEN
VOODOO_FLEET_VERIFIER_TOKEN
VOODOO_EXECUTOR_SHARED_SECRET
```

## Coordinator API

Read-only runtime truth:

```text
GET /api/fleet
GET /api/fleet/events
```

Control authority:

```text
POST /api/fleet/jobs
```

Worker authority:

```text
POST /api/fleet/claim
POST /api/fleet/heartbeat
POST /api/fleet/complete
POST /api/fleet/fail
```

Verifier authority:

```text
POST /api/fleet/verify/claim
POST /api/fleet/verify/complete
```

Remote fleet coordinator clients require HTTPS. Plaintext HTTP is accepted only for localhost development/test communication.

## Independent verification

The reference independent verifier can assert independently observable properties such as:

- expected exit code;
- expected isolated runner backend;
- `persistent_effect=NONE`;
- deny-by-default network status;
- read-only root filesystem;
- all Linux capabilities dropped;
- expected stdout evidence;
- source workspace manifest unchanged after ephemeral sandbox execution.

A `VERIFIED` verdict requires non-empty checks and every check must pass. Missing evidence must not become PASS.

## Real R3 fleet proof

The `fleet-r3-live` workflow is designed to prove two independent boundaries:

1. **Postgres contract** — migrations, server-role behavior, client-role denial, atomic concurrent claims and event-chain integrity.
2. **Real fleet** — two concurrent worker processes communicate only with the coordinator HTTP API, execute actual Docker/runc sandboxes, then a different verifier process independently verifies all jobs.

The real-fleet worker processes are launched without:

- the fleet DB path;
- Supabase credentials;
- CONTROL token;
- VERIFIER token.

The verifier process is launched without:

- fleet DB path;
- CONTROL token;
- WORKER token;
- executor shared secret.

## Deployment reality boundary

R3 provides a deployable Supabase/Postgres contract but **does not claim a dedicated VOODOO Supabase project is already provisioned**.

At the time R3 was built, the connected Supabase account exposed existing ODKAZERO projects only. VOODOO data was intentionally not mixed into those projects. Creating a new Supabase project is a separate paid infrastructure/provisioning authorization boundary.

Likewise, GitHub-hosted runner fleet nodes are real isolated execution evidence but are ephemeral verification infrastructure, not persistent production workers.

A complete production topology still requires:

1. a dedicated VOODOO durable database project;
2. Vercel server-side fleet environment variables;
3. persistent or ephemeral-on-demand Linux executor capacity reachable over HTTPS;
4. secure secret provisioning/rotation;
5. durable workspace/artifact transport for workloads that cannot share a local workspace root;
6. production identity/session layer before browser-driven execution is exposed.

## Invariants

```text
PROJECT IDENTITY != EXECUTION AUTHORITY
EXECUTOR IDENTITY != VERIFIER IDENTITY
UNKNOWN != PASS
MISSING != PASS
UNVERIFIED != PASS
ExecutionReceipt != IndependentVerification
ExclusiveLease != ExactlyOnce
```
