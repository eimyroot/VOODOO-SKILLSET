from __future__ import annotations
import re
from .models import IntentProfile
INTENT_PATTERNS={"audit":("audit","review","inspect","analyze","analyse","diagnose"),"security":("security","secure","threat","vulnerability","red team","red-team"),"research":("research","compare","investigate","source","market","competitive"),"architecture":("architecture","architect","design","system design"),"implement":("implement","fix","repair","build","create","refactor","develop","code"),"test":("test","qa","verify build","ci"),"deploy":("deploy","release","production","ship"),"verify":("verify","independent","evidence","prove","validate"),"ux":("webdesign","web design","ui","ux","frontend","dashboard","control room"),"github":("github","repository","repo","pull request","pr"),"observe":("observability","metrics","telemetry","logs","trace")}
WRITE_WORDS={"write","commit","push","merge","change","modify","implement","fix","repair","create","refactor","build"}; DESTRUCTIVE_WORDS={"delete","remove","destroy","reset","wipe","purge"}; DEPLOY_WORDS={"deploy","release","production","promote"}
def classify_intent(goal:str)->IntentProfile:
    text=goal.lower().strip(); intents=[]
    for intent,patterns in INTENT_PATTERNS.items():
        if any(p in text for p in patterns): intents.append(intent)
    if not intents: intents.append("general")
    words=set(re.findall(r"[a-z0-9_-]+",text))
    return IntentProfile(goal,tuple(dict.fromkeys(intents)),bool(words&WRITE_WORDS),bool(words&DESTRUCTIVE_WORDS),bool(words&DEPLOY_WORDS),min(.98,.55+.08*len(intents)))
