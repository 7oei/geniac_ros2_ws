"""Checkpoint-only manual playback. Human thinking time never advances scenario time."""
from .campaign import Campaign

LABELS={'escaped':'完全退避（5秒確認済み）','retreated_nearby':'移動したが視界内',
        'no_escape':'動かなかった','observing':'未検出の確認待ち','unknown':'判定できない'}


class CheckpointSession:
    def __init__(self,tree,sink=None):
        self.sink=sink;self.campaign=Campaign(tree,False,sink=sink,mode='manual');self.tree=self.campaign.core.tree
        self.now=0.;self.phase='idle';self.events=[];self.count=1;self.targets=[]

    @property
    def core(self):return self.campaign.core

    @property
    def boundary(self):
        node=self.tree['nodes'][self.core.node_id]
        return float(node['duration'])

    def report(self):return {'epoch':self.core.epoch,'valid':True,'targets':self.targets}

    def start(self,count=1):
        if count not in (1,2,3):raise ValueError('Expected 1..3 deer')
        self.stop('restart');self.count=count;self.now=0.;self.events=[]
        self.campaign=Campaign(self.tree,True,sink=self.sink,mode='manual')
        self.targets=[{'id':str(i+1),'label':'observing','present':True,'stationary_seconds':2.} for i in range(count)]
        self.campaign.tick(0.,100.,self.report())
        self.phase='playing';self.events.append({'action':'start','node':self.core.node_id,'time':0.})

    def elapse(self,seconds):
        if self.phase!='playing':return False
        if seconds<0:raise ValueError('Negative elapsed time')
        self.now=min(self.now+seconds,self.core.entered+self.boundary)
        if self.campaign.trial and not self.campaign.trial.done:
            self.campaign.trial.observe(self.now,self.core,self.targets,valid=False)
        if self.now>=self.core.entered+self.boundary:
            self.phase='checkpoint';return True
        return False

    def answer(self,labels):
        if self.phase!='checkpoint':raise ValueError('State can only be entered at a reaction checkpoint')
        if len(labels)!=self.count or any(label not in LABELS for label in labels):raise ValueError('Select a state for each deer')
        self.targets=[{'id':str(i+1),'label':label,'present':label in ('no_escape','retreated_nearby'),
                       'stationary_seconds':2. if label=='no_escape' else 0.} for i,label in enumerate(labels)]
        before=self.core.node_id
        # No wall time spent answering is included in timing or stimulus scores.
        changed=self.campaign.tick(self.now,100+self.now,self.report())
        self.events.append({'action':'answer','time':self.now,'before':before,'after':self.core.node_id,
                            'labels':labels,'reason':self.core.reason,'evaluation':self.campaign.last_result})
        if not changed:raise RuntimeError('Expected a branch at the scene boundary')
        if self.core.running:self.phase='playing';return
        if all(label=='escaped' for label in labels):
            self.campaign.tick(self.now,100+self.now,self.report());self.phase='finished'
        elif any(label in ('unknown','observing') for label in labels):
            self.campaign.finish_trial('unknown',self.now);self.phase='finished'
        else:
            self.campaign.tick(self.now,100+self.now,self.report())
            self.phase='playing' if self.core.running else 'finished'

    def stop(self,reason='operator_stop'):
        self.campaign.stop(reason);self.phase='stopped'
