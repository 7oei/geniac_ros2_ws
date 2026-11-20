"""Require audible identity for principal actors, not generic footsteps alone."""
import json
import re
from .story_repair import LocalRepairError

# (actor identity, characteristic audible event). Generic rustle/footsteps never
# establish an animal's identity, even if labelled as that animal in prose.
RULES={
 'human':(r'人間|猟師|射手|作業員|警備員|hunter|shooter|person|human|operator|worker',r'声|会話|発話|speech|voice|talk|call'),
 'snowmobile':(r'スノーモービル|snowmobile',r'エンジン|走行|engine|driv|pass'),
 'buggy':(r'バギー|atv|buggy|quad',r'エンジン|走行|engine|driv|pass'),
 'chainsaw':(r'チェーンソー|chainsaw',r'エンジン|切|伐|engine|cut|saw'),
 'dog':(r'犬|dog|hound',r'吠|鳴|唸|うな|bark|growl|howl|whin|yelp'),
 'bear':(r'クマ|熊|bear',r'唸|うな|咆哮|鳴|growl|roar|huff'),
 'wolf':(r'狼|オオカミ|wolf|wolves',r'遠吠|吠|唸|鳴|howl|growl|bark'),
 'horse':(r'馬|horse',r'いなな|嘶|蹄|neigh|whinny|hoof'),
 'boar':(r'猪|イノシシ|boar',r'鳴|唸|鼻息|grunt|snort|squeal'),
 'drone':(r'ドローン|drone|quadcopter',r'飛|ローター|プロペラ|rotor|propeller|flying|flight|buzz'),
 'helicopter':(r'ヘリ|helicopter',r'飛|ローター|rotor|flying|flight|hover'),
 'mower':(r'草刈|刈払|mower|brush.?cutter',r'刈|エンジン|mow|cut|engine'),
 'heavy_equipment':(r'重機|掘削|ブルドーザー|excavator|bulldozer',r'エンジン|掘|稼働|走行|engine|dig|operat|driv'),
}


def matches(key,text):
    identity,event=RULES[key]
    text=text.lower().replace('_',' ')
    return bool(re.search(identity,text) and re.search(event,text))


def required(tree):
    story=tree.get('story',{})
    actor=story.get('arrival',{}).get('actor','')
    roles=story.get('variation',{}).get('roles',[])
    text=json.dumps([actor,roles],ensure_ascii=False).lower().replace('_',' ')
    keys=[key for key,(pattern,_) in RULES.items() if re.search(pattern,text)]
    return keys


def role_matches(key,need):
    if key=='human':return need.get('kind')=='voice' and need.get('speech_required') is True
    if need.get('kind')=='footsteps' and key in ('dog','bear','wolf','boar'):return False
    return matches(key,json.dumps({k:need.get(k) for k in ('description','queries')},ensure_ascii=False))


def validate(tree,manifest=None):
    for actor in required(tree):
        roles={r for r,n in tree.get('needs',{}).items() if role_matches(actor,n)}
        if manifest is not None and actor=='human':
            from .assets import speech_evidence
            roles={r for r in roles if speech_evidence(manifest.get('assets',{}).get(r,{}))}
        elif manifest is not None:
            roles={r for r in roles if matches(actor,json.dumps(
                {k:manifest.get('assets',{}).get(r,{}).get(k) for k in ('description','details','tags')},ensure_ascii=False))}
        # Require presence on every sustained-visible path; immediate escape is exempt.
        pending=[(tree['root'],False)];seen=set();missing=False
        while pending:
            key,heard=pending.pop()
            if (key,heard) in seen:continue
            seen.add((key,heard));node=tree['nodes'][key]
            cues=node.get('events') if manifest is not None and 'events' in node else node.get('cues',[])
            heard=heard or any(c.get('role',c.get('asset_id')) in roles and c.get('duration',0)>0 for c in cues)
            if node.get('terminal'):
                missing=missing or not heard;continue
            pending.extend((node['branches'][label],heard) for label in ('no_escape','retreated_nearby'))
        if not missing:continue
        if manifest is not None:raise ValueError('Missing verified characteristic recording for principal actor: '+actor)
        sound='core_'+actor
        paths=[f'/nodes/{k}/cues' for k,n in tree['nodes'].items() if not n.get('terminal') and n.get('stage')!='withdrawal']
        if roles:paths.extend('/needs/'+r for r in roles)
        elif len(tree['needs'])<12:paths.append('/needs/'+sound)
        raise LocalRepairError('Principal actor '+actor+' must have its own recognizable audible event on every visible-deer path. For dogs add actual barking/growling (kind voice, speech_required false), not footsteps/rustling. For other actors use their characteristic vocalization or operating sound. Add a need and reference it in an early cue, preserving existing sounds and story. Do not delete the actor to pass validation.',paths)
