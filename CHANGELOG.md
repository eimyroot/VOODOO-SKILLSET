# Changelog

## 0.7.0 — 2026-08-30
- Added production R4 infrastructure contracts for GitHub governance, Vercel server-side secrets and persistent worker/verifier services.
- Added execution-lease heartbeat during long-running sandbox jobs; lease ownership uncertainty withholds successful completion fail-closed.
- Added persistent `--forever` worker/verifier loops with bounded polling and graceful SIGTERM/SIGINT shutdown.
- Fixed the Vercel Python wrapper to expose all durable fleet coordinator routes added in R3.
- Added exact deployment provenance through `VOODOO_CANONICAL_SHA` / `VERCEL_GIT_COMMIT_SHA` and `X-Canonical-SHA`.
- Added real Docker/runc long-job heartbeat CI proof.
- Added an active `main` ruleset payload requiring squash PRs, strict Python 3.12/3.13 checks, resolved review threads, signed commits, linear history and force-push/delete protection.
- Production provisioning remains fail-closed until a dedicated Supabase project, explicit Vercel project identity and persistent Linux host authority are available.

## 0.6.0 — 2026-08-30
- Added durable executor fleet state with atomic execution leases, retry budgets, verifier leases and hash-chained events.
- Added SQLite durable reference backend and Supabase/Postgres production schema using `FOR UPDATE SKIP LOCKED`.
- Added separate CONTROL / WORKER / VERIFIER bearer boundaries; database service-role credentials remain Control Plane only.
- Added database-secret-free coordinator clients for worker/verifier nodes.
- Added real two-worker Docker/runc fleet proof and independent verifier proof against the durable coordinator model.
- Added durable `BLOCKED` verification semantics and Control Room fleet truth view.

## 0.5.0 — 2026-08-30
- Added a real digest-pinned Docker/runc COMPUTE sandbox for executor hosts where unprivileged Linux namespaces are unavailable.
- Added `voodoo-executor` node entrypoint with fail-closed `auto | namespace | container` backend selection.
- Container runtime uses `--pull=never`, `--network=none`, read-only rootfs, all capabilities dropped, no-new-privileges, bounded PID/CPU/memory/fd limits and an ephemeral CASER workspace copy.
- Mutable image tags, selective egress, privileged mode and unisolated fallback remain blocked.
- Added real Linux live-node CI proving Control Plane → signed executor-v1 request → Docker/runc sandbox → signed receipt end-to-end.
- Live isolation evidence confirms no host filesystem, Docker socket or executor-secret exposure, zero effective capabilities, denied rootfs writes/network and no persistent workspace mutation.
- Updated executor systemd/env packaging and documented the Docker-daemon host-authority boundary.

## 0.4.0 — 2026-08-30
- Added signed remote CASTER-MINAL executor protocol (`executor-v1`).
- Added COMPUTE-only workspace-scoped remote execution with deny-by-default network policy.
- Added HMAC-SHA256 request/receipt signatures and persistent SQLite replay protection.
- Added executor health, operator CLI commands, server-side control-plane execution endpoint and evidence receipts.
- Added systemd/TLS deployment examples for a separate Linux executor host.
- Kept execution receipts separate from independent verification (`UNKNOWN != PASS`).

## 0.2.0 — 2026-08-30
- Added end-to-end governed orchestration control plane.
- Integrated CASER / CASER-SOURCER / CASER-MINER role contracts.
- Added CASTER-MINAL-compatible governed-terminal boundary.
- Added policy gates, DAG verification, evidence hash chain, API, CLI and Control Room UI.
- Added zero-dependency test suite and CI.
