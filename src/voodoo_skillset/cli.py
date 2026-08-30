import argparse,json,os
from pathlib import Path
from .api import serve
from .evidence import EvidenceLedger
from .executor_bridge import ExecutionRequest, RemoteExecutorClient, serve_executor
from .learning import LearningStore
from .models import Mode,ExecutionPlan,Selection
from .orchestrator import Orchestrator
from .registry import CapabilityRegistry
from .runtime import load_runtime_manifest
from .verifier import verify_plan

def repo_root(): return Path(__file__).resolve().parents[2]
def registry(): return CapabilityRegistry.from_path(repo_root()/'registry/capabilities.json')
def plan_from_dict(d):
    d=dict(d); d['selections']=[Selection(**x) for x in d['selections']]; d['io_capabilities']=[Selection(**x) for x in d['io_capabilities']]; return ExecutionPlan(**d)
def _secret_from_env(name):
    value=os.environ.get(name,'')
    if not value: raise SystemExit(f'{name} is required')
    return value

def main(argv=None):
    p=argparse.ArgumentParser(prog='voodoo-skillset'); s=p.add_subparsers(dest='cmd',required=True)
    i=s.add_parser('inspect'); i.add_argument('capability_id',nargs='?')
    pl=s.add_parser('plan'); pl.add_argument('goal'); pl.add_argument('--mode',choices=[x.value for x in Mode],default='ALL'); pl.add_argument('--runtime-manifest'); pl.add_argument('--tool',action='append',default=[]); pl.add_argument('--connector',action='append',default=[]); pl.add_argument('--grant',action='append',default=[]); pl.add_argument('--exclude',action='append',default=[]); pl.add_argument('--out'); pl.add_argument('--evidence')
    vp=s.add_parser('verify-plan'); vp.add_argument('path'); vp.add_argument('--require-verifier',action='store_true')
    ve=s.add_parser('verify-evidence'); ve.add_argument('path')
    sv=s.add_parser('serve'); sv.add_argument('--host',default='127.0.0.1'); sv.add_argument('--port',type=int,default=8787)
    es=s.add_parser('executor-serve'); es.add_argument('--host',default='127.0.0.1'); es.add_argument('--port',type=int,default=8790); es.add_argument('--workspace-root',required=True); es.add_argument('--secret-env',default='VOODOO_EXECUTOR_SHARED_SECRET')
    ec=s.add_parser('executor-check'); ec.add_argument('--url',default=None); ec.add_argument('--secret-env',default='VOODOO_EXECUTOR_SHARED_SECRET')
    er=s.add_parser('executor-run'); er.add_argument('workspace_id'); er.add_argument('--plan-id',required=True); er.add_argument('--capability-id',default='governed-terminal'); er.add_argument('--cwd',default='.'); er.add_argument('--url',default=None); er.add_argument('--secret-env',default='VOODOO_EXECUTOR_SHARED_SECRET'); er.add_argument('argv',nargs=argparse.REMAINDER)
    a=p.parse_args(argv)
    if a.cmd=='inspect': print(json.dumps([x.__dict__ for x in registry().all()] if not a.capability_id else registry().get(a.capability_id).__dict__,indent=2)); return 0
    if a.cmd=='plan':
        rt=load_runtime_manifest(a.runtime_manifest,a.tool,a.connector,a.grant); plan=Orchestrator(registry(),LearningStore(repo_root()/'evidence/learning.json')).plan(a.goal,Mode(a.mode),rt,set(a.exclude)); rendered=json.dumps(plan.to_dict(),indent=2)
        if a.out: Path(a.out).write_text(rendered+'\n')
        else: print(rendered)
        if a.evidence:
            led=EvidenceLedger(a.evidence); led.append('PLAN','orchestrator',{'plan_id':plan.plan_id,'status':plan.status,'goal':plan.goal}); led.append('DAG','composer',{'stages':plan.stages}); led.append('AUTHORITY_GATES','policy',{'gates':plan.authority_gates}); led.append('PLAN_VERIFICATION','independent-verifier',{'status':plan.status})
        return 0 if plan.status=='VERIFIED_PLAN' else 2
    if a.cmd=='verify-plan':
        ok,problems=verify_plan(plan_from_dict(json.loads(Path(a.path).read_text())),a.require_verifier); print(json.dumps({'status':'PASS' if ok else 'FAIL','problems':problems},indent=2)); return 0 if ok else 2
    if a.cmd=='verify-evidence':
        ok,reason=EvidenceLedger(a.path).verify(); print(json.dumps({'status':'PASS' if ok else 'FAIL','reason':reason},indent=2)); return 0 if ok else 2
    if a.cmd=='serve': serve(repo_root(),a.host,a.port); return 0
    if a.cmd=='executor-serve':
        serve_executor(Path(a.workspace_root),_secret_from_env(a.secret_env),host=a.host,port=a.port); return 0
    if a.cmd=='executor-check':
        url=a.url or os.environ.get('VOODOO_EXECUTOR_URL','')
        if not url: raise SystemExit('VOODOO_EXECUTOR_URL or --url is required')
        out=RemoteExecutorClient(url,_secret_from_env(a.secret_env),timeout=5).health(); print(json.dumps(out,indent=2)); return 0 if out.get('execution')=='AVAILABLE' else 2
    if a.cmd=='executor-run':
        url=a.url or os.environ.get('VOODOO_EXECUTOR_URL','')
        if not url: raise SystemExit('VOODOO_EXECUTOR_URL or --url is required')
        argv=list(a.argv)
        if argv and argv[0]=='--': argv=argv[1:]
        if not argv: raise SystemExit('executor-run requires argv after --')
        req=ExecutionRequest.create(plan_id=a.plan_id,capability_id=a.capability_id,workspace_id=a.workspace_id,argv=argv,cwd=a.cwd,requested_by='operator-cli')
        out=RemoteExecutorClient(url,_secret_from_env(a.secret_env)).execute(req); print(json.dumps(out,indent=2)); return 0 if out['receipt']['result'].get('status')=='EXECUTED' else 2
    return 1
if __name__=='__main__': raise SystemExit(main())
