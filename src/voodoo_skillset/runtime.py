from __future__ import annotations
import json
from pathlib import Path
from .models import RuntimeManifest
def load_runtime_manifest(path:str|Path|None=None,tools=(),connectors=(),standing_grants=()):
    data={"tools":[],"connectors":[],"standing_grants":[]}
    if path: data.update(json.loads(Path(path).read_text(encoding="utf-8")))
    return RuntimeManifest(tuple(dict.fromkeys([*data.get("tools",[]),*tools])),tuple(dict.fromkeys([*data.get("connectors",[]),*connectors])),tuple(dict.fromkeys([*data.get("standing_grants",[]),*standing_grants])))
