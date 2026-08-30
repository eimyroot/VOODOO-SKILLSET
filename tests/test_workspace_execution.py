import tempfile,unittest
from pathlib import Path
from voodoo_skillset.workspace import CaserWorkspace,Zone
from voodoo_skillset.execution import DryRunExecutor,ExecutionEnvelope,NetworkPolicy,RunStore,run_record
class WorkspaceExecutionTests(unittest.TestCase):
 def test_workspace_zones(self):
  with tempfile.TemporaryDirectory() as d:
   w=CaserWorkspace(d); paths=w.initialize(); self.assertTrue(paths.vault.is_dir()); self.assertEqual(w.write(Zone.WORKSPACE,'a/b.txt','x').read_text(),'x')
 def test_workspace_escape_denied(self):
  with tempfile.TemporaryDirectory() as d:
   w=CaserWorkspace(d); w.initialize()
   with self.assertRaises(ValueError): w.resolve(Zone.WORKSPACE,'../../escape')
 def test_vault_overwrite_denied(self):
  with tempfile.TemporaryDirectory() as d:
   w=CaserWorkspace(d); w.initialize(); w.write(Zone.VAULT,'evidence.txt','v1')
   with self.assertRaises(FileExistsError): w.write(Zone.VAULT,'evidence.txt','v2',overwrite=True)
 def test_network_default_deny(self): self.assertFalse(NetworkPolicy().allows('example.com'))
 def test_network_explicit_allow(self):
  p=NetworkPolicy(allowed_hosts=('api.github.com',)); self.assertTrue(p.allows('api.github.com')); self.assertFalse(p.allows('evil.example'))
 def test_dry_run_no_effect(self):
  with tempfile.TemporaryDirectory() as d:
   out=DryRunExecutor().execute('x',{},ExecutionEnvelope.local_reference(d)); self.assertEqual(out['effect'],'NONE'); self.assertEqual(out['status'],'SIMULATED')
 def test_run_store(self):
  with tempfile.TemporaryDirectory() as d:
   r=RunStore(Path(d)/'runs.jsonl'); r.append(run_record('p','PLANNED')); self.assertEqual(len(r.list()),1)
