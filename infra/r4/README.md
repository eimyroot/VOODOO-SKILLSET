# R4 Production Infrastructure

R4 converts the canonical R3 fleet into a production-deployable topology without weakening the governance model.

## Target topology

```text
Browser / Operator
        |
        v
Vercel Control Plane
  - exact canonical SHA provenance
  - Supabase service-role stays server-side
  - CONTROL / WORKER / VERIFIER bearer separation
        |
        v
Dedicated VOODOO Supabase/Postgres
  - durable VERIFIED_PLAN authority
  - atomic execution leases
  - durable receipts / verification / hash-chain events
        |
        +-------------------------+
        |                         |
        v                         v
CASTER-MINAL worker(s)      Independent verifier(s)
  worker token only          verifier token only
  executor secret            NO executor secret
  Docker/runc COMPUTE        NO Docker authority
  persistent poll loop       read-only verification workspace
  lease heartbeat
```

## R4 hardening added before production

1. Long-running execution leases are heartbeated while the sandbox workload runs.
2. Loss of lease ownership is fail-closed: the worker withholds a successful completion and reports `LEASE_UNCERTAIN`.
3. Fleet workers/verifiers support persistent `--forever` poll loops with SIGTERM/SIGINT shutdown.
4. The Vercel Python wrapper exposes every R3 fleet coordinator route instead of returning 404.
5. Vercel health exposes an exact 40-hex `canonical_sha` from `VOODOO_CANONICAL_SHA` or `VERCEL_GIT_COMMIT_SHA`.
6. Production secret contracts keep Supabase service-role credentials in the Control Plane only.
7. GitHub `main` has an explicit active ruleset payload requiring squash PRs, strict Python 3.12/3.13 CI, resolved review threads, signed commits, linear history and blocking force-push/delete.

## Authority boundaries

### Vercel Control Plane

Required server-side secrets are documented in `vercel/production.env.example`. Never use `NEXT_PUBLIC_`/browser-exposed equivalents for these values.

### Worker host

`executor/worker.env.example` contains only:

- `VOODOO_FLEET_WORKER_TOKEN`
- `VOODOO_EXECUTOR_SHARED_SECRET`
- executor backend/image configuration

It intentionally excludes CONTROL, VERIFIER and database service-role credentials.

### Verifier host/process

`executor/verifier.env.example` contains only `VOODOO_FLEET_VERIFIER_TOKEN`. It intentionally has no executor secret, no worker token, no CONTROL token and no database service-role key.

For strongest independence, run verifier capacity on a separate host with read-only access to the evidence/workspace material needed by its verification specification. The included same-filesystem systemd unit is a minimum deployable separation of identity and Unix authority, not a claim of separate-host independence.

## Current external infrastructure reality

At R4 construction time:

- GitHub repository rulesets: none were active; the connected GitHub tool does not expose Administration-write ruleset mutation.
- Vercel team project listing did not expose the historical `voodoo-skillset` project even though its public alias exists; production deployment must therefore be bound to an explicit Vercel project identity before it is trusted.
- Supabase exposes one organization named `ODKAZERO`; creating a new dedicated VOODOO project requires explicit organization selection and cost confirmation.
- No persistent VPS/VM provider with provisioning authority is connected to the current tool environment.

These are infrastructure authority boundaries, not reasons to weaken the application contract.

## Production acceptance gate

A production PASS requires all of the following on the same canonical release:

```text
GitHub main ruleset                  ACTIVE
canonical main                      VERIFIED
exact-head CI                       PASS
Vercel project identity             VERIFIED
Vercel deployment canonical_sha     exact canonical SHA
/api/health                         200 + version + canonical SHA
/api/fleet                          durable Supabase backend AVAILABLE
Supabase R3 migration               APPLIED + contract smoke PASS
worker host                         persistent + health/lease smoke PASS
worker credential boundary          VERIFIED
long-job lease heartbeat            VERIFIED
real Docker/runc workload           EXECUTED with network DENY
receipt signature                   VERIFIED
independent verifier identity       VERIFIED
final job outcome                   VERIFIED / FAILED / BLOCKED truthfully
```

`UNKNOWN != PASS`, `MISSING != PASS`, `UNVERIFIED != PASS` remain mandatory.
