from dataclasses import dataclass
from enum import Enum
from pathlib import Path
class Zone(str,Enum): SCRATCH="SCRATCH"; WORKSPACE="WORKSPACE"; VAULT="VAULT"
@dataclass(frozen=True)
class WorkspacePaths: root:Path; scratch:Path; workspace:Path; vault:Path
class CaserWorkspace:
    def __init__(self,root):
        root=Path(root).resolve(); self.paths=WorkspacePaths(root,root/'SCRATCH',root/'WORKSPACE',root/'VAULT')
    def initialize(self):
        for x in (self.paths.scratch,self.paths.workspace,self.paths.vault): x.mkdir(parents=True,exist_ok=True)
        return self.paths
    def resolve(self,zone,relative):
        base={Zone.SCRATCH:self.paths.scratch,Zone.WORKSPACE:self.paths.workspace,Zone.VAULT:self.paths.vault}[zone].resolve(); target=(base/relative).resolve()
        if target!=base and base not in target.parents: raise ValueError('path escapes CASER zone')
        return target
    def write(self,zone,relative,content,overwrite=False):
        target=self.resolve(zone,relative); target.parent.mkdir(parents=True,exist_ok=True)
        if zone==Zone.VAULT and target.exists(): raise FileExistsError('VAULT is append/version oriented; overwrite denied')
        if target.exists() and not overwrite: raise FileExistsError(str(target))
        target.write_text(content,encoding='utf-8'); return target
