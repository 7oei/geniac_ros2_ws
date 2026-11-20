import json
import numpy as np

FEATURE_NAMES=['length','width','height','top','bottom','point_count','intensity_mean','intensity_std','xy_eigen_ratio','height_mean','height_std']

def reflectivity_rule(c):
    f=c['features']
    return bool(.35<f[0]<2.8 and .10<f[1]<1.5 and .28<f[2]<1.8 and .5<f[3]<2.3 and f[4]<1. and f[6]>=18.)

class Forest:
    """Portable JSON forest; no pickle execution or sklearn dependency at inference."""
    def __init__(self,path):
        with open(path,encoding='utf-8') as f:self.model=json.load(f)
        self.trees=[{k:np.asarray(v) for k,v in t.items()} for t in self.model['trees']]
        offsets=np.cumsum([0]+[len(t['left']) for t in self.trees[:-1]])
        self.roots=offsets
        self.compiled={k:np.concatenate([np.where(t[k]>=0,t[k]+off,-1) if k in ['left','right'] else t[k]
                                        for t,off in zip(self.trees,offsets)])
                       for k in ['left','right','feature','threshold','probability']}
    def predict(self,features):
        x=np.asarray(features,dtype=np.float32)
        if len(x)==0:return np.empty(0)
        if x.ndim!=2 or x.shape[1]!=len(self.model['features']):
            raise ValueError(f"Expected {len(self.model['features'])} LiDAR features per candidate")
        if not np.isfinite(x).all():raise ValueError('Non-finite LiDAR features')
        tree=self.compiled
        nodes=np.broadcast_to(self.roots[:,None],(len(self.trees),len(x))).copy()
        for _ in range(self.model['max_depth']+1):
            active=tree['left'][nodes]>=0
            if not active.any():break
            row,col=np.nonzero(active);n=nodes[row,col]
            nodes[row,col]=np.where(x[col,tree['feature'][n]]<=tree['threshold'][n],tree['left'][n],tree['right'][n])
        return tree['probability'][nodes].mean(axis=0)
