# VOODOO-SKILLSET v0.2.0

Release candidate assembled on 2026-08-30.

Canonical trust rules:

- `PROJECT IDENTITY != EXECUTION AUTHORITY`
- `UNKNOWN != PASS`
- `MISSING != PASS`
- `UNVERIFIED != PASS`
- `ExecutionReceipt != IndependentVerification`

Local deterministic verification before remote release: 33 tests passed, JavaScript syntax PASS, plan verifier PASS, evidence-chain verifier PASS.

Remote GitHub Actions must pass on the exact release commit before remote status is promoted to VERIFIED.
