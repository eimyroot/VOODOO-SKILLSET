from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

class Mode(str, Enum):
    FAST="FAST"; PRO="PRO"; ALL="ALL"; REDTEAM="REDTEAM"
class Authority(str, Enum):
    READ="READ"; COMPUTE="COMPUTE"; WRITE="WRITE"; REMOTE_WRITE="REMOTE_WRITE"; DEPLOY="DEPLOY"; DESTRUCTIVE="DESTRUCTIVE"; PRIVILEGED="PRIVILEGED"
class EvidenceStatus(str, Enum):
    VERIFIED="VERIFIED"; IMPLEMENTED="IMPLEMENTED"; SIMULATED="SIMULATED"; PROPOSED="PROPOSED"; BLOCKED="BLOCKED"; FAILED="FAILED"; UNKNOWN="UNKNOWN"
@dataclass(frozen=True)
class Capability:
    id:str; kind:str; description:str; intents:tuple[str,...]; tags:tuple[str,...]=(); requires_tools:tuple[str,...]=(); requires_connectors:tuple[str,...]=(); authority:str="READ"; risk:float=.1; latency:float=.2; token_cost:float=.2; confidence:float=.8; expected_impact:float=.6; enabled:bool=True; always_in_modes:tuple[str,...]=()
@dataclass(frozen=True)
class RuntimeManifest:
    tools:tuple[str,...]=(); connectors:tuple[str,...]=(); standing_grants:tuple[str,...]=()
@dataclass(frozen=True)
class IntentProfile:
    goal:str; intents:tuple[str,...]; write_intent:bool; destructive_intent:bool; deploy_intent:bool; confidence:float
@dataclass(frozen=True)
class Selection:
    capability_id:str; score:float; reasons:tuple[str,...]
@dataclass
class ExecutionPlan:
    plan_id:str; goal:str; mode:str; intents:list[str]; selections:list[Selection]; io_capabilities:list[Selection]; stages:list[list[str]]; required_tools:list[str]; required_connectors:list[str]; authority_gates:list[dict[str,Any]]; status:str; blockers:list[str]=field(default_factory=list)
    def to_dict(self)->dict[str,Any]: return asdict(self)
