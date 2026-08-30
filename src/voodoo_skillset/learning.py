from __future__ import annotations
import json
from dataclasses import dataclass,asdict
from pathlib import Path
@dataclass
class LearningStat:
    samples:int=0; success_rate:float=.5; unique_value:float=.5; false_positive_rate:float=0.0
    def signal(self): return max(-.2,min(.2,(.45*self.success_rate+.45*self.unique_value-.35*self.false_positive_rate-.4)*.4))
class LearningStore:
    def __init__(self,path=None):
        self.path=Path(path) if path else None; self.stats={}
        if self.path and self.path.exists(): self.stats={k:LearningStat(**v) for k,v in json.loads(self.path.read_text()).items()}
    def get_signal(self,cid): return self.stats.get(cid,LearningStat()).signal()
    def update(self,cid,success,unique_value,false_positive,alpha=.2):
        s=self.stats.setdefault(cid,LearningStat()); s.samples+=1; s.success_rate=(1-alpha)*s.success_rate+alpha*(1 if success else 0); s.unique_value=(1-alpha)*s.unique_value+alpha*max(0,min(1,unique_value)); s.false_positive_rate=(1-alpha)*s.false_positive_rate+alpha*(1 if false_positive else 0)
        if self.path: self.path.parent.mkdir(parents=True,exist_ok=True); self.path.write_text(json.dumps({k:asdict(v) for k,v in self.stats.items()},indent=2)+"\n")
        return s
