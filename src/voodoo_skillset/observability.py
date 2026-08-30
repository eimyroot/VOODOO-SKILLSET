from collections import Counter
from threading import Lock
class Metrics:
    def __init__(self): self._c=Counter(); self._lock=Lock()
    def inc(self,key,n=1):
        with self._lock: self._c[key]+=n
    def snapshot(self):
        with self._lock: return dict(self._c)
