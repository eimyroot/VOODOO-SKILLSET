# Changelog

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
