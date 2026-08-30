from __future__ import annotations
DEPENDENCY_RULES={"implementer":{"architect","repo-auditor","security-reviewer","reality-checker"},"test-engineer":{"implementer"},"devops-reviewer":{"test-engineer"}}
def compose_stages(selected_ids):
    selected=set(selected_ids); deps={x:set() for x in selected}
    for node,prereqs in DEPENDENCY_RULES.items():
        if node in selected: deps[node]|=prereqs&selected
    if "red-team" in selected: deps["red-team"]|={x for x in selected if x not in {"red-team","independent-verifier","evidence-curator"}}
    if "independent-verifier" in selected: deps["independent-verifier"]|={x for x in selected if x not in {"independent-verifier","evidence-curator"}}
    if "evidence-curator" in selected: deps["evidence-curator"]|={x for x in selected if x not in {"evidence-curator","independent-verifier"}}
    stages=[]; remaining=set(selected); completed=set()
    while remaining:
        ready=sorted(x for x in remaining if deps[x]<=completed)
        if not ready: raise ValueError(f"dependency cycle or unsatisfied dependencies: {sorted(remaining)}")
        stages.append(ready); completed.update(ready); remaining.difference_update(ready)
    return stages
