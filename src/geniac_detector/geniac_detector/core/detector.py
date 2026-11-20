"""CPU-only geometric candidate detector. Scores are heuristics, not probabilities."""
from dataclasses import dataclass
import time
import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

@dataclass
class Config:
    ground: str = 'plane'
    max_range: float = 45.
    voxel: float = .08
    eps: float = .35
    min_points: int = 8
    min_height: float = .20

def ground_plane(p):
    """Dominant ground z=a*x+b*y+c, robust to modest handheld pitch/roll."""
    q=p[(p[:,0]>1)&(p[:,0]<25)&(np.abs(p[:,1])<16)&(p[:,2]<.5),:3]
    if len(q)<40:return np.array([0.,0.,-1.0]),0.
    rng=np.random.default_rng(42)
    q=q[rng.choice(len(q),min(len(q),1600),replace=False)]
    design=np.column_stack((q[:,:2],np.ones(len(q))))
    best=0;plane=np.array([0.,0.,-1.])
    for _ in range(70):
        ids=rng.choice(len(q),3,replace=False)
        try:coef=np.linalg.solve(design[ids],q[ids,2])
        except np.linalg.LinAlgError:continue
        if np.linalg.norm(coef[:2])>.8 or not -3.5<coef[2]<-.15:continue
        mask=np.abs(q[:,2]-design@coef)<.13
        count=mask.sum()
        if count>best:best=count;plane=coef
    for _ in range(3):
        mask=np.abs(q[:,2]-design@plane)<.15
        if mask.sum()>=20:plane=np.linalg.lstsq(design[mask],q[mask,2],rcond=None)[0]
    return plane,float(best/len(q))

def candidates(points,config=None,ground_override=None):
    """Extract proposals; optional experimental (plane, quality) leaves defaults unchanged."""
    cfg=config or Config();start=time.perf_counter()
    p=np.asarray(points,dtype=np.float32)
    p=p[np.isfinite(p).all(axis=1)&(p[:,0]>.8)&(np.linalg.norm(p[:,:3],axis=1)<cfg.max_range)]
    if ground_override is None:
        plane,quality=ground_plane(p) if cfg.ground!='fixed' else (np.array([0.,0.,-1.0]),1.)
    else:
        plane,quality=ground_override;plane=np.asarray(plane,dtype=float)
        if plane.shape!=(3,) or not np.isfinite(plane).all() or not 0<=quality<=1:
            raise ValueError('ground_override must contain a finite 3-coefficient plane and quality in [0,1]')
    h=p[:,2]-p[:,0]*plane[0]-p[:,1]*plane[1]-plane[2]
    if cfg.ground=='local' and len(p):
        # Coarse cell minima correct gentle terrain changes without per-object fitting.
        cells=np.floor(p[:,:2]/2.).astype(int)
        _,inv=np.unique(cells,axis=0,return_inverse=True)
        mins=np.full(inv.max()+1,np.inf);np.minimum.at(mins,inv,h)
        centers=np.column_stack([np.bincount(inv,weights=p[:,j])/np.bincount(inv) for j in range(2)])
        valid=(mins>-.8)&(mins<.6)
        if valid.sum()>3:
            _,ix=cKDTree(centers[valid]).query(p[:,:2],k=1)
            h=h-mins[valid][ix]
    mask=(h>cfg.min_height)&(h<3.)
    p=p[mask];h=h[mask]
    if len(p)==0:return [],{'plane':plane.tolist(),'ground_quality':quality,'ms':(time.perf_counter()-start)*1000}
    _,ids=np.unique(np.floor(p[:,:3]/cfg.voxel).astype(np.int32),axis=0,return_index=True)
    p=p[ids];h=h[ids]
    # Radius graph on bounded, downsampled points; connected components avoids quadratic DBSCAN arrays.
    pairs=cKDTree(p[:,:3]).query_pairs(cfg.eps,output_type='ndarray')
    graph=coo_matrix((np.ones(len(pairs)),(pairs[:,0],pairs[:,1])),shape=(len(p),len(p))).tocsr()
    _,labels=connected_components(graph,directed=False)
    out=[]
    for label,count in enumerate(np.bincount(labels)):
        if count<cfg.min_points:continue
        idx=np.flatnonzero(labels==label);q=p[idx];qh=h[idx]
        lo=np.min(q[:,:3],axis=0);hi=np.max(q[:,:3],axis=0);center=(lo+hi)/2
        cov=np.cov(q[:,:2].T);eig,vec=np.linalg.eigh(cov);xy=q[:,:2]@vec
        dims=np.ptp(xy,axis=0);width,length=sorted(dims)
        height=float(np.ptp(qh));top=float(qh.max());bottom=float(qh.min())
        if length>4. or width>2.5 or top>2.8:continue
        # Deliberately broad proposal filter; annotation must decide class independently.
        plausible=(.35<length<2.5 and .12<width<1.2 and .3<height<1.9 and .5<top<2.3 and bottom<.8)
        features=[float(length),float(width),height,top,bottom,float(count),float(np.mean(q[:,3])),float(np.std(q[:,3])),float(eig[0]/(eig[1]+1e-6)),float(np.mean(qh)),float(np.std(qh))]
        out.append({'center':center.tolist(),'lo':lo.tolist(),'hi':hi.tolist(),'features':features,'n':int(count),'rule':bool(plausible),'points':q})
    return out,{'plane':plane.tolist(),'ground_quality':quality,'ms':(time.perf_counter()-start)*1000,'foreground_voxels':len(p)}
