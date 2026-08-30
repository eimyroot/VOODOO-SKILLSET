from .models import ExecutionPlan
def verify_plan(plan:ExecutionPlan,require_verifier=True):
    problems=[]; ids=[s.capability_id for s in plan.selections]; flat=[x for stage in plan.stages for x in stage]
    if len(flat)!=len(set(flat)): problems.append("duplicate capability in DAG")
    if set(flat)!=set(ids): problems.append("DAG does not cover selected workers")
    if require_verifier and "independent-verifier" not in ids: problems.append("independent verifier missing")
    where={x:i for i,stage in enumerate(plan.stages) for x in stage}
    if "implementer" in where and "test-engineer" in where and where["implementer"]>=where["test-engineer"]: problems.append("tests must run after implementer")
    if "independent-verifier" in where:
        for x in ids:
            if x not in {"independent-verifier","evidence-curator"} and where[x]>=where["independent-verifier"]: problems.append(f"verifier must run after {x}")
    if plan.blockers: problems.extend(plan.blockers)
    return not problems,problems
