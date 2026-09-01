# Repository Hygiene Audit

Audit scope: canonical `main` at `78f0695ada64cd8024f374d6165b1175f413923c` plus the release-polish patch prepared from that exact head.

## Verdict

**PASS WITH EXPLICIT NON-BLOCKING LIMITATIONS**

The repository has a coherent product scaffold, real tests, explicit trust boundaries and a working zero-build browser cockpit. The release-polish patch closes the main presentation/operability gaps without changing executor or fleet semantics.

## Scaffold review

| Area | Status | Notes |
| --- | --- | --- |
| `src/` layout | PASS | Runtime implementation is isolated under `src/voodoo_skillset/`. |
| API adapter | PASS | `api/index.py` is a hosting adapter over the shared `App` runtime rather than a second control plane. |
| Browser cockpit | PASS | `web/` is zero-build static UI backed by real `/api/*` endpoints. |
| Tests | PASS | Unit/contract/runtime coverage exists across core, API, executor, fleet, policy and workspace behavior. |
| CI | PASS | Python 3.12/3.13, compile, JS syntax and governed CLI smoke are enforced; this patch adds cockpit HTTP smoke. |
| Capability registry | PASS | Registry is separated from orchestration/runtime implementation. |
| Infra/deploy | PASS | Production definitions and executor deployment examples are separated from application runtime. |
| Evidence boundary | PASS | Runtime evidence has a dedicated directory and generated local state is ignored. |
| Secret hygiene | PASS | `.gitignore` now excludes local env files, keys, databases, Vercel state and build/tool caches. |
| Documentation consistency | FIXED | `docs/ARCHITECTURE.md` was stale at a v0.2 isolation statement; it is aligned with the canonical v0.7 isolation/fleet model in this patch. |
| Contribution contract | FIXED | Added root contribution workflow and verification expectations. |
| Vulnerability reporting | FIXED | Added root security reporting policy. |
| Front-page presentation | FIXED | Added repository banner, EN-first product story, architecture and runnable cockpit entrypoint. |

## Architecture hygiene

The scaffold follows one primary rule: **trust semantics live in executable runtime code and tests, not in hosting glue or presentation files**.

```text
registry/schemas
      |
      v
src/voodoo_skillset
      |
      +---- api/ adapter
      +---- web/ cockpit
      +---- tools/ operator verification
      +---- tests/ executable contract
      |
      v
infra/ + deploy/
```

### Boundaries that should remain stable

- `api/` must remain a thin hosting adapter.
- `web/` must not receive control-plane/database/executor secrets.
- worker and verifier authority must remain separate.
- runtime evidence must not be used as source code/configuration authority.
- production provisioning must not be inferred from repository source presence.
- documentation must be updated whenever isolation, credential or verification semantics change.

## Explicit limitations

### 1. Repository license

There is no root `LICENSE` file. That is **not auto-fixed** because license selection is an ownership/legal decision. Until an explicit license is chosen, public source visibility should not be described as an open-source license grant.

### 2. GitHub repository metadata

At audit time the GitHub repository description field is empty. The source patch can make the README/front page representative, but repository metadata should also be set in GitHub settings when the relevant API/UI authority is available.

Recommended description:

> Governance-first control plane for composing, executing and independently verifying AI capabilities with fail-closed authority and evidence.

Recommended topics:

```text
ai-agents governance orchestration security control-plane verification evidence python devops
```

### 3. Production infrastructure

The repository contains production deployment contracts; it does not by itself prove that dedicated Supabase/Postgres, persistent Linux executor capacity, durable artifact transport or browser production authorization are currently provisioned.

## Release hygiene contract

Before merging a release-quality change:

```bash
make verify
```

Before claiming the cockpit is runnable, CI must additionally prove:

1. the HTTP server starts,
2. `/` serves the Control Room,
3. `/api/health` returns `status=ok`,
4. static JS passes syntax validation.

For production claims, require separate exact-SHA infrastructure evidence.
