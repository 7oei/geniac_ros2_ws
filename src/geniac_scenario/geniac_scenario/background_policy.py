"""Prevent vehicle ambience from outliving its audible action."""
import re

VEHICLE=re.compile(r'\b(vehicle|engine|motor|van|truck|car|tractor|bulldozer)\b|車両|軽バン|トラック|エンジン|車体|自動車',re.I)
OFF=re.compile(r'engine.{0,20}(off|stop)|エンジン.{0,12}(切|停止)|エンジン停止',re.I)
RUNNING=re.compile(r'\bidl(?:e|ing)\b|engine.{0,20}running|エンジン.{0,12}(回り|回って|かか|稼働)|アイドリング',re.I)
START=re.compile(r'engine.{0,20}(start|restart)|エンジン.{0,12}(始動|かけ)|再始動',re.I)

def text(need):return ' '.join([need.get('description',''),*need.get('queries',[])])

def apply_background_policy(tree):
    needs=tree.get('needs',{});nodes=tree['nodes']
    roles={k for k,n in needs.items() if n.get('kind')=='ambience' and VEHICLE.search(text(n))}
    if not roles:return tree
    incoming={k:set() for k in nodes}
    for key,node in nodes.items():
        for dest in node.get('branches',{}).values():
            if dest in incoming:incoming[dest].add(key)
    def ancestors(key,seen=None):
        seen=set() if seen is None else seen
        for parent in incoming[key]:
            if parent not in seen:
                seen.add(parent);ancestors(parent,seen)
        return seen
    def actions(node):
        return ' '.join([node.get('narrative',''),node.get('action',''),
                         *[text(needs.get(c['role'],{})) for c in node.get('cues',[]) if c['role'] not in roles]])
    removed=[]
    for key,node in nodes.items():
        if node.get('terminal'):continue
        own=actions(node)
        stopped=any(OFF.search(actions(nodes[k])) for k in ancestors(key)|{key})
        running=bool(RUNNING.search(own))
        allowed=node.get('stage')=='transport' or (running and (not stopped or START.search(own)))
        old=node.get('cues',[])
        retained=[c for c in old if c['role'] not in roles or allowed]
        if len(retained)==len(old):continue
        if not retained:raise ValueError('Scene '+key+' contains only unrelated vehicle ambience; add a coherent foreground action')
        removed.append(key);node['cues']=retained;node.pop('events',None)
    if removed:
        tree['background_policy']={'version':1,'removed_vehicle_background_nodes':removed}
        used={c['role'] for n in nodes.values() for c in n.get('cues',[])}
        for role in roles-used:needs.pop(role)
    return tree
