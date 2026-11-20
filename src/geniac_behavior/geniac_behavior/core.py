"""Scenario-relative movement and observed entry/exit in a fixed LiDAR frame.

Five seconds of continuous valid disappearance is an escape by the project's operational definition.
Sensor outages are unknown. Departure results are retained for scenario consumers,
and the scene remains escaped whenever no deer is visible, including startup.
"""
from collections import deque
from dataclasses import dataclass
import math
import numpy as np

LABELS = ('escaped', 'retreated_nearby', 'no_escape', 'observing', 'unknown')


@dataclass(frozen=True)
class Settings:
    stationary_radius: float = .75
    stop_speed: float = .35
    settle_seconds: float = 2.0
    observation_seconds: float = 4.0
    missing_seconds: float = 5.0
    stale_seconds: float = 1.0
    max_history: int = 600

    def __post_init__(self):
        values = [v for k,v in self.__dict__.items() if k != 'max_history']
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError('Thresholds must be positive and finite')
        if self.observation_seconds < self.settle_seconds:
            raise ValueError('Invalid time ordering')
        if type(self.max_history) is not int or self.max_history < 20:
            raise ValueError('History must hold at least 20 observations')


class Classifier:
    def __init__(self, settings=None):
        self.settings = settings or Settings()
        self.histories = {}
        self.baselines = {}
        self.moved = set()
        self.departed = {}
        self.pending = {}
        self.last_stamp = None
        self.frame = None
        self.stream = None
        self.epoch = ''
        self.epoch_stamp = 0.0
        self.valid = False
        self.last_seen = set()
        self.scene_state = 'escaped'
        self.visibility_known = False

    def begin(self, epoch, stamp):
        if not math.isfinite(stamp):raise ValueError('Invalid baseline timestamp')
        if epoch == self.epoch:return
        # Evaluate the response to this scenario against the latest visible position
        # at its start, not against program start or the original arrival position.
        visible = {k:self.histories[k][-1][1].copy() for k in self.last_seen
                   if k in self.histories and self.valid and self.last_stamp is not None
                   and 0 <= stamp-self.last_stamp <= self.settings.stale_seconds}
        self.epoch, self.epoch_stamp = epoch, stamp
        # Motion evidence spans scene boundaries; only the response origin resets.
        self.histories={key:self.histories[key] for key in visible}
        self.baselines.clear();self.moved.clear()
        for key,p in visible.items():
            self.baselines[key] = (stamp,p)
        # Presence is independent of scenario baseline changes.

    def update(self, packet):
        stamp = float(packet['stamp'])
        frame, stream = packet['frame_id'], packet['stream_id']
        if not math.isfinite(stamp) or stamp <= 0 or not frame or not stream:
            raise ValueError('Invalid track header')
        rows = []
        for t in packet['tracks']:
            p = np.asarray(t['center'], dtype=float)
            if p.shape != (3,) or not np.isfinite(p).all():raise ValueError('Invalid track coordinates')
            rows.append((str(stream) + ':' + str(t['track_id']), p))
        if len({k for k,p in rows}) != len(rows):raise ValueError('Duplicate track ID')
        reset = self.last_stamp is not None and (stamp <= self.last_stamp or frame != self.frame or stream != self.stream)
        if reset:
            self.histories.clear();self.baselines.clear();self.moved.clear();self.departed.clear();self.pending.clear()
            self.last_seen.clear();self.visibility_known=False
        gap = self.last_stamp is not None and stamp-self.last_stamp > self.settings.stale_seconds
        self.last_stamp, self.frame, self.stream = stamp, frame, stream
        was_valid = self.valid
        self.valid = packet.get('valid', True) is True
        if not self.valid:
            self.histories.clear()
            for target in self.pending.values():target['missing_since']=None
            self.visibility_known=False;self.scene_state='unknown';return
        if stamp < self.epoch_stamp:
            self.valid=False;self.scene_state='unknown';return
        current = {k for k,p in rows}
        if gap or not self.visibility_known or not was_valid:
            for target in self.pending.values():target['missing_since']=None
        lost = self.last_seen-current
        for key in lost:
            # Preserve the outcome for consumers slower than the input frame rate.
            start,base = self.baselines.get(key,(stamp,np.zeros(3)))
            h=self.histories.get(key)
            t,p=h[-1] if h else (start,base)
            self.pending[key]={'id':key,'label':'observing','present':False,'last_seen':t,
                               'missing_since':stamp,'baseline_stamp':start,
                               'range_m':float(np.linalg.norm(p[:2])),
                               'radial_gain_m':float(np.linalg.norm(p[:2])-np.linalg.norm(base[:2])),
                               'displacement_m':float(np.linalg.norm(p[:2]-base[:2]))}
        for key,p in rows:
            if key not in self.last_seen and key not in self.pending:
                self.histories.pop(key,None);self.baselines.pop(key,None);self.moved.discard(key)
            self.pending.pop(key,None)
            self.departed.pop(key,None)
            h=self.histories.setdefault(key,deque(maxlen=self.settings.max_history))
            if h and stamp-h[-1][0]>self.settings.stale_seconds:h.clear()
            h.append((stamp,p))
            self.baselines.setdefault(key,(stamp,p.copy()))
            if np.linalg.norm(p[:2]-self.baselines[key][1][:2])>self.settings.stationary_radius:
                self.moved.add(key)
        for key,target in list(self.pending.items()):
            if target['missing_since'] is None:target['missing_since']=stamp
            target['missing_elapsed_seconds']=stamp-target['missing_since']
            if target['missing_elapsed_seconds'] >= self.settings.missing_seconds:
                self.departed[key]=dict(target,label='escaped',departure_stamp=stamp)
                del self.pending[key]
        self.last_seen=current;self.visibility_known=True
        self.scene_state='present' if current else ('observing' if self.pending else 'escaped')
        for key in list(self.histories):
            if key not in current and key not in self.pending:
                del self.histories[key];self.baselines.pop(key,None);self.moved.discard(key)
        # Bound retained outcomes while preserving recent scenario results (max episode 180s).
        self.departed={k:v for k,v in self.departed.items() if stamp-v['departure_stamp']<=180}

    def _label(self, key, now):
        s=self.settings;h=self.histories[key]
        t,p=h[-1];start,base=self.baselines[key]
        info={'id':key,'label':'observing','present':True,'baseline_stamp':start,
              'range_m':float(np.linalg.norm(p[:2])),
              'radial_gain_m':float(np.linalg.norm(p[:2])-np.linalg.norm(base[:2])),
              'displacement_m':float(np.linalg.norm(p[:2]-base[:2])),'last_seen':t,'stationary_seconds':0.}
        if not self.valid or now-t>s.stale_seconds or now<t:
            info['label']='unknown';return info
        # Any movement outside the existing no-movement tolerance counts, including
        # sideways/towards the sensor, still moving, or returning to the start.
        if key in self.moved:
            info['label']='retreated_nearby'
        recent=[(a,b) for a,b in h if a>=t-s.settle_seconds-s.stale_seconds]
        window=[(a,b) for a,b in recent if a>=t-s.settle_seconds]
        anchor=next(((a,b) for a,b in reversed(recent) if a<=t-s.settle_seconds),None)
        if anchor is None or t<self.epoch_stamp:return info
        window=[anchor]+window
        if len(window)<3:return info
        speed=float(np.linalg.norm(window[-1][1][:2]-window[0][1][:2])/max(window[-1][0]-window[0][0],1e-6))
        spread=max(float(np.linalg.norm(b[:2]-p[:2])) for a,b in window)
        info['speed_mps']=speed
        if speed<=s.stop_speed and spread<=s.stationary_radius:
            info['stationary_seconds']=s.settle_seconds
        scene_baseline=bool(self.epoch) and start==self.epoch_stamp
        if key not in self.moved and (scene_baseline or t-start>=s.observation_seconds) and speed<=s.stop_speed and spread<=s.stationary_radius:
            info['label']='no_escape'
        return info

    def report(self, now):
        valid=self.valid and self.last_stamp is not None and 0<=now-self.last_stamp<=self.settings.stale_seconds
        targets=[self._label(k,now) for k in sorted(self.last_seen) if k in self.histories]
        targets += [dict(v) for k,v in sorted(self.pending.items())]
        targets += [dict(v) for k,v in sorted(self.departed.items()) if k not in self.last_seen]
        if not valid:
            for target in targets:target['label']='unknown'
        state=self.scene_state if valid or self.last_stamp is None else 'unknown'
        if state=='present':
            labels=[t['label'] for t in targets if t['present']]
            state='retreated_nearby' if 'retreated_nearby' in labels else ('no_escape' if labels and all(x=='no_escape' for x in labels) else 'observing')
        return {'version':1,'stamp':float(now),'epoch':self.epoch,'frame_id':self.frame or '',
                'valid':bool(valid),'state':state,'present_ids':sorted(self.last_seen) if valid else [],
                'targets':targets}


def group_response(targets, cohort):
    """Departed outcomes remain usable while other cohort members are visible."""
    labels={t['id']:t['label'] for t in targets}
    cohort=set(cohort) | {t['id'] for t in targets if t.get('present') is True}
    order={'no_escape':0,'retreated_nearby':1,'escaped':2}
    if not cohort or any(labels.get(k) not in order for k in cohort):return 'unknown'
    return min((labels[k] for k in cohort),key=order.get)
