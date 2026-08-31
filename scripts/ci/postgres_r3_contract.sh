#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  docker rm -f voodoo-pg >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker pull --quiet postgres:17
PG_IMAGE="$(docker image inspect postgres:17 --format '{{index .RepoDigests 0}}')"
python3 - "$PG_IMAGE" <<'PY'
import re,sys
image=sys.argv[1]
assert re.fullmatch(r'[^\s@]+(?:/[^\s@]+)*@sha256:[0-9a-f]{64}', image), image
print('POSTGRES_IMAGE='+image)
PY

docker run -d --name voodoo-pg \
  -e POSTGRES_PASSWORD=postgres \
  "$PG_IMAGE" >/tmp/pg-container-id

READY=0
STABLE=0
for _ in $(seq 1 120); do
  RUNNING="$(docker inspect -f '{{.State.Running}}' voodoo-pg 2>/dev/null || echo false)"
  if [ "$RUNNING" != "true" ]; then
    echo 'FAIL: PostgreSQL container exited during startup'
    docker logs voodoo-pg || true
    exit 1
  fi
  if [ "$(docker exec voodoo-pg psql -X -qAt -U postgres -d postgres -c 'select 1' 2>/dev/null || true)" = "1" ]; then
    STABLE=$((STABLE + 1))
    if [ "$STABLE" -ge 2 ]; then
      READY=1
      break
    fi
  else
    STABLE=0
  fi
  sleep 0.5
done
if [ "$READY" != "1" ]; then
  echo 'FAIL: PostgreSQL did not sustain two SQL readiness probes'
  docker inspect voodoo-pg || true
  docker logs voodoo-pg || true
  exit 1
fi
SQL_PROBE="$(docker exec voodoo-pg psql -X -qAt -U postgres -d postgres -c 'select 1')"
test "$SQL_PROBE" = "1"
echo 'POSTGRES_SQL_READY=PASS'

docker exec -i voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres <<'SQL'
create role service_role bypassrls noinherit;
create role anon noinherit;
create role authenticated noinherit;
SQL

docker exec -i voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres < supabase/migrations/20260830_r3_executor_fleet.sql
docker exec -i voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres < supabase/migrations/20260830_r3_executor_fleet_privileges.sql
docker exec -i voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres < supabase/migrations/20260831_r4_fleet_security_hardening.sql
docker exec -i voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres < supabase/migrations/20260831_r4_pgcrypto_schema_parity.sql
docker exec -i voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres < supabase/migrations/20260831_r4_plan_fk_index.sql

MUTABLE_PATHS="$(docker exec voodoo-pg psql -X -qAt -v ON_ERROR_STOP=1 -U postgres -c \
  "select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname like 'voodoo_%' and not exists (select 1 from unnest(coalesce(p.proconfig,'{}'::text[])) cfg where cfg='search_path=pg_catalog, public, extensions');")"
test "$MUTABLE_PATHS" = "0"
echo 'POSTGRES_FIXED_SEARCH_PATH=PASS'

PLAN_INDEX="$(docker exec voodoo-pg psql -X -qAt -v ON_ERROR_STOP=1 -U postgres -c \
  "select count(*) from pg_indexes where schemaname='public' and tablename='voodoo_jobs' and indexname='voodoo_jobs_plan_id_idx' and indexdef ~ '\\(plan_id\\)';")"
test "$PLAN_INDEX" = "1"
echo 'POSTGRES_PLAN_FK_INDEX=PASS'

docker exec -i voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres <<'SQL'
set role service_role;
select public.voodoo_record_plan('{"plan_id":"PLAN-PG","status":"VERIFIED_PLAN","goal":"r4 postgres","mode":"ALL"}'::jsonb);
select public.voodoo_enqueue_job(
  'PLAN-PG','demo','test-engineer','["python3","-c","print(1)"]'::jsonb,'.',
  '{"expected_exit_code":0}'::jsonb,null,100,3,'JOB-PG-1'
);
select public.voodoo_enqueue_job(
  'PLAN-PG','demo','test-engineer','["python3","-c","print(2)"]'::jsonb,'.',
  '{"expected_exit_code":0}'::jsonb,null,100,3,'JOB-PG-2'
);
SQL

if docker exec voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres \
  -c "set role service_role; update public.voodoo_jobs set priority=999 where job_id='JOB-PG-1';" >/tmp/direct-write.out 2>/tmp/direct-write.err; then
  echo 'FAIL: service_role unexpectedly updated voodoo_jobs directly'
  cat /tmp/direct-write.out
  exit 1
fi
grep -Ei 'permission denied|privilege' /tmp/direct-write.err >/dev/null

if docker exec voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres \
  -c "set role service_role; delete from public.voodoo_fleet_events;" >/tmp/direct-delete.out 2>/tmp/direct-delete.err; then
  echo 'FAIL: service_role unexpectedly deleted append-only fleet events'
  cat /tmp/direct-delete.out
  exit 1
fi
grep -Ei 'permission denied|privilege' /tmp/direct-delete.err >/dev/null

echo 'POSTGRES_GOVERNED_MUTATION_ONLY=PASS'

docker exec voodoo-pg psql -X -qAt -v ON_ERROR_STOP=1 -U postgres \
  -c "set role service_role; select public.voodoo_claim_execution('worker-a',30)::text;" \
  >/tmp/claim-a.json &
A_PID=$!
docker exec voodoo-pg psql -X -qAt -v ON_ERROR_STOP=1 -U postgres \
  -c "set role service_role; select public.voodoo_claim_execution('worker-b',30)::text;" \
  >/tmp/claim-b.json &
B_PID=$!
wait "$A_PID" "$B_PID"

cat /tmp/claim-a.json
cat /tmp/claim-b.json
python3 - <<'PY'
import json
a=json.loads(open('/tmp/claim-a.json').read())
b=json.loads(open('/tmp/claim-b.json').read())
assert a['job_id'] != b['job_id'], (a,b)
assert {a['job_id'],b['job_id']} == {'JOB-PG-1','JOB-PG-2'}, (a,b)
assert a['lease_token'] and b['lease_token'] and a['lease_token'] != b['lease_token']
assert 'execution_lease_hash' not in a and 'execution_lease_hash' not in b
print('POSTGRES_ATOMIC_CLAIMS=PASS')
PY

if docker exec voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres \
  -c "set role anon; select count(*) from public.voodoo_jobs;" >/tmp/anon.out 2>/tmp/anon.err; then
  echo 'FAIL: anon unexpectedly read voodoo_jobs'
  cat /tmp/anon.out
  exit 1
fi
grep -Ei 'permission denied|privilege' /tmp/anon.err >/dev/null

if docker exec voodoo-pg psql -v ON_ERROR_STOP=1 -U postgres \
  -c "set role authenticated; select public.voodoo_claim_execution('rogue-client',30);" >/tmp/auth.out 2>/tmp/auth.err; then
  echo 'FAIL: authenticated role unexpectedly executed fleet claim RPC'
  cat /tmp/auth.out
  exit 1
fi
grep -Ei 'permission denied|privilege' /tmp/auth.err >/dev/null

docker exec voodoo-pg psql -X -qAt -v ON_ERROR_STOP=1 -U postgres \
  -c "set role service_role; select public.voodoo_verify_event_chain()::text;" >/tmp/chain.json
cat /tmp/chain.json
python3 - <<'PY'
import json
d=json.loads(open('/tmp/chain.json').read())
assert d['ok'] is True,d
assert d['event_count'] >= 5,d
print('POSTGRES_EVENT_CHAIN=PASS')
PY

echo 'R4_POSTGRES_SECURITY_CONTRACT=PASS'
