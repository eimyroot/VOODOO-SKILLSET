# Changelog

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
