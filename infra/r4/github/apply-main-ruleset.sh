#!/usr/bin/env bash
set -euo pipefail

: "${GH_ADMIN_TOKEN:?GH_ADMIN_TOKEN is required (fine-grained token with repository Administration: write)}"
REPO="eimyroot/VOODOO-SKILLSET"
API="https://api.github.com/repos/${REPO}/rulesets"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD="${HERE}/main-ruleset.json"

existing="$(curl -fsS \
  -H "Authorization: Bearer ${GH_ADMIN_TOKEN}" \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  "${API}")"

count="$(python3 -c 'import json,sys; print(sum(1 for x in json.load(sys.stdin) if x.get("name")=="main-governance"))' <<<"${existing}")"
if [[ "${count}" != "0" ]]; then
  echo "BLOCKED: main-governance ruleset already exists; update it explicitly instead of creating a duplicate." >&2
  exit 2
fi

curl -fsS -X POST \
  -H "Authorization: Bearer ${GH_ADMIN_TOKEN}" \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  -H 'Content-Type: application/json' \
  --data-binary "@${PAYLOAD}" \
  "${API}" >/tmp/voodoo-main-ruleset.json

python3 - <<'PY'
import json
p='/tmp/voodoo-main-ruleset.json'
d=json.load(open(p))
assert d.get('name')=='main-governance', d
assert d.get('enforcement')=='active', d
print('MAIN_RULESET_APPLY=PASS id='+str(d.get('id')))
PY
