import tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from voodoo_skillset.governed_terminal import AuthorizationGrant,classify,execute,grant_allows,parse_command
from voodoo_skillset.intent import classify_intent
from voodoo_skillset.models import Capability,RuntimeManifest
from voodoo_skillset.policy import authority_gate
class PolicyTerminalTests(unittest.TestCase):
 def test_git_status_read(self): self.assertEqual(classify(parse_command('git status --short')).classification,'READ_ONLY')
 def test_git_commit_write(self): self.assertEqual(classify(parse_command('git commit -m x')).classification,'REPO_WRITE')
 def test_git_push_remote(self): self.assertEqual(classify(parse_command('git push origin main')).classification,'REMOTE_WRITE')
 def test_shell_wrapper_blocked(self): self.assertEqual(classify(parse_command('bash script.sh')).classification,'BLOCKED')
 def test_chaining_blocked(self):
  with self.assertRaises(ValueError): parse_command('git status && git push')
 def test_unknown_blocked(self): self.assertEqual(classify(parse_command('mystery-tool x')).classification,'BLOCKED')
 def test_compute_without_isolation_blocked(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(PermissionError): execute('python -c pass',Path(d))
 def test_receipt_unknown_not_verified(self):
  with tempfile.TemporaryDirectory() as d: self.assertEqual(execute('pwd',Path(d))[1].verification_status,'UNKNOWN')
 def test_expired_grant(self):
  with tempfile.TemporaryDirectory() as d:
   g=AuthorizationGrant('op',d,('REPO_WRITE',),(('git','apply'),),'USER',datetime.now(timezone.utc).isoformat(),(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),'n'); ok,reason=grant_allows(g,classify(parse_command('git apply x.patch')),Path(d)); self.assertFalse(ok); self.assertEqual(reason,'grant expired')
 def test_write_authority_needs_approval(self): self.assertEqual(authority_gate(Capability('w','agent','',('implement',),authority='WRITE'),classify_intent('implement fix'),RuntimeManifest()).decision,'APPROVAL_REQUIRED')
 def test_standing_write_grant(self): self.assertEqual(authority_gate(Capability('w','agent','',('implement',),authority='WRITE'),classify_intent('implement fix'),RuntimeManifest(standing_grants=('WRITE',))).decision,'ALLOW')
