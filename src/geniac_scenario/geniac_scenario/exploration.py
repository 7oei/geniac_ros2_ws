"""Choose underrepresented audible threats using the complete story history."""
import json
import random
import re
from collections import Counter

# Seeds for exploration, not assertions about real-world deterrence efficacy.
ELEMENTS={
 'hunting_dog':('猟犬・犬の群れ',r'猟犬|犬の|吠え|\bdogs?\b|\bhounds?\b|barking'),
 'bear':('クマ',r'クマ|熊|\bbear\b'),
 'wolf':('狼・遠吠え',r'狼|オオカミ|\bwolf\b|\bwolves\b'),
 'heavy_equipment':('掘削機・ブルドーザー',r'重機|掘削|ブルドーザー|excavator|bulldozer'),
 'mower':('草刈り機・刈払機',r'草刈|刈払|mower|brush.?cutter'),
 'helicopter':('ヘリコプター',r'ヘリ|helicopter'),
 'snowmobile':('スノーモービル',r'スノーモービル|snowmobile'),
 'buggy':('バギー・四輪ATV',r'バギー|\batv\b|buggy|quad.?bike'),
 'drone':('ドローン',r'ドローン|\bdrone\b|quadcopter'),
 'chainsaw':('林業作業・チェーンソー',r'チェーンソー|chainsaw'),
 'tractor':('農業用トラクター',r'トラクター|tractor'),
 'motorcycle':('オフロードバイク',r'バイク|motorcycle|dirt.?bike'),
 'horse':('馬・騎馬の接近',r'騎馬|馬の|horse|hoof'),
 'boar':('イノシシ',r'イノシシ|猪|\bboar\b'),
 'train':('近隣線路からの列車',r'列車|鉄道|\btrain\b|railway'),
 'logging':('伐採・倒木',r'伐採|倒木|tree.?fall|logging'),
 'air_compressor':('工事用コンプレッサー・空気工具',r'コンプレッサー|空気工具|compressor|pneumatic'),
 'truck':('トラック',r'トラック|\btruck\b'),
}


def elements(tree):
    # Only narrative and actually referenced recordings count, never suggestions/history.
    story=tree.get('story',{})
    narrative={k:story.get(k) for k in ('title','premise','arrival','variation')}
    roles={c.get('role',c.get('sound_id')) for n in tree.get('nodes',{}).values() for c in n.get('cues',[])}
    audio=[n for k,n in tree.get('needs',{}).items() if k in roles]
    text=json.dumps([narrative,audio],ensure_ascii=False).lower()
    return [key for key,(_,pattern) in ELEMENTS.items() if re.search(pattern,text)]


def history_summary(trees):
    counts=Counter()
    for tree in trees:counts.update(elements(tree))
    return dict(counts)


def choose(context,weather):
    counts=context.get('exploration_counts',{})
    eligible=[k for k in ELEMENTS if k!='snowmobile' or weather.get('surface')=='snow']
    lowest=min(counts.get(k,0) for k in eligible)
    candidates=[k for k in eligible if counts.get(k,0)==lowest]
    key=random.choice(candidates)
    return {'element':key,'name':ELEMENTS[key][0],'prior_count':counts.get(key,0),
            'new_element':counts.get(key,0)==0,
            'history_counts':counts,
            'requirement':'Make this element central to causal action AND an actually referenced sound cue. Add a coherent previously unused element when possible. You may combine it with another original threat outside the examples; examples are not an exhaustive list. Do not substitute a drone. Do not merely mention the element in prose. Use physically obtainable recordings; fictional route assumptions must be explicit. A threat is a hypothesis, not a proven deterrent. Preserve escape/visible-deer branching constraints.'}


def validate(tree,plan):
    key=plan['element'];pattern=ELEMENTS[key][1]
    roles={c['role'] for n in tree['nodes'].values() for c in n.get('cues',[])}
    if not any(re.search(pattern,json.dumps(tree['needs'][r],ensure_ascii=False).lower()) for r in roles):
        raise ValueError('Exploration must include an audible '+plan['name']+' action, not a name-only change')
