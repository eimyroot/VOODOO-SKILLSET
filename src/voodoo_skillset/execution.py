from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
import json,uuid
from typing import Protocol,Any
@dataclass(frozen=True)
class NetworkPolicy:
    default:str="DENY"; allowed_hosts:tuple[str,...]=()
    def allows(self,host): return self.default=="ALLOW" or host in self.allowed_hosts
@dataclass(frozen=True)
class ExecutionEnvelope:
    operation_id:str; target:str; network_policy:NetworkPolicy; timeout_seconds:int=120; cpu_limit:str="UNENFORCED_LOCAL_REFERENCE"; memory_limit:str="UNENFORCED_LOCAL_REFERENCE"
    @classmethod
    def local_reference(cls,target,allowed_hosts=()): return cls(f"OP-{uuid.uuid4().hex[:12]}",str(Path(target).resolve()),NetworkPolicy("DENY",tuple(allowed_hosts)))
class ExecutionAdapter(Protocol):
    def execute(self,capability_id:str,payload:dict[str,Any],envelope:ExecutionEnvelope)->dict[str,Any]: ...
class DryRunExecutor:
    def execute(self,capability_id,payload,envelope): return {"status":"SIMULATED","capability_id":capability_id,"operation_id":envelope.operation_id,"effect":"NONE","network_default":envelope.network_policy.default}
class RunStore:
    def __init__(self,path): self.path=Path(path)
    def append(self,record):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(record,sort_keys=True)+"\n")
    def list(self,limit=50):
        if not self.path.exists(): return []
        rows=[json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]; return rows[-limit:][::-1]
def run_record(plan_id,status,metadata=None): return {"run_id":f"RUN-{uuid.uuid4().hex[:12]}","plan_id":plan_id,"status":status,"timestamp":datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),"metadata":metadata or {}}
