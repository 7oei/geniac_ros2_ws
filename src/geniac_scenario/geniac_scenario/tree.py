"""Validated, bounded, precomputed scenario DAG. No generation in the runtime."""
from functools import lru_cache
from copy import deepcopy
import math
import random
from pathlib import Path
import uuid
import yaml
from geniac_behavior.core import group_response

RESPONSES = ('escaped', 'retreated_nearby', 'no_escape', 'unknown')

class UniqueLoader(yaml.SafeLoader):
    pass

def _mapping(loader,node,deep=False):
    result={}
    for k,v in node.value:
        key=loader.construct_object(k,deep=deep)
        if key in result:raise ValueError('Duplicate YAML key')
        result[key]=loader.construct_object(v,deep=deep)
    return result
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,_mapping)

def load_tree(path):
    return validate_tree(yaml.load(Path(path).read_text(), Loader=UniqueLoader))

def validate_tree(tree):
    if not isinstance(tree,dict) or tree.get('version')!=1:
        raise ValueError('Unsupported tree version')
    nodes=tree.get('nodes')
    if not isinstance(nodes,dict) or not 1<=len(nodes)<=32 or tree.get('root') not in nodes:
        raise ValueError('Invalid nodes/root')
    for key,n in nodes.items():
        if not isinstance(key,str) or not isinstance(n,dict):raise ValueError('Invalid node')
        if n.get('terminal') is True:continue
        for field in ('duration','min_dwell','level'):
            if type(n.get(field)) not in (float,int) or not math.isfinite(n[field]):raise ValueError('Invalid numeric field')
        if not 0<n['duration']<=60 or not 0<=n['min_dwell']<=n['duration'] or not 0<=n['level']<=3:
            raise ValueError('Invalid node bounds')
        if set(n.get('branches',{}))!=set(RESPONSES) or any(v not in nodes for v in n['branches'].values()):
            raise ValueError('Every response needs an existing branch')
        if n.get('audio') is not None and (not isinstance(n['audio'],str) or not n['audio']):raise ValueError('Invalid audio path')
    for n in nodes.values():
        if n.get('terminal'):continue
        unknown = nodes[n['branches']['unknown']]
        if not unknown.get('terminal'):
            raise ValueError('Unknown response must terminate without escalation')
        escaped = nodes[n['branches']['escaped']]
        if not escaped.get('terminal') and escaped['level'] > n['level']:
            raise ValueError('Escape cannot increase scenario intensity')
    visiting=set(); visited=set()
    def walk(key):
        if key in visiting:raise ValueError('Scenario tree must be acyclic')
        if key in visited:return
        visiting.add(key)
        if not nodes[key].get('terminal'):
            for target in nodes[key]['branches'].values():walk(target)
        visiting.remove(key);visited.add(key)
    walk(tree['root'])
    if visited!=set(nodes):raise ValueError('Unreachable scenario node')
    @lru_cache(None)
    def longest(key):
        n=nodes[key]
        return 0 if n.get('terminal') else n['duration']+max(longest(x) for x in n['branches'].values())
    if longest(tree['root'])>180:raise ValueError('Scenario exceeds 180 second episode budget')
    return tree

def runtime_tree(tree):
    """Adapt legacy escape tails to immediate termination without changing stock files."""
    result=deepcopy(validate_tree(tree))
    if result.get('needs'):
        from .evolving import route_visible_to_attack
        route_visible_to_attack(result)
    nodes=result['nodes']
    for node in nodes.values():
        if node.get('terminal'):
            node.pop('branches',None)
            continue
        destination=node['branches']['escaped']
        while not nodes[destination].get('terminal'):
            destination=nodes[destination]['branches']['escaped']
        node['branches']['escaped']=destination
    reachable=set()
    def visit(key):
        if key in reachable:return
        reachable.add(key)
        for dest in nodes[key].get('branches',{}).values():visit(dest)
    visit(result['root'])
    result['nodes']={key:node for key,node in nodes.items() if key in reachable}
    return validate_tree(result)

def audio_paths(tree,root,require=True):
    root=Path(root).resolve(); result={}
    for key,n in tree['nodes'].items():
        if n.get('terminal'):continue
        name=n.get('audio')
        if not name:
            if require:raise ValueError('Missing pre-rendered audio for '+key)
            continue
        path=(root/name).resolve()
        if not path.is_relative_to(root):raise ValueError('Audio path escapes tree directory')
        if require and not path.is_file():raise ValueError('Missing audio file for '+key)
        result[key]=path
    return result

