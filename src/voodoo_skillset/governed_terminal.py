from __future__ import annotations
import hashlib,json,shlex,subprocess,uuid
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
POLICY={"read_only_commands":["pwd","ls","cat","head","tail","wc","stat","uname","whoami"],"compute_commands":["pytest","ruff","mypy","python","python3"],"blocked_commands":["sudo","su","doas","rm","shred","dd","mkfs","bash","sh","zsh","fish","eval","exec","env","printenv"],"git":{"read_only":["status","diff","log","show","rev-parse","ls-files","ls-tree","cat-file"],"repo_write":["add","apply","restore","checkout","switch","commit","merge","rebase","cherry-pick","reset","clean","stash","tag","fetch","pull"],"remote_write":["push"]},"deploy_executables":["vercel","terraform","kubectl","helm","aws","az","gcloud"],"forbidden_metacharacters":[";","&&","||","|",">","<","`","$("]}
@dataclass(frozen=True)
class CommandDecision: argv:tuple[str,...]; classification:str; reason:str; allowed_without_grant:bool
@dataclass(frozen=True)
class AuthorizationGrant: operation_id:str; target:str; allowed_classes:tuple[str,...]; allowed_prefixes:tuple[tuple[str,...],...]; authorized_by:str; issued_at:str; expires_at:str; nonce:str
@dataclass(frozen=True)
class ExecutionReceipt: receipt_version:int; receipt_id:str; operation_id:str; target:str; cwd:str; argv:tuple[str,...]; classification:str; command_sha256:str; runner:str; started_at:str; finished_at:str; exit_code:int; stdout_sha256:str; stderr_sha256:str; stdout_bytes:int; stderr_bytes:int; verification_status:str
def utc_now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha256_text(v): return hashlib.sha256(v.encode('utf-8',errors='replace')).hexdigest()
def parse_command(command):
    if not command.strip(): raise ValueError('empty command')
    if any(x in command for x in POLICY['forbidden_metacharacters']): raise ValueError('shell metacharacter/chaining is forbidden')
    argv=tuple(shlex.split(command,posix=True))
    if not argv: raise ValueError('empty argv')
    return argv
def classify(argv):
    argv=tuple(argv); exe=Path(argv[0]).name
    if exe in POLICY['blocked_commands']: return CommandDecision(argv,'BLOCKED',f'{exe} is hard-blocked',False)
    if exe=='git':
        if len(argv)<2: return CommandDecision(argv,'BLOCKED','git requires an explicit subcommand',False)
        sub=argv[1]
        if sub in POLICY['git']['read_only']: return CommandDecision(argv,'READ_ONLY',f'git {sub} is repository inspection',True)
        if sub in POLICY['git']['repo_write']: return CommandDecision(argv,'REPO_WRITE',f'git {sub} mutates local repository state',False)
        if sub in POLICY['git']['remote_write']: return CommandDecision(argv,'REMOTE_WRITE',f'git {sub} may mutate remote repository',False)
        return CommandDecision(argv,'BLOCKED',f'unknown git subcommand: {sub}',False)
    if exe in POLICY['read_only_commands']: return CommandDecision(argv,'READ_ONLY',f'{exe} is allowlisted for inspection',True)
    if exe in POLICY['compute_commands']: return CommandDecision(argv,'COMPUTE',f'{exe} executes code; isolated runner required',False)
    if exe in POLICY['deploy_executables']: return CommandDecision(argv,'DEPLOY',f'{exe} is classified as deployment/remote mutation',False)
    return CommandDecision(argv,'BLOCKED',f'executable not allowlisted: {exe}',False)
def _prefix_allowed(argv,prefixes): return any(len(p)<=len(argv) and argv[:len(p)]==p for p in prefixes)
def grant_allows(grant,decision,target,now=None):
    if decision.classification=='BLOCKED': return False,'blocked commands cannot be authorized'
    now=now or datetime.now(timezone.utc)
    try: expiry=datetime.fromisoformat(grant.expires_at.replace('Z','+00:00'))
    except ValueError: return False,'invalid grant expiry'
    if expiry.tzinfo is None: return False,'grant expiry must be timezone-aware'
    if now>=expiry: return False,'grant expired'
    if str(Path(grant.target).resolve())!=str(target.resolve()): return False,'grant target mismatch'
    if decision.classification not in grant.allowed_classes: return False,'operation class not granted'
    if not _prefix_allowed(decision.argv,grant.allowed_prefixes): return False,'command prefix not granted'
    return True,'grant matches target, class and command prefix'
def execute(command,cwd,grant=None,operation_id=None,isolated_runner=False):
    argv=parse_command(command); decision=classify(argv); cwd=cwd.resolve()
    if not cwd.exists() or not cwd.is_dir(): raise RuntimeError(f'target cwd does not exist: {cwd}')
    if decision.classification=='BLOCKED': raise PermissionError(decision.reason)
    if decision.classification=='COMPUTE' and not isolated_runner: raise PermissionError('COMPUTE requires isolated runner')
    op_id=operation_id or (grant.operation_id if grant else f'OP-{uuid.uuid4().hex[:12]}')
    if not decision.allowed_without_grant:
        if grant is None: raise PermissionError(f'{decision.classification} requires explicit authorization grant')
        ok,reason=grant_allows(grant,decision,cwd)
        if not ok: raise PermissionError(reason)
    started=utc_now(); proc=subprocess.run(list(argv),cwd=str(cwd),shell=False,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,check=False,env={'PATH':'/usr/local/bin:/usr/bin:/bin'}); finished=utc_now()
    receipt=ExecutionReceipt(1,f'RCP-{uuid.uuid4().hex}',op_id,str(cwd),str(cwd),argv,decision.classification,sha256_text(json.dumps(argv,separators=(',',':'))),'governed-local-reference-v2',started,finished,proc.returncode,sha256_text(proc.stdout),sha256_text(proc.stderr),len(proc.stdout.encode()),len(proc.stderr.encode()),'UNKNOWN')
    return decision,receipt,proc.stdout,proc.stderr
