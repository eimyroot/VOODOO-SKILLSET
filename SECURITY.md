# Security Policy

VOODOO-SKILLSET is designed around fail-closed authority separation. Security reports are treated as trust-boundary issues, not ordinary feature requests.

## Reporting a vulnerability

Do **not** publish active exploit details, credentials, private infrastructure identifiers or sensitive proof in a public issue.

Prefer GitHub private vulnerability reporting / Security Advisories when that channel is available for this repository. Otherwise contact the repository maintainer privately through the GitHub account before disclosing technical details publicly.

Include, where possible:

- affected version or commit SHA
- affected trust boundary
- reproduction steps
- expected vs. actual behavior
- whether credentials, execution authority, isolation, verification or evidence integrity are impacted
- a minimal proof that does not expose third-party secrets

## High-priority classes

Reports involving any of the following should be treated as high priority:

- bypass of `VERIFIED_PLAN` or authority gates
- worker/verifier identity confusion
- service-role or executor-secret exposure
- replay-protection bypass
- signature verification failure
- sandbox/container escape or unintended host access
- network-default bypass
- evidence hash-chain forgery or silent mutation
- conversion of UNKNOWN/MISSING/UNVERIFIED into PASS
- unauthorized REMOTE_WRITE / DEPLOY / DESTRUCTIVE / PRIVILEGED execution

## Supported security contract

The current security architecture is documented in [`docs/SECURITY.md`](docs/SECURITY.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Production infrastructure claims must be supported by deployment evidence; repository source code alone is not proof that a production control plane or executor fleet is provisioned.
