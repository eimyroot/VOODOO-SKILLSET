import json,threading,unittest,urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from voodoo_skillset.api import App,handler_factory
ROOT=Path(__file__).resolve().parents[1]
class ApiTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls): cls.app=App(ROOT); cls.server=ThreadingHTTPServer(('127.0.0.1',0),handler_factory(cls.app)); cls.port=cls.server.server_address[1]; cls.t=threading.Thread(target=cls.server.serve_forever,daemon=True); cls.t.start()
 @classmethod
 def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()
 def get(self,path):
  with urllib.request.urlopen(f'http://127.0.0.1:{self.port}{path}') as r: return r.status,r.read().decode(),r.headers.get_content_type()
 def test_health(self):
  status,body,_=self.get('/api/health'); self.assertEqual(status,200); self.assertEqual(json.loads(body)['trust_model'],'fail-closed')
 def test_index(self):
  status,body,ctype=self.get('/'); self.assertEqual(status,200); self.assertIn('VOODOO',body); self.assertEqual(ctype,'text/html')
 def test_plan(self):
  data=json.dumps({'goal':'audit github repo security implement fixes test verify','mode':'ALL'}).encode(); req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/plan',data=data,headers={'Content-Type':'application/json'},method='POST')
  with urllib.request.urlopen(req) as r:
   d=json.loads(r.read()); self.assertEqual(d['status'],'VERIFIED_PLAN'); self.assertIn('independent-verifier',[x['capability_id'] for x in d['selections']])
