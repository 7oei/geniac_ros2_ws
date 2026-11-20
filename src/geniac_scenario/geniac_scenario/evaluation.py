"""Timing and acoustic-use proxies; never claim measured animal stress."""
import math
import uuid
from geniac_behavior.core import group_response


class Trial:
    def __init__(self,core,now,mode='simulation',volume=30):
        self.trial_id=uuid.uuid4().hex;self.tree=core.tree;self.started=now;self.mode=mode;self.volume=volume
        self.story=self.tree.get('story',{});self.done=False;self.dose=0.;self.impulses=0
        self.visits={};self.path=[];self.elapsed=0.;self.last=now;self.initial_targets=sorted(core.cohort);self.targets=set(core.cohort)

    def observe(self,now,core,targets,valid=True):
        self.targets.update(t['id'] for t in targets if t.get('present') is True)
        self.elapsed=max(0.,now-self.started)
        if core.running:
            node=core.tree['nodes'][core.node_id]
            key=core.epoch;played=max(0.,min(now-core.entered,node['duration']))
            prior=self.visits.get(key,0.)
            if key not in self.visits:self.path.append({'node':core.node_id,'level':node['level'],'played_seconds':0.})
            # Prefer event-level declared intensities; exposure is counted only while audio would play.
            events=node.get('events',[])
            if events:
                for i,e in enumerate(events):
                    intensity=self.tree.get('needs',{}).get(e['asset_id'],{}).get('intensity',node['level'])
                    overlap=max(0.,min(played,e['start']+e['duration'])-max(prior,e['start']))
                    self.dose+=overlap*(intensity/3.)**2
                    kind=self.tree.get('needs',{}).get(e['asset_id'],{}).get('kind','')
                    if kind=='impulse' and prior<=e['start']<played:self.impulses+=1
            else:self.dose+=max(0.,played-prior)*(node['level']/3.)**2
            self.visits[key]=max(prior,played);self.path[-1]['played_seconds']=played
        self.last=now
        return valid and group_response(targets,core.cohort)=='escaped'

    def finish(self,outcome,now):
        if self.done:return None
        self.done=True;elapsed=max(0.,now-self.started)
        dose=self.dose+3*self.impulses
        score=round(100*(.6*math.exp(-elapsed/60)+.4*math.exp(-dose/30)),3) if outcome=='escaped' else (0. if outcome=='not_escaped' else None)
        return {'trial_id':self.trial_id,'story_id':self.story.get('id','local'),
            'mode':self.mode,'outcome':outcome,'elapsed_seconds':round(elapsed,3),
            'escape_seconds':round(elapsed,3) if outcome=='escaped' else None,
            'stimulus_dose':round(self.dose,3),'impulse_count':self.impulses,'score':score,
            'volume_percent':self.volume,'path':self.path,'story':self.story,
            'initial_targets':self.initial_targets,'all_targets':sorted(self.targets),
            'score_definition':'success:100*(0.6*exp(-seconds/60)+0.4*exp(-(dose+3*impulses)/30)); failure:0; censored:null',
            'measurement_note':'Elapsed includes the 5-second missing-detection confirmation. Dose is a design proxy, not animal stress or measured SPL.'}
