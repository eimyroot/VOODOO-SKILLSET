import json,tempfile,unittest
from pathlib import Path
from voodoo_skillset.intent import classify_intent
from voodoo_skillset.registry import CapabilityRegistry
from voodoo_skillset.models import Mode,RuntimeManifest
from voodoo_skillset.orchestrator import Orchestrator
from voodoo_skillset.evidence import EvidenceLedger
from voodoo_skillset.verifier import verify_plan
ROOT=Path(__file__).resolve().parents[1]
class CoreTests(unittest.TestCase):
 def setUp(self): self.reg=CapabilityRegistry.from_path(ROOT/'registry/capabilities.json')
 def runtime(self): return RuntimeManifest(('web-search','filesystem-write','test-runner','isolated-runner'),('github',),())
 def test_registry_unique(self): self.assertGreaterEqual(len(self.reg.all()),15)
 def test_intent_write(self): self.assertTrue(classify_intent('implement fixes').write_intent)
 def test_intent_plain_audit_no_write(self): self.assertFalse(classify_intent('audit github repo').write_intent)
 def test_all_is_selective(self): self.assertLess(len(Orchestrator(self.reg).plan('audit github repo security implement fixes test and verify',Mode.ALL,self.runtime()).selections),len(self.reg.all()))
 def test_all_requires_verifier(self): self.assertIn('independent-verifier',[x.capability_id for x in Orchestrator(self.reg).plan('audit github repo security implement fixes test and verify',Mode.ALL,self.runtime()).selections])
 def test_implement_before_test(self):
  p=Orchestrator(self.reg).plan('implement web ui test and verify',Mode.ALL,self.runtime()); where={x:i for i,s in enumerate(p.stages) for x in s}; self.assertLess(where['implementer'],where['test-engineer'])
 def test_verifier_after_workers(self):
  p=Orchestrator(self.reg).plan('implement web ui test and verify',Mode.ALL,self.runtime()); where={x:i for i,s in enumerate(p.stages) for x in s}; self.assertGreater(where['independent-verifier'],where['test-engineer'])
 def test_missing_runtime_required_blocks(self): self.assertEqual(Orchestrator(self.reg).plan('implement and test',Mode.ALL,RuntimeManifest()).status,'BLOCKED')
 def test_plan_verifies(self):
  p=Orchestrator(self.reg).plan('audit github repo security implement fixes test verify',Mode.ALL,self.runtime()); ok,problems=verify_plan(p,True); self.assertTrue(ok,problems)
 def test_github_write_not_auto_allowed(self):
  p=Orchestrator(self.reg).plan('audit github repository',Mode.PRO,self.runtime()); self.assertNotIn('github-write-plugin',{g['capability_id']:g for g in p.authority_gates})
 def test_evidence_chain(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'ledger.json'; l=EvidenceLedger(path); l.append('A','x',{'a':1}); l.append('B','y',{'b':2}); self.assertEqual(l.verify(),(True,'PASS'))
 def test_evidence_tamper_detected(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'ledger.json'; l=EvidenceLedger(path); l.append('A','x',{'a':1}); raw=json.loads(path.read_text()); raw[0]['payload']['a']=2; path.write_text(json.dumps(raw)); self.assertFalse(EvidenceLedger(path).verify()[0])
