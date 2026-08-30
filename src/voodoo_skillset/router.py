from __future__ import annotations
from .learning import LearningStore
from .models import Capability,IntentProfile,Mode,RuntimeManifest,Selection
THRESHOLDS={Mode.FAST:.52,Mode.PRO:.38,Mode.ALL:.28,Mode.REDTEAM:.30}
def _available(cap,runtime): return set(cap.requires_tools).issubset(runtime.tools) and set(cap.requires_connectors).issubset(runtime.connectors)
def score_capability(cap,intent,mode,learning):
    overlap=set(cap.intents)&set(intent.intents); tags=" ".join(cap.tags).lower(); lexical=sum(1 for w in intent.goal.lower().split() if w.strip(".,:/") in tags); relevance=min(1,.22*len(overlap)+.03*lexical+(.18 if "general" in cap.intents else 0)); score=.42*relevance+.19*cap.confidence+.19*cap.expected_impact+learning.get_signal(cap.id)-.08*cap.risk-.05*cap.latency-.03*cap.token_cost
    if mode.value in cap.always_in_modes: score=max(score,.92)
    reasons=[]
    if overlap: reasons.append("intent:"+",".join(sorted(overlap)))
    if mode.value in cap.always_in_modes: reasons.append("mode-required")
    return Selection(cap.id,round(score,4),tuple(reasons or ["supporting-capability"]))
def route(capabilities,intent,mode,runtime,learning,exclude=None):
    exclude=exclude or set(); workers=[]; io=[]; blockers=[]; threshold=THRESHOLDS[mode]
    for cap in capabilities:
        if not cap.enabled or cap.id in exclude: continue
        if not _available(cap,runtime):
            if mode.value in cap.always_in_modes: blockers.append(f"{cap.id}: unavailable tools={sorted(set(cap.requires_tools)-set(runtime.tools))} connectors={sorted(set(cap.requires_connectors)-set(runtime.connectors))}")
            continue
        if cap.kind in {"plugin","tool"}:
            if cap.authority in {"WRITE","REMOTE_WRITE"} and not intent.write_intent: continue
            if cap.authority=="DEPLOY" and not intent.deploy_intent: continue
        sel=score_capability(cap,intent,mode,learning)
        if cap.kind in {"plugin","tool"}:
            if sel.score>=threshold and (set(cap.intents)&set(intent.intents)): io.append(sel)
        elif sel.score>=threshold or mode.value in cap.always_in_modes: workers.append(sel)
    workers.sort(key=lambda s:(-s.score,s.capability_id)); io.sort(key=lambda s:(-s.score,s.capability_id)); return workers,io,blockers
