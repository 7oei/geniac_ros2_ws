"""Vectorized, bounded LiDAR rasterization on the sensor host."""
from collections import deque
import json
import math
import threading
import time
import cv2
import numpy as np
from geniac_detector.cloud import decode_cloud


class Raster:
    def __init__(self,width=960,height=320,frames=10):
        self.width=width;self.height=height;self.frames=deque(maxlen=frames)
        self.focal=1.5*width/(2*math.tan(math.radians(60)))
    def project(self,xyz):
        xyz=np.asarray(xyz,dtype=np.float32)[:,:3]
        valid=np.isfinite(xyz).all(axis=1)&(xyz[:,0]>.2)
        points=xyz[valid]
        u=self.width/2-self.focal*points[:,1]/points[:,0]
        v=self.height/2-self.focal*points[:,2]/points[:,0]
        inside=(u>=0)&(u<self.width)&(v>=0)&(v<self.height)
        return u[inside].astype(np.int32),v[inside].astype(np.int32),np.linalg.norm(points[inside],axis=1)
    def add(self,xyz,now):
        u,v,d=self.project(xyz)
        depth=np.full(self.width*self.height,np.inf,np.float32)
        np.minimum.at(depth,v*self.width+u,d)
        self.frames.append((now,depth))
    def render(self,now,tracks=()):
        while self.frames and now-self.frames[0][0]>2.:self.frames.popleft()
        image=np.full((self.height,self.width,3),(39,28,17),np.uint8)
        cv2.line(image,(0,self.height//2),(self.width,self.height//2),(87,70,48),1)
        if not self.frames:
            cv2.putText(image,'LiDAR disconnected',(20,35),cv2.FONT_HERSHEY_SIMPLEX,.7,(180,180,180),1)
            return image
        # Nearest point wins per pixel; reverse order resolves ties in favour of new points.
        depths=np.stack([d for _,d in reversed(self.frames)])
        nearest=depths.min(axis=0);valid=np.isfinite(nearest)
        age=depths.argmin(axis=0)[valid]
        hsv=np.zeros((int(valid.sum()),1,3),np.uint8)
        hsv[:,0,0]=np.minimum(nearest[valid]/45.,1.)*.65*179
        hsv[:,0,1]=166;hsv[:,0,2]=255
        color=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)[:,0] if len(hsv) else np.empty((0,3))
        alpha=(1.-.7*age/max(1,len(self.frames)-1))[:,None]
        image.reshape(-1,3)[valid]=(color*alpha+np.array([39,28,17])*(1-alpha)).astype(np.uint8)
        def point(xyz):
            x,y,z=map(float,xyz[:3])
            if not all(map(math.isfinite,(x,y,z))) or x<=.2:return None
            return (int(np.clip(self.width/2-self.focal*y/x,-10000,10000)),int(np.clip(self.height/2-self.focal*z/x,-10000,10000)))
        for t in tracks:
            at=point(t['center'])
            if at is None:continue
            if 'lo' in t and 'hi' in t:
                corners=[point([t['hi' if mask&(1<<axis) else 'lo'][axis] for axis in range(3)]) for mask in range(8)]
                for mask in range(8):
                    for axis in range(3):
                        other=mask^(1<<axis)
                        if mask<other and corners[mask] is not None and corners[other] is not None:cv2.line(image,corners[mask],corners[other],(90,120,255),2)
            else:cv2.circle(image,at,7,(90,120,255),2)
            cv2.putText(image,f"ID {t['track_id']} {t.get('score',0):.2f}",(at[0]+10,at[1]-5),cv2.FONT_HERSHEY_SIMPLEX,.5,(90,120,255),1)
        cv2.putText(image,f'LiDAR 1.5x / {len(self.frames)} frames',(12,22),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
        return image


class LidarRenderer:
    def __init__(self,deliver):
        self.deliver=deliver;self.pending=deque(maxlen=10);self.lock=threading.Lock();self.closed=threading.Event()
        self.tracks=[];self.tracks_at=0.;self.raster=Raster();self.stats={}
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def cloud(self,msg):
        if msg.header.frame_id!='livox_frame':return
        with self.lock:self.pending.append((time.monotonic(),msg))
    def tracking(self,msg):
        try:
            data=json.loads(msg.data)
            with self.lock:self.tracks=data.get('tracks',[]) if data.get('valid') else [];self.tracks_at=time.monotonic()
        except (ValueError,TypeError):pass
    def run(self):
        while not self.closed.is_set():
            started=time.monotonic()
            try:
                with self.lock:
                    incoming=list(self.pending);self.pending.clear();tracks=list(self.tracks) if started-self.tracks_at<2 else []
                for stamp,msg in incoming:self.raster.add(decode_cloud(msg),stamp)
                image=self.raster.render(started,tracks)
                self.stats={'frames':len(self.raster.frames),'render_ms':round((time.monotonic()-started)*1000,2),'source_age':round(started-self.raster.frames[-1][0],3) if self.raster.frames else None}
                self.deliver(image)
            except Exception as exc:self.stats={'error':type(exc).__name__}
            self.closed.wait(max(0,.1-(time.monotonic()-started)))
    def close(self):self.closed.set();self.thread.join(timeout=3)