class Engine:
    def __init__(self,tree):
        self.tree=runtime_tree(tree)
        self.node_id=None;self.running=False;self.cohort=set();self.epoch='';self.entered=0.;self.entered_stamp=0.
        self.reason='idle';self.transitions=[];self.sequence=0;self.episode=''
        self.repeat_until=None;self.repeat_gap_seconds=0.;self.repeat_remaining_seconds=0.

    def _enter(self,key,now,stamp,reason):
        self.repeat_until=None;self.repeat_remaining_seconds=0.
        self.node_id=key;self.entered=now;self.entered_stamp=stamp;self.reason=reason
        self.sequence+=1;self.epoch=f'{self.episode}:{self.sequence}'
        self.running=not self.tree['nodes'][key].get('terminal',False)
        self.transitions.append({'node':key,'stamp':stamp,'reason':reason})
        self.transitions=self.transitions[-32:]

    def start(self,now,stamp,cohort):
        if self.running:raise ValueError('Scenario already running')
        if not cohort:raise ValueError('No fresh target cohort')
        self.cohort=set(cohort);self.episode=uuid.uuid4().hex;self.sequence=0;self.transitions=[]
        self._enter(self.tree['root'],now,stamp,'start')

    def stop(self,reason='operator_stop'):
        self.running=False;self.reason=reason

    def tick(self,now,stamp,report=None):
        if not self.running:return False
        n=self.tree['nodes'][self.node_id];label='unknown'
        if report and report.get('epoch')==self.epoch and report.get('valid') is True:
            targets=report.get('targets',[])
            # Retain late arrivals even during their five-second disappearance check.
            self.cohort.update(t['id'] for t in targets if t.get('present') is True)
            label=group_response(targets, self.cohort)
        elapsed=now-self.entered
        if elapsed<0:
            self.stop('clock_reset');return True
        if label=='escaped':
            self._enter(n['branches']['escaped'],now,stamp,label);return True
        if self.repeat_until is not None:
            self.repeat_remaining_seconds=max(0.,self.repeat_until-now)
            if now<self.repeat_until:
                self.reason='repeat_interval';return False
            if label not in ('no_escape','retreated_nearby'):
                self.reason='awaiting_behavior';return False
            self._enter(self.node_id,now,stamp,'repeat_final_'+label);return True
        if now>=self.entered+n['min_dwell'] and label!='unknown':
            destination=n['branches'][label]
            if (label in ('no_escape','retreated_nearby') and self.tree['nodes'][destination].get('terminal')
                    and not n.get('escape_tail') and n.get('stage')!='withdrawal'):
                # Runtime repetition keeps the generated design acyclic. A new epoch
                # requires a new reaction after every replay, including the same node.
                maximum=float(self.tree.get('repeat_gap_max_seconds',0.))
                self.repeat_gap_seconds=round(random.uniform(0.,maximum),3) if maximum>0 else 0.
                if self.repeat_gap_seconds>0:
                    self.repeat_until=now+self.repeat_gap_seconds
                    self.repeat_remaining_seconds=self.repeat_gap_seconds
                    self.reason='repeat_interval';return True
                self._enter(self.node_id,now,stamp,'repeat_final_'+label);return True
            self._enter(destination,now,stamp,label);return True
        if now>=self.entered+n['duration']:
            if self.tree.get('wait_for_observation') and report and report.get('epoch')==self.epoch and report.get('valid') is True:
                labels={t['id']:t.get('label') for t in report.get('targets',[])}
                if (self.cohort and all(labels.get(k) in ('observing','escaped','no_escape','retreated_nearby') for k in self.cohort)
                        and any(labels.get(k)=='observing' for k in self.cohort)):
                    self.reason='awaiting_behavior';return False
            self._enter(n['branches']['unknown'],now,stamp,'timeout_unknown');return True
        return False

    def state(self):
        return {'version':1,'running':self.running,'node':self.node_id,'epoch':self.epoch,
                'entered_stamp':self.entered_stamp,'targets':sorted(self.cohort),
                'reason':self.reason,'transitions':self.transitions,
                'repeat_gap_seconds':self.repeat_gap_seconds,'repeat_remaining_seconds':self.repeat_remaining_seconds}
