# Contributing

VOODOO-SKILLSET is governance-first software. Changes are expected to preserve explicit authority boundaries, fail-closed semantics and verifiable evidence.

## Local workflow

```bash
git clone https://github.com/eimyroot/VOODOO-SKILLSET.git
cd VOODOO-SKILLSET
make verify
```

Run the browser cockpit:

```bash
make cockpit
```

## Change rules

1. Keep runtime implementation under `src/voodoo_skillset/`.
2. Keep hosting adapters thin; `api/` must not become a second implementation of trust logic.
3. Do not weaken `UNKNOWN != PASS`, independent verification, credential separation or deny-by-default execution/network rules.
4. Add or update tests for every behavioral change.
5. Update architecture/security documentation when a trust boundary changes.
6. Never commit secrets, tokens, private keys, local databases or generated runtime evidence.
7. Prefer one scoped branch and one reviewable pull request per logical change.

## Verification gates

The default CI contract includes:

- Python compile checks
- JavaScript syntax validation
- the full `unittest` suite on Python 3.12 and 3.13
- CLI governed-plan smoke verification
- browser cockpit HTTP smoke verification
- repository/front-page contract tests

A green CI result is necessary but does not automatically prove production readiness. Live infrastructure claims require their own evidence.

## Commit style

Use concise Conventional Commit-style subjects where practical:

```text
feat: add ...
fix: prevent ...
test: prove ...
docs: explain ...
ops: add ...
chore: clean ...
```

## Pull request checklist

- [ ] Scope is explicit and bounded.
- [ ] Trust/authority impact is described.
- [ ] Tests cover the changed behavior.
- [ ] Documentation matches executable reality.
- [ ] No secret or generated-state leakage.
- [ ] Rollback is straightforward.
- [ ] CI is green on the exact PR head.
