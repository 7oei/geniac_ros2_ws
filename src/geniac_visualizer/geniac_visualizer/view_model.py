"""Presentation-only state with stale-data clearing and bounded trajectories."""
from collections import defaultdict, deque
import time
import numpy as np

class ViewModel:
    def __init__(self):
        self.cloud=np.empty((0,4));self.tracks=[];self.paths=defaultdict(lambda:deque(maxlen=100))
        self.tree={};self.scenario={};self.behavior={};self.recording={};self.timestamps={};self.stream=None
    def update(self,kind,data,now=None):
        now=time.monotonic() if now is None else now;self.timestamps[kind]=now
        if kind=='tracks':
            if data.get('stream_id')!=self.stream:
                self.paths.clear();self.stream=data.get('stream_id')
            self.tracks=data.get('tracks',[]) if data.get('valid') else []
            active=set()
            for t in self.tracks:
                key=str(t['track_id']);active.add(key);self.paths[key].append(t['center'][:2])
            for key in list(self.paths):
                if key not in active:del self.paths[key]
        else:setattr(self,kind,data)
    def fresh(self,kind,now=None,timeout=2.):
        now=time.monotonic() if now is None else now
        return kind in self.timestamps and 0<=now-self.timestamps[kind]<timeout
    def expire(self,now=None):
        if not self.fresh('tracks',now):self.tracks=[];self.paths.clear()
        if not self.fresh('cloud',now):self.cloud=np.empty((0,4))


def tree_layers(tree):
    nodes=tree.get('nodes',{});root=tree.get('root')
    if root not in nodes:return {}
    depth={root:0}
    for _ in range(len(nodes)):
        changed=False
        for k,d in list(depth.items()):
            for target in nodes[k].get('branches',{}).values():
                if target in nodes and depth.get(target,-1)<d+1:
                    depth[target]=d+1;changed=True
        if not changed:break
    layers=defaultdict(list)
    for k,d in depth.items():layers[d].append(k)
    return dict(layers)
