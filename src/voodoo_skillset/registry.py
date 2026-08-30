from __future__ import annotations
import json
from pathlib import Path
from .models import Capability
class CapabilityRegistry:
    def __init__(self,capabilities:list[Capability]):
        ids=[c.id for c in capabilities]
        if len(ids)!=len(set(ids)): raise ValueError("duplicate capability id")
        self._items={c.id:c for c in capabilities}
    @classmethod
    def from_path(cls,path:str|Path):
        raw=json.loads(Path(path).read_text(encoding="utf-8")); items=[]
        for x in raw["capabilities"]:
            x=dict(x)
            for key in ("intents","tags","requires_tools","requires_connectors","always_in_modes"): x[key]=tuple(x.get(key,()))
            items.append(Capability(**x))
        return cls(items)
    def all(self): return list(self._items.values())
    def get(self,capability_id): return self._items[capability_id]
