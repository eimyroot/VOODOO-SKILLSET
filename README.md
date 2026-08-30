# VOODOO-SKILLSET

Governed orchestration control plane for selecting, composing, executing and verifying AI capabilities without granting unrestricted authority.

## What is implemented

- Intent Compiler
- Capability Router with bounded learning signal
- Dynamic DAG Composer
- Governed Runtime contracts for skills / agents / subagents / plugins / tools
- CASER role model and source-of-truth boundaries
- CASTER-MINAL-compatible governed-terminal integration
- **Remote CASTER-MINAL executor bridge (`executor-v1`)**
- **Signed requests + signed receipts + persistent replay protection**
- **Workspace-scoped COMPUTE execution with deny-by-default network**
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

## Remote executor R1

The public Control Plane and the executor are deliberately separate trust domains.

```text
Control Plane / Control Room
        |
        | HTTPS + HMAC signed request
        v
CASTER-MINAL executor service
        |
        | bounded workspace_id
        v
Linux namespace/chroot runner
        |
        v
signed execution receipt
        |
        v
independent verification (separate)
```

The R1 bridge accepts **COMPUTE only**. WRITE, REMOTE_WRITE, DEPLOY, DESTRUCTIVE and PRIVILEGED requests fail closed. Remote plaintext HTTP is refused; it is allowed only on localhost for development. Replay nonces persist in SQLite across executor restarts.

See [`docs/EXECUTOR_R1.md`](docs/EXECUTOR_R1.md) for setup, systemd packaging and security boundaries.

## Reality boundary

v0.4 provides a real networked executor service/client protocol and can drive the existing Linux namespace/chroot runner on a compatible Linux host. The Vercel Control Plane itself still cannot provide kernel namespace isolation, so execution belongs on a separate Linux executor host.

The public browser Control Room does **not** receive executor secrets. Server-side remote execution requires `VOODOO_CONTROL_API_TOKEN`, a configured executor URL/secret, and a locally recorded `VERIFIED_PLAN`. Current Vercel run/plan state is ephemeral, so durable multi-instance plan/evidence storage and user/session identity remain production-hardening work before browser-driven execution should be considered resilient.
