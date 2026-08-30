from __future__ import annotations
from dataclasses import dataclass
from .models import Authority,Capability,IntentProfile,RuntimeManifest
@dataclass(frozen=True)
class GateDecision: capability_id:str; authority:str; decision:str; reason:str
def authority_gate(cap:Capability,intent:IntentProfile,runtime:RuntimeManifest)->GateDecision:
    a=Authority(cap.authority)
    if a==Authority.READ: return GateDecision(cap.id,a.value,"ALLOW","read capability")
    if a==Authority.COMPUTE:
        return GateDecision(cap.id,a.value,"ALLOW","isolated compute runner available") if ({"isolated-runner","test-runner"}&set(runtime.tools)) else GateDecision(cap.id,a.value,"BLOCK","compute requires isolated runner")
    if a==Authority.WRITE:
        if not intent.write_intent: return GateDecision(cap.id,a.value,"BLOCK","no explicit write intent")
        return GateDecision(cap.id,a.value,"ALLOW","standing WRITE grant") if "WRITE" in runtime.standing_grants else GateDecision(cap.id,a.value,"APPROVAL_REQUIRED","bounded write authorization required")
    if a==Authority.REMOTE_WRITE:
        if not intent.write_intent: return GateDecision(cap.id,a.value,"BLOCK","no explicit remote-write intent")
        return GateDecision(cap.id,a.value,"ALLOW","standing REMOTE_WRITE grant") if "REMOTE_WRITE" in runtime.standing_grants else GateDecision(cap.id,a.value,"APPROVAL_REQUIRED","bounded remote-write authorization required")
    if a==Authority.DEPLOY:
        if not intent.deploy_intent: return GateDecision(cap.id,a.value,"BLOCK","no explicit deploy intent")
        return GateDecision(cap.id,a.value,"ALLOW","dedicated DEPLOY grant") if "DEPLOY" in runtime.standing_grants else GateDecision(cap.id,a.value,"APPROVAL_REQUIRED","dedicated deploy approval required")
    return GateDecision(cap.id,a.value,"APPROVAL_REQUIRED","explicit one-operation authorization required")
