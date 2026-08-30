from dataclasses import dataclass,field
from typing import Any
@dataclass
class Blackboard:
    goal:str; facts:list[dict[str,Any]]=field(default_factory=list); findings:list[dict[str,Any]]=field(default_factory=list); decisions:list[dict[str,Any]]=field(default_factory=list); artifacts:list[dict[str,Any]]=field(default_factory=list); blockers:list[dict[str,Any]]=field(default_factory=list); completed_tasks:list[str]=field(default_factory=list)
    def apply_delta(self,delta):
        for key,value in delta.items():
            if key=="goal": continue
            current=getattr(self,key,None)
            if isinstance(current,list): current.extend(value if isinstance(value,list) else [value])
