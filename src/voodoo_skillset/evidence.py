from __future__ import annotations
import hashlib,json
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
GENESIS="0"*64
def _canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def _hash(v): return hashlib.sha256(_canon(v).encode()).hexdigest()
@dataclass(frozen=True)
class EvidenceEvent: seq:int; timestamp:str; kind:str; subject:str; payload:dict[str,Any]; prev_hash:str; event_hash:str
class EvidenceLedger:
    def __init__(self,path=None):
        self.path=Path(path) if path else None; self.events=[]
        if self.path and self.path.exists(): self.events=[EvidenceEvent(**x) for x in json.loads(self.path.read_text())]
    def append(self,kind,subject,payload):
        seq=len(self.events)+1; prev=self.events[-1].event_hash if self.events else GENESIS; core={"seq":seq,"timestamp":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"kind":kind,"subject":subject,"payload":payload,"prev_hash":prev}; e=EvidenceEvent(**core,event_hash=_hash(core)); self.events.append(e); self._persist(); return e
    def _persist(self):
        if self.path: self.path.parent.mkdir(parents=True,exist_ok=True); self.path.write_text(json.dumps([asdict(x) for x in self.events],indent=2,ensure_ascii=False)+"\n")
    def verify(self):
        prev=GENESIS
        for i,e in enumerate(self.events,1):
            if e.seq!=i: return False,f"sequence mismatch at {i}"
            if e.prev_hash!=prev: return False,f"prev_hash mismatch at {i}"
            core={k:v for k,v in asdict(e).items() if k!="event_hash"}
            if _hash(core)!=e.event_hash: return False,f"event_hash mismatch at {i}"
            prev=e.event_hash
        return True,"PASS"
