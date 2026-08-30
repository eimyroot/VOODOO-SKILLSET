#!/usr/bin/env bash
set -euo pipefail

ROOT=/tmp/voodoo-r3
WORKSPACES="$ROOT/workspaces"
DB="$ROOT/fleet.sqlite3"
CONTROL_LOG="$ROOT/control.log"
mkdir -p "$WORKSPACES/demo" "$ROOT/state"
printf 'canonical-source-workspace\n' > "$WORKSPACES/demo/marker.txt"

cleanup() {
  if [ -f "$ROOT/control.pid" ]; then
    kill "$(cat "$ROOT/control.pid")" 2>/dev/null || true
  fi
  echo '--- control log ---'
  tail -150 "$CONTROL_LOG" 2>/dev/null || true
}
trap cleanup EXIT

docker pull --quiet python:3.12-slim
IMAGE="$(docker image inspect python:3.12-slim --format '{{index .RepoDigests 0}}')"
python3 - "$IMAGE" <<'PY'
import re,sys
image=sys.argv[1]
assert re.fullmatch(r'[^\s@]+(?:/[^\s@]+)*@sha256:[0-9a-f]{64}', image), image
print('PINNED_EXECUTOR_IMAGE='+image)
PY

SECRET="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
CONTROL="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
WORKER="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
VERIFIER="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
for value in "$SECRET" "$CONTROL" "$WORKER" "$VERIFIER"; do
  echo "::add-mask::$value"
done

# Only the coordinator receives the DB path and all authorization boundaries.
env \
  PYTHONPATH=src \
  VOODOO_FLEET_DB="$DB" \
  VOODOO_EXECUTOR_SHARED_SECRET="$SECRET" \
  VOODOO_CONTROL_API_TOKEN="$CONTROL" \
  VOODOO_FLEET_WORKER_TOKEN="$WORKER" \
  VOODOO_FLEET_VERIFIER_TOKEN="$VERIFIER" \
  nohup python3 -m voodoo_skillset.cli serve --host 127.0.0.1 --port 8787 \
  >"$CONTROL_LOG" 2>&1 &
echo $! > "$ROOT/control.pid"

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8787/api/fleet >"$ROOT/fleet-health.json"; then break; fi
  sleep 0.25
done
cat "$ROOT/fleet-health.json"
python3 - "$ROOT/fleet-health.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d['status']=='AVAILABLE',d
assert d['execution']=='AVAILABLE',d
assert d['backend']=='sqlite-durable-reference',d
assert d['event_chain']=='VERIFIED',d
assert d['database_secret_exposed_to_workers'] is False,d
print('FLEET_COORDINATOR=PASS')
PY

# Plan + enqueue are Control Plane authority only.
env PYTHONPATH=src VOODOO_CONTROL_API_TOKEN="$CONTROL" python3 - <<'PY'
import json,os,pathlib,sys,urllib.request
base='http://127.0.0.1:8787'
def post(path,payload,token=None):
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    req=urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers=headers,method='POST')
    with urllib.request.urlopen(req) as r: return json.load(r)
plan=post('/api/plan',{'goal':'audit repository security implement fixes test independently verify','mode':'ALL'})
assert plan['status']=='VERIFIED_PLAN',plan
assert plan['durable_record']=='RECORDED',plan
sys.path.insert(0,'src')
from voodoo_skillset.fleet import workspace_manifest_digest
root=pathlib.Path('/tmp/voodoo-r3/workspaces/demo')
before=workspace_manifest_digest(root)
control=os.environ['VOODOO_CONTROL_API_TOKEN']
script_template='''import os,pathlib,socket,time\ntime.sleep(1.2)\nprint("JOB_LABEL")\nprint("marker="+pathlib.Path("marker.txt").read_text().strip())\nprint("host_mnt="+str(pathlib.Path("/mnt/data").exists()))\nprint("docker_socket="+str(pathlib.Path("/var/run/docker.sock").exists()))\nprint("secret_env="+str("VOODOO_EXECUTOR_SHARED_SECRET" in os.environ))\npathlib.Path("EPHEMERAL_FILE").write_text("sandbox-only")\ntry:\n pathlib.Path("/etc/voodoo-write-probe").write_text("x"); print("root_write=OPEN")\nexcept OSError:\n print("root_write=DENIED")\ncapeff="UNKNOWN"\nfor line in pathlib.Path("/proc/self/status").read_text().splitlines():\n if line.startswith("CapEff:"): capeff=line.split(":",1)[1].strip()\nprint("cap_eff="+capeff)\ns=socket.socket(); s.settimeout(.3)\ntry:\n s.connect(("1.1.1.1",53)); print("network=OPEN")\nexcept OSError:\n print("network=DENIED")\n'''
jobs=[]
for i in range(4):
    label=f'fleet-job-{i}'
    script=script_template.replace('JOB_LABEL',label).replace('EPHEMERAL_FILE',f'ephemeral-{i}.txt')
    job=post('/api/fleet/jobs',{
        'plan_id':plan['plan_id'],
        'workspace_id':'demo',
        'capability_id':'test-engineer',
        'argv':['python3','-c',script],
        'workspace_before_sha256':before,
        'max_attempts':2,
        'verification_spec':{
            'expected_exit_code':0,
            'runner':'docker-container-v1',
            'persistent_effect':'NONE',
            'network_default':'DENY',
            'root_filesystem':'READ_ONLY',
            'capabilities':'ALL_DROPPED',
            'stdout_contains':[label,'marker=canonical-source-workspace','host_mnt=False','docker_socket=False','secret_env=False','root_write=DENIED','cap_eff=0000000000000000','network=DENIED'],
            'require_workspace_unchanged':True,
        },
    },control)
    assert job['state']=='QUEUED',job
    jobs.append(job['job_id'])
