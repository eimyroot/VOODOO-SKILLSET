# VOODOO-SKILLSET

Governed orchestration control plane for selecting, composing, executing and verifying AI capabilities without granting unrestricted authority.

## What is implemented

- Intent Compiler
- Capability Router with bounded learning signal
- Dynamic DAG Composer
- Governed Runtime contracts for skills / agents / subagents / plugins / tools
- CASER role model and source-of-truth boundaries
- CASTER-MINAL-compatible governed-terminal integration
- Authority Gate + fail-closed policy decisions
- Hash-chained Evidence Ledger
- Independent plan Verifier
- Red-team mode
- Zero-dependency REST API
- Responsive Web Control Room
- CLI
- CI matrix for Python 3.12 / 3.13

## Trust invariants

```text
PROJECT IDENTITY != EXECUTION AUTHORITY
UNKNOWN    != PASS
MISSING    != PASS
UNVERIFIED != PASS
ExecutionReceipt != IndependentVerification
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

## Reality boundary

v0.2 implements the control-plane foundation and a local governed reference runner. It does **not** claim a deployed microVM sandbox, production mutation authority, OIDC/RBAC, or provider credentials. Those remain explicit production-hardening work; see `docs/ROADMAP.md`.
