import tempfile,unittest
from pathlib import Path
from voodoo_skillset.workspace import CaserWorkspace,Zone
from voodoo_skillset.execution import DryRunExecutor,ExecutionEnvelope,NetworkPolicy,RunStore,run_record
class WorkspaceExecutionTests(unittest.TestCase):
 def test_workspace_zones(self):
  with tempfile.TemporaryDirectory() as d:
   w=CaserWorkspace(d); paths=w.initialize(); self.assertTrue(paths.vault.is_dir()); p=w.write(Zone.WORKSPACE,'a/b.txt','x'); self.assertEqual(p.read_text(),'x')
 def test_workspace_escape_denied(self):
  with tempfile.TemporaryDirectory() as d:
   w=CaserWorkspace(d); w.initialize()
   with self.assertRaises(ValueError): w.resolve(Zone.WORKSPACE,'../../escape')
 def test_vault_overwrite_denied(self):
  with tempfile.TemporaryDirectory() as d:
   w=CaserWorkspace(d); w.initialize(); w.write(Zone.VAULT,'evidence.txt','v1')
   with self.assertRaises(FileExistsError): w.write(Zone.VAULT,'evidence.txt','v2',overwrite=True)
 def test_network_default_deny(self):
  p=NetworkPolicy(); self.assertFalse(p.allows('example.com'))
 def test_network_explicit_allow(self):
  p=NetworkPolicy(allowed_hosts=('api.github.com',)); self.assertTrue(p.allows('api.github.com')); self.assertFalse(p.allows('evil.example'))
 def test_dry_run_no_effect(self):
  with tempfile.TemporaryDirectory() as d:
   e=ExecutionEnvelope.local_reference(d); out=DryRunExecutor().execute('x',{},e); self.assertEqual(out['effect'],'NONE'); self.assertEqual(out['status'],'SIMULATED')
 def test_run_store(self):
  with tempfile.TemporaryDirectory() as d:
   r=RunStore(Path(d)/'runs.jsonl'); r.append(run_record('p','PLANNED')); self.assertEqual(len(r.list()),1)

class NamespaceSandboxTests(unittest.TestCase):
 def test_namespace_sandbox_denies_network_and_host_filesystem(self):
  from voodoo_skillset.execution import LinuxNamespaceExecutor
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/'src').mkdir(); (root/'marker.txt').write_text('inside')
   runner=LinuxNamespaceExecutor(); ok,_=runner.available()
   if not ok: self.skipTest('linux namespace isolation unavailable')
   script=(
    "import os,socket,pathlib; "
    "print('marker='+pathlib.Path('marker.txt').read_text()); "
    "print('host_mnt='+str(pathlib.Path('/mnt/data').exists())); "
    "s=socket.socket(); s.settimeout(.2); "
    "\ntry: s.connect(('1.1.1.1',53)); print('network=OPEN')\n"
    "except OSError: print('network=DENIED')"
   )
   out=runner.execute('sandbox-smoke',{'argv':['python3','-c',script]},ExecutionEnvelope.local_reference(root))
   self.assertEqual(out['exit_code'],0,out['stderr'])
   self.assertIn('marker=inside',out['stdout'])
   self.assertIn('host_mnt=False',out['stdout'])
   self.assertIn('network=DENIED',out['stdout'])
   self.assertEqual(out['persistent_effect'],'NONE')
   self.assertEqual(out['verification_status'],'UNKNOWN')

 def test_namespace_sandbox_changes_are_ephemeral(self):
  from voodoo_skillset.execution import LinuxNamespaceExecutor
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/'base.txt').write_text('v1')
   runner=LinuxNamespaceExecutor(); ok,_=runner.available()
   if not ok: self.skipTest('linux namespace isolation unavailable')
   out=runner.execute('sandbox-write',{'argv':['python3','-c',"open('new.txt','w').write('x')"]},ExecutionEnvelope.local_reference(root))
   self.assertEqual(out['exit_code'],0,out['stderr'])
   self.assertIn('new.txt',out['staged_changes'])
   self.assertFalse((root/'new.txt').exists())

 def test_namespace_sandbox_rejects_egress_allowlist(self):
  from voodoo_skillset.execution import LinuxNamespaceExecutor
  with tempfile.TemporaryDirectory() as d:
   runner=LinuxNamespaceExecutor(); ok,_=runner.available()
   if not ok: self.skipTest('linux namespace isolation unavailable')
   with self.assertRaises(PermissionError):
    runner.execute('x',{'argv':['python3','-c','print(1)']},ExecutionEnvelope.local_reference(d,allowed_hosts=('api.github.com',)))
