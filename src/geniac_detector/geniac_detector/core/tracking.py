"""Fixed sensor-frame tracks; no odometry, IMU, ICP, or robot motion compensation.

This produces observations, never robot commands. Track IDs are short-lived, not permanent animal identities.
"""
from collections import deque
import math
import numpy as np
from scipy.optimize import linear_sum_assignment

class Tracker:
    def __init__(self,confirm_score=.7,max_speed_mps=10.,position_tolerance_m=.2):
        if not math.isfinite(max_speed_mps) or max_speed_mps<=0:raise ValueError("max_speed_mps must be positive and finite")
        if not math.isfinite(position_tolerance_m) or position_tolerance_m<0:raise ValueError("position_tolerance_m must be nonnegative and finite")
        self.max_speed_mps=max_speed_mps;self.position_tolerance_m=position_tolerance_m
        self.confirm_score=confirm_score;self.previous=None;self.last_stamp=None;self.tracks=[];self.next_id=1
    def update(self,observations,points,stamp,ground_quality=1.):
        sample=None
        motion={'enabled':False,'valid':True,'mode':'stationary_sensor'}
        dt=None if self.last_stamp is None else stamp-self.last_stamp
        if dt is not None and (dt<=0 or dt>1.0):self.tracks=[];self.previous=None
        self.previous=sample;self.last_stamp=stamp
        assigned=set();matched=set()
        if self.tracks and observations:
            costs=np.full((len(self.tracks),len(observations)),1e9)
            speed_rejections=0
            for i,tr in enumerate(self.tracks):
                elapsed=stamp-tr['observed_stamp']
                predicted=tr['position']+tr.get('velocity',np.zeros(3))*elapsed
                for j,c in enumerate(observations):
                    new=np.asarray(c['center'])
                    displacement=np.linalg.norm((new-tr['position'])[:2])
                    if displacement>self.max_speed_mps*elapsed+self.position_tolerance_m:
                        speed_rejections+=1;continue
                    error=np.linalg.norm((predicted-new)[:2])
                    if error<=min(3.,.8+6.*elapsed):costs[i,j]=error
            motion['speed_gate_rejected_pairs']=speed_rejections
            rr,cc=linear_sum_assignment(costs)
            for i,j in zip(rr,cc):
                if costs[i,j]>=1e9:continue
                tr=self.tracks[i];c=observations[j];new=np.asarray(c['center'])
                elapsed=stamp-tr['observed_stamp']
                tr['velocity']=(new-tr['position'])/elapsed
                tr['speed_mps']=float(np.linalg.norm(tr['velocity'][:2]))
                tr['observed_stamp']=stamp;tr['position']=new
                tr['history'].append(c['score']>=self.confirm_score);tr['missed']=0;tr['hits']+=1;tr['observation']=c;assigned.add(j);matched.add(i)
        for i,tr in enumerate(self.tracks):
            if i not in matched:tr['missed']+=1;tr['history'].append(False)
        for j,c in enumerate(observations):
            if j in assigned:continue
            self.tracks.append({'id':self.next_id,'observed_stamp':stamp,'speed_mps':0.,'position':np.asarray(c['center']),'history':deque([c['score']>=self.confirm_score],maxlen=5),'missed':0,'hits':1,'observation':c});self.next_id+=1
        self.tracks=[tr for tr in self.tracks if tr['missed']<=10]
        output=[]
        for tr in self.tracks:
            if tr['missed']:continue
            c=tr['observation'];confirmed=tr['hits']>=3 and sum(tr['history'])>=2 and ground_quality>=.35
            p=tr['position']
            output.append({'track_id':tr['id'],'state':'observed_candidate' if confirmed else 'tentative','center':p.tolist(),'range_m':float(np.linalg.norm(p[:2])),'bearing_rad':float(np.arctan2(p[1],p[0])),'score':c['score'],'lo':np.asarray(c['lo']).tolist(),'hi':np.asarray(c['hi']).tolist(),'points':int(c['n']),'hits':tr['hits'],'speed_mps':tr['speed_mps']})
        return output,motion
