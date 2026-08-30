import uuid
from .dag import compose_stages
from .intent import classify_intent
from .learning import LearningStore
from .models import ExecutionPlan,Mode
from .policy import authority_gate
from .router import route
from .verifier import verify_plan
class Orchestrator:
    def __init__(self,registry,learning=None): self.registry=registry; self.learning=learning or LearningStore()
    def plan(self,goal,mode,runtime,exclude=None):
        intent=classify_intent(goal); workers,io,blockers=route(self.registry.all(),intent,mode,runtime,self.learning,exclude); ids=[s.capability_id for s in workers]; stages=compose_stages(ids); gates=[]
        for sel in [*workers,*io]:
            cap=self.registry.get(sel.capability_id); g=authority_gate(cap,intent,runtime); gates.append({'capability_id':g.capability_id,'authority':g.authority,'decision':g.decision,'reason':g.reason})
            if g.decision=='BLOCK' and cap.kind not in {'plugin','tool'}: blockers.append(f'{cap.id}: {g.reason}')
        tools=sorted({x for s in workers+io for x in self.registry.get(s.capability_id).requires_tools}); connectors=sorted({x for s in workers+io for x in self.registry.get(s.capability_id).requires_connectors}); plan=ExecutionPlan(f'PLAN-{uuid.uuid4().hex[:12]}',goal,mode.value,list(intent.intents),workers,io,stages,tools,connectors,gates,'PROPOSED',blockers); ok,problems=verify_plan(plan,mode!=Mode.FAST); plan.status='VERIFIED_PLAN' if ok else 'BLOCKED'
        if not ok:
            for p in problems:
                if p not in plan.blockers: plan.blockers.append(p)
        return plan
