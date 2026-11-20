"""Complete acoustic hunting stories, prepared before sensor-driven playback."""
import copy
from .tree import validate_tree

FOOTSTEPS = {'snow':('雪を踏む足音','footsteps walking snow'),
             'rain':('水たまりを歩く足音','footsteps walking puddles water'),
             'grass':('草をかき分ける足音','footsteps walking grass')}


def story_tree(weather, opponent='human', variant=0):
    if opponent not in ('human','bear'):raise ValueError('Unknown opponent')
    surface=weather['surface']
    if surface not in FOOTSTEPS:raise ValueError('Unknown surface')
    foot,query=FOOTSTEPS[surface]
    human=opponent=='human'
    actor='猟師' if human else '熊'
    needs={'footsteps':{'description':foot,'query':query},
           'search':{'description':'衣服と道具の擦れる音' if human else '熊が匂いを嗅ぐ息遣い',
                     'query':'clothes rustling jacket' if human else 'bear breathing sniff'},
           'prepare':{'description':'銃を構える際の金属と衣擦れ' if human else '熊の低いうなり声',
                      'query':'rifle handling foley' if human else 'bear growl'},
           'attack':{'description':'単発の銃声' if human else '熊の突進とうなり声',
                     'query':'single rifle gunshot' if human else 'bear roar'}}
    nodes={}
    def node(key,title,narrative,duration,level,cues,next_node,partial='watch'):
        nodes[key]={'title':title,'narrative':narrative,'duration':duration,'min_dwell':duration,
                    'level':level,'audio':None,'cues':cues,
                    'branches':{'escaped':'withdraw','retreated_nearby':partial,'no_escape':next_node,'unknown':'uncertain_end'}}
    def cue(role,start,length,gain):return {'role':role,'start':start,'duration':length,'gain_db':gain}
    # Variants alter the distance/timing of an already coherent story, never its response policy.
    far=-22-2*(variant%3)
    node('arrival',f'{actor}が森へ入る',f'鹿を探す{actor}が遠くから近づく。{foot}が小さく聞こえる。',8,1,
         [cue('footsteps',0,6,far)],'search')
    node('search','鹿の気配を探す',f'{actor}が立ち止まり、気配を探してから数歩進む。',8,1,
         [cue('search',0,2,-20),cue('footsteps',3,4,-18)],'approach')
    node('approach','鹿へ忍び寄る',f'鹿を見つけた{actor}が歩みを遅くして距離を詰める。',8,2,
         [cue('footsteps',0,5,-14),cue('search',5.5,1.5,-18)],'prepare')
    node('watch','動いた鹿を見守る',f'{actor}は足を止めて様子を見る。鹿が離れ続ければ追跡を諦める。',6,1,
         [cue('search',0,2,-24)],'prepare','withdraw')
    node('prepare','狩りの直前', '猟師が銃を構えて待つ。発砲前に鹿の反応をもう一度確認する。' if human
         else '熊が低くうなり、突進する前に鹿の反応を確認する。',6,2,
         [cue('prepare',0,3,-16)],'attack','withdraw')
    node('attack','単発の発砲' if human else '熊が突進する',
         '直前の分岐で逃げないと判定された場合だけ、単発の銃声を鳴らす。' if human
         else '直前の分岐で逃げないと判定された場合だけ、突進のうなり声を鳴らす。',2,3,
         [cue('attack',0,1.5,-16)],'retry_end','retry_end')
    node('withdraw','追跡をやめて遠ざかる',f'鹿を追うのをやめ、{actor}の{foot}が遠ざかる。発砲はしない。',6,0,
         [cue('footsteps',0,2,-24),cue('footsteps',3,2,-34)],'retry_end','retry_end')
    nodes['withdraw']['branches']['escaped']='escaped_end'
    nodes['withdraw']['escape_tail']=True
    for key,title in [('escaped_end','完全退避・終了'),('retry_end','まだ視界内・次の物語を最初から'),('uncertain_end','反応確認待ち')]:
        nodes[key]={'terminal':True,'title':title}
    tree={'version':1,'root':'arrival','story':{'opponent':opponent,'variant':variant,'weather':copy.deepcopy(weather),
           'premise':f'森にいる鹿を狩ろうとする{actor}。鹿が退避したら狩りを中止する。'},
          'interrupt_on_escape':True,'needs':needs,'nodes':nodes}
    return validate_tree(tree)


def attach_events(tree,manifest):
    """Loop only continuous ambience/footsteps; discrete actions play once per cue."""
    tree=copy.deepcopy(tree)
    for node in tree['nodes'].values():
        if node.get('terminal'):continue
        events=[];unused=[]
        for cue in node['cues']:
            asset=manifest['assets'][cue['role']];length=float(asset['duration'])
            if length<=0:raise ValueError('Empty recording')
            remaining=cue['duration'];offset=cue['start']
            need=tree.get('needs',{}).get(cue['role'],{})
            loopable=(need.get('kind') in ('footsteps','ambience')
                      and need.get('event') not in ('stop','exit','transport','action','attack'))
            if not loopable:
                remaining=min(remaining,length)
                if remaining<cue['duration']:
                    unused.append((cue['start']+remaining,cue['start']+cue['duration']))
            while remaining>1e-6:
                take=min(length,remaining)
                events.append({'asset_id':cue['role'],'start':offset,'source_start':0.,'duration':take,'gain_db':cue['gain_db']})
                offset+=take;remaining-=take
                if len(events)>32:raise ValueError('Recording too short for story')
        # Reclaim only unused tails of cue windows. Preserve explicit pauses and
        # overlapping sounds; shortening one cue must not cut another recording.
        boundaries=sorted({v for pair in unused for v in pair} |
                          {v for e in events for v in (e['start'],e['start']+e['duration'])})
        removed=[]
        for left,right in zip(boundaries,boundaries[1:]):
            middle=(left+right)/2
            if (any(a<=middle<b for a,b in unused) and
                    not any(e['start']<=middle<e['start']+e['duration'] for e in events)):
                removed.append((left,right))
        def mapped(t):return t-sum(max(0.,min(t,b)-a) for a,b in removed if t>a)
        for event in events:event['start']=mapped(event['start'])
        if 'duration' in node:
            original=node.setdefault('cue_timeline_duration',node['duration'])
            dwell=node.setdefault('cue_timeline_min_dwell',node.get('min_dwell',original))
            node['duration']=mapped(original);node['min_dwell']=mapped(dwell)
        node['events']=events
    return tree
