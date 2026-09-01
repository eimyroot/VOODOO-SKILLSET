# VOODOO-SKILLSET v0.7.1

Release-polish closure prepared on 2026-09-01.

## Scope

v0.7.1 closes repository presentation, operability and documentation consistency around the canonical v0.7 runtime. It does not broaden execution authority or weaken verification semantics.

Included:

- branded English-first GitHub front page
- repository banner
- one-command browser cockpit launcher
- CI proof that the cockpit starts and serves runtime truth
- repository/scaffold contract tests
- hardened generated-state and secret ignore rules
- contribution and vulnerability-reporting contracts
- architecture documentation aligned with the implemented R4 isolation/fleet model
- repository hygiene audit

## Canonical trust rules

```text
PROJECT IDENTITY != EXECUTION AUTHORITY
EXECUTOR IDENTITY != VERIFIER IDENTITY
UNKNOWN != PASS
MISSING != PASS
UNVERIFIED != PASS
ExecutionReceipt != IndependentVerification
ExclusiveLease != ExactlyOnce
```

## Promotion gate

The release is promotable only when GitHub Actions is green on the exact pull-request head for Python 3.12 and 3.13 and the cockpit HTTP smoke test passes.

Production infrastructure remains a separate evidence boundary. A green repository CI run does not imply that dedicated Supabase/Postgres, persistent Linux workers/verifiers or browser-to-production authorization are provisioned.
