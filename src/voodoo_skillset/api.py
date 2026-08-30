import json,mimetypes
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse
from .execution import RunStore,run_record
from .learning import LearningStore
from .models import Mode,RuntimeManifest
from .observability import Metrics
from .orchestrator import Orchestrator
from .registry import CapabilityRegistry
class App:
    def __init__(self,repo_root):
        self.repo_root=repo_root; self.registry=CapabilityRegistry.from_path(repo_root/'registry/capabilities.json'); self.orchestrator=Orchestrator(self.registry,LearningStore(repo_root/'evidence/learning.json')); self.runtime=RuntimeManifest(('web-search','filesystem-write','test-runner','isolated-runner'),('github',)); self.runs=RunStore(repo_root/'evidence/runs.jsonl'); self.metrics=Metrics()
    def health(self): return {'status':'ok','service':'voodoo-skillset','version':'0.2.0','trust_model':'fail-closed','capabilities':len(self.registry.all())}
    def capabilities(self): return [asdict(c) for c in self.registry.all()]
    def runtime_status(self): return {'tools':list(self.runtime.tools),'connectors':list(self.runtime.connectors),'standing_grants':list(self.runtime.standing_grants),'network_default':'DENY','production_mutation':'BLOCKED_BY_DEFAULT'}
    def plan(self,payload):
        mode=Mode(payload.get('mode','ALL').upper()); rt=RuntimeManifest(tuple(payload.get('tools',self.runtime.tools)),tuple(payload.get('connectors',self.runtime.connectors)),tuple(payload.get('standing_grants',()))); self.metrics.inc('plans_requested'); plan=self.orchestrator.plan(payload['goal'],mode,rt,set(payload.get('exclude',()))) ; self.runs.append(run_record(plan.plan_id,'PLANNED',{'plan_status':plan.status,'mode':plan.mode})); self.metrics.inc('plans_blocked' if plan.status=='BLOCKED' else 'plans_verified'); return plan.to_dict()
def handler_factory(app):
    class Handler(BaseHTTPRequestHandler):
        def _json(self,data,status=200):
            body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            path=urlparse(self.path).path
            if path=='/api/health': return self._json(app.health())
            if path=='/api/capabilities': return self._json(app.capabilities())
            if path=='/api/runtime': return self._json(app.runtime_status())
            if path=='/api/runs': return self._json(app.runs.list())
            if path=='/api/metrics': return self._json(app.metrics.snapshot())
            rel='index.html' if path in {'/',''} else path.lstrip('/'); file=(app.repo_root/'web'/rel).resolve(); web=(app.repo_root/'web').resolve()
            if not str(file).startswith(str(web)) or not file.exists() or not file.is_file(): return self._json({'error':'not found'},404)
            body=file.read_bytes(); self.send_response(200); self.send_header('Content-Type',mimetypes.guess_type(str(file))[0] or 'application/octet-stream'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            if urlparse(self.path).path!='/api/plan': return self._json({'error':'not found'},404)
            try:
                n=int(self.headers.get('Content-Length','0')); payload=json.loads(self.rfile.read(n) or b'{}')
                if not isinstance(payload.get('goal'),str) or not payload['goal'].strip(): raise ValueError('goal is required')
                return self._json(app.plan(payload))
            except (ValueError,KeyError,json.JSONDecodeError) as exc: return self._json({'error':str(exc)},400)
        def log_message(self,fmt,*args): pass
    return Handler
def serve(repo_root,host='127.0.0.1',port=8787):
    app=App(repo_root); server=ThreadingHTTPServer((host,port),handler_factory(app)); print(f'VOODOO-SKILLSET http://{host}:{port}'); server.serve_forever()