pathlib.Path('/tmp/voodoo-r3/job-ids.json').write_text(json.dumps(jobs))
print(json.dumps({'plan_id':plan['plan_id'],'jobs':jobs,'workspace_before_sha256':before},sort_keys=True))
PY

# Worker nodes get ONLY worker bearer + executor transport secret + sandbox config.
# They receive neither DB credentials/path, CONTROL token nor VERIFIER token.
WORKER_CODE='import sys; from voodoo_skillset.fleet_worker import worker_main; raise SystemExit(worker_main(sys.argv[1:]))'
env -u VOODOO_FLEET_DB -u VOODOO_CONTROL_API_TOKEN -u VOODOO_FLEET_VERIFIER_TOKEN \
  PYTHONPATH=src \
  VOODOO_FLEET_WORKER_TOKEN="$WORKER" \
  VOODOO_EXECUTOR_SHARED_SECRET="$SECRET" \
  VOODOO_EXECUTOR_CONTAINER_IMAGE="$IMAGE" \
  VOODOO_EXECUTOR_BACKEND=container \
  python3 -c "$WORKER_CODE" \
    --coordinator-url http://127.0.0.1:8787 \
    --workspace-root "$WORKSPACES" \
    --worker-id worker-a --drain --max-jobs 2 \
    >"$ROOT/worker-a.log" 2>&1 &
A_PID=$!

env -u VOODOO_FLEET_DB -u VOODOO_CONTROL_API_TOKEN -u VOODOO_FLEET_VERIFIER_TOKEN \
  PYTHONPATH=src \
  VOODOO_FLEET_WORKER_TOKEN="$WORKER" \
  VOODOO_EXECUTOR_SHARED_SECRET="$SECRET" \
  VOODOO_EXECUTOR_CONTAINER_IMAGE="$IMAGE" \
  VOODOO_EXECUTOR_BACKEND=container \
  python3 -c "$WORKER_CODE" \
    --coordinator-url http://127.0.0.1:8787 \
    --workspace-root "$WORKSPACES" \
    --worker-id worker-b --drain --max-jobs 2 \
    >"$ROOT/worker-b.log" 2>&1 &
B_PID=$!
wait "$A_PID" "$B_PID"
cat "$ROOT/worker-a.log"
cat "$ROOT/worker-b.log"
grep '"status": "EXECUTED"' "$ROOT/worker-a.log" >/dev/null
grep '"status": "EXECUTED"' "$ROOT/worker-b.log" >/dev/null

# Verifier receives ONLY verifier bearer. It gets no executor secret and no DB path.
VERIFY_CODE='import sys; from voodoo_skillset.fleet_worker import verifier_main; raise SystemExit(verifier_main(sys.argv[1:]))'
env -u VOODOO_FLEET_DB -u VOODOO_CONTROL_API_TOKEN -u VOODOO_FLEET_WORKER_TOKEN -u VOODOO_EXECUTOR_SHARED_SECRET \
  PYTHONPATH=src \
  VOODOO_FLEET_VERIFIER_TOKEN="$VERIFIER" \
  python3 -c "$VERIFY_CODE" \
    --coordinator-url http://127.0.0.1:8787 \
    --workspace-root "$WORKSPACES" \
    --verifier-id verifier-1 --drain --max-jobs 4 \
    >"$ROOT/verifier.log" 2>&1
cat "$ROOT/verifier.log"
test "$(grep -c '"status": "VERIFIED"' "$ROOT/verifier.log")" -eq 4

curl -fsS http://127.0.0.1:8787/api/fleet >"$ROOT/fleet-final.json"
cat "$ROOT/fleet-final.json"
PYTHONPATH=src python3 - <<'PY'
import json,pathlib,sqlite3
d=json.load(open('/tmp/voodoo-r3/fleet-final.json'))
counts=d['stats']['counts']
assert d['event_chain']=='VERIFIED',d
assert counts['VERIFIED']==4,counts
for state in ['QUEUED','LEASED','EXECUTED','VERIFYING','FAILED','BLOCKED']:
    assert counts[state]==0,(state,counts)
db=sqlite3.connect('/tmp/voodoo-r3/fleet.sqlite3'); db.row_factory=sqlite3.Row
rows=db.execute('select job_id,state,attempts,execution_worker_id,verifier_id from jobs order by job_id').fetchall()
assert len(rows)==4,rows
assert all(r['state']=='VERIFIED' and r['attempts']==1 for r in rows),[dict(r) for r in rows]
workers={r['execution_worker_id'] for r in rows}
assert workers=={'worker-a','worker-b'},workers
assert {r['verifier_id'] for r in rows}=={'verifier-1'},[dict(r) for r in rows]
workspace=pathlib.Path('/tmp/voodoo-r3/workspaces/demo')
assert not list(workspace.glob('ephemeral-*.txt')),list(workspace.glob('ephemeral-*.txt'))
from voodoo_skillset.fleet import DurableFleetStore
ok,reason=DurableFleetStore('/tmp/voodoo-r3/fleet.sqlite3').verify_event_chain()
assert ok,reason
print(json.dumps({
    'verdict':'PASS',
    'jobs':4,
    'workers':sorted(workers),
    'verifier':'verifier-1',
    'attempts_per_job':[r['attempts'] for r in rows],
    'final_state':'VERIFIED',
    'event_chain':'VERIFIED',
    'persistent_workspace_effect':'NONE',
    'database_credentials_on_workers':False,
    'control_token_on_workers':False,
    'verifier_token_on_workers':False,
    'executor_secret_on_verifier':False,
    'delivery_semantics':'exclusive active lease; retry-capable at-least-once',
},sort_keys=True))
PY

echo 'R3_REAL_FLEET=PASS'
