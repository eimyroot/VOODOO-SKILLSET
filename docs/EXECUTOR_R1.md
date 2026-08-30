# CASTER-MINAL Executor Bridge R1

VOODOO-SKILLSET separates the public/control-plane runtime from the machine that is allowed to execute COMPUTE operations.

```text
Control Room / API (Vercel)
        |
        | signed executor-v1 request (HTTPS)
        v
CASTER-MINAL executor service (Linux)
        |
        | workspace_id -> bounded CASER workspace
        v
LinuxNamespaceExecutor
user + mount + net + pid namespaces
chroot staged copy, DENY network, ephemeral effects
        |
        v
signed execution receipt
verification_status = UNKNOWN
        |
        v
Control plane evidence ledger
        |
        v
Independent verifier (separate step)
```

## Security properties

- `PROJECT IDENTITY != EXECUTION AUTHORITY`.
- R1 remote protocol authorizes **COMPUTE only**. WRITE, REMOTE_WRITE, DEPLOY, DESTRUCTIVE and PRIVILEGED are not accepted by the executor bridge.
- Requests and receipts are HMAC-SHA256 signed with a minimum 32-byte shared secret.
- Remote plaintext HTTP is refused; HTTP is allowed only for localhost development. Production must use HTTPS/TLS termination.
- Request TTL is at most 120 seconds with a 5 second future clock-skew allowance.
- Replay nonces are stored in SQLite with a UNIQUE constraint, so replay remains blocked across executor restarts.
- A request names `workspace_id`, never an arbitrary filesystem path. Workspace IDs are resolved directly beneath the configured executor workspace root.
- `cwd` must remain relative to that workspace.
- Network policy is fixed to `DENY`; any allowlist fails closed until a governed egress broker exists.
- Shell/privileged wrapper blocking and Linux namespace/chroot constraints remain enforced by `LinuxNamespaceExecutor`.
- An execution receipt is **not** independent verification. R1 returns `verification_status=UNKNOWN` unless a later verifier proves the outcome.

## Required secrets

Executor host:

```bash
export VOODOO_EXECUTOR_SHARED_SECRET='<random 32+ byte secret>'
```

Control plane:

```bash
export VOODOO_EXECUTOR_URL='https://executor.example.com'
export VOODOO_EXECUTOR_SHARED_SECRET='<same executor transport secret>'
export VOODOO_CONTROL_API_TOKEN='<separate bearer token for server-side execution API>'
```

Do not embed either secret in browser JavaScript. The Control Room may display executor health, but a trusted server-side/session identity layer must authorize execution.

## Run the executor

Prepare CASER workspaces:

```text
/srv/voodoo/workspaces/
├── repo-a/
├── repo-b/
└── job-123/
```

Then:

```bash
VOODOO_EXECUTOR_SHARED_SECRET='...' \
voodoo-skillset executor-serve \
  --workspace-root /srv/voodoo/workspaces \
  --host 127.0.0.1 \
  --port 8790
```

Probe it locally:

```bash
VOODOO_EXECUTOR_URL=http://127.0.0.1:8790 \
VOODOO_EXECUTOR_SHARED_SECRET='...' \
voodoo-skillset executor-check
```

For remote use, place TLS termination/reverse proxy in front of `127.0.0.1:8790` and configure the control plane with an `https://` executor URL.

## Trusted operator smoke execution

The operator CLI intentionally requires a plan id and direct access to the executor transport secret:

```bash
voodoo-skillset executor-run repo-a \
  --plan-id PLAN-0123456789ab \
  --capability-id test-engineer \
  -- \
  python3 -m unittest discover -s tests -v
```

The result is a signed **execution receipt**, not a PASS verdict.

## Control-plane execution API

The control plane exposes:

```text
GET  /api/executor
POST /api/executor/execute
```

`POST /api/executor/execute` requires:

```http
Authorization: Bearer <VOODOO_CONTROL_API_TOKEN>
```

and a locally recorded `VERIFIED_PLAN`. If the plan is missing, executor configuration is incomplete, the executor is unreachable, the receipt signature is invalid, or the request is outside R1 policy, execution fails closed.

Current Vercel state storage is ephemeral. A production multi-instance control plane therefore still needs a durable plan/evidence store before browser-driven execution can be considered resilient. The execution API deliberately blocks when its local verified-plan record is absent.
