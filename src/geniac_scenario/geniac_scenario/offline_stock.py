"""No paid calls: recombine validated local recordings within existing story structure."""
import copy
import json
from pathlib import Path
import yaml
from .assets import forbidden_material,human_speech_valid,manifest_context_valid
from .evolving import validate_climax,route_visible_to_attack
from .tree import runtime_tree, load_tree,audio_paths
from .prepare import compile_tree


def compose(root,history,weather):
    root=Path(root).resolve();sources=[]
    for row in history.rows():
        if row['status'] not in ('ready','used','obsolete') or not row.get('path'):continue
        try:
            path=Path(row['path']).resolve()
            if not path.is_relative_to(root):continue
            tree=runtime_tree(load_tree(path));audio_paths(tree,path.parent)
            if tree['story'].get('design_version',0)<3:continue
            validate_climax(tree)
            if tree['story']['weather']['surface']!=weather['surface']:continue
            manifest=yaml.safe_load((path.parent.parent/'manifest.yaml').read_text())
            if any(forbidden_material(a) or not Path(a['file']).is_file() for a in manifest['assets'].values()):continue
            if not human_speech_valid(tree,manifest) or not manifest_context_valid(tree,manifest):continue
            # Recombine originals, not a shrinking sequence of derivatives.
            if tree['story'].get('generation_basis')=='local recombination':continue
            sources.append((tree,manifest))
        except (OSError,ValueError,KeyError,TypeError,yaml.YAMLError):continue
    if not sources:raise ValueError('No compatible verified local materials for current weather')
    sequence=history.next_sequence();tree,manifest=copy.deepcopy(sources[(sequence-1)%len(sources)])
    from .speech_pool import expand_roles
    expand_roles(tree)
    parent=tree['story']['id'];variant=(sequence-1)//len(sources);optional_index=0
    # Optional ambience/voice layers can be omitted without inventing new actions or people.
    for node in tree['nodes'].values():
        if node.get('terminal'):continue
        node['duration']=node.get('cue_timeline_duration',node['duration'])
        node['min_dwell']=node.get('cue_timeline_min_dwell',node['min_dwell'])
        kept=[]
        for cue in node['cues']:
            need=tree['needs'][cue['role']]
            optional=not need.get('speech_required') and need['kind'] in ('voice','ambience') and need.get('event') not in ('attack','stop','exit','transport')
            omit=optional and ((variant>>optional_index)&1)
            if optional:optional_index+=1
            if not omit:kept.append(cue)
        if kept:node['cues']=kept
        node['narrative']='既存の行動順序を維持した素材構成：'+'、'.join(tree['needs'][c['role']]['description'] for c in node['cues'])
        node.pop('events',None)
    # Substitute only recordings already verified against the identical requirement.
    for role,need in tree['needs'].items():
        if need.get('speech_required'):
            from .speech_pool import select
            speech=select(root,need)
            if speech is not None:
                manifest['assets'][role]=speech
                continue
        matches=[]
        for source,assets in sources:
            for other,n in source['needs'].items():
                if (n.get('kind'),n.get('event'),n.get('queries'))==(need.get('kind'),need.get('event'),need.get('queries')):
                    asset=assets['assets'].get(other)
                    if asset and asset not in matches:matches.append(asset)
        if matches:manifest['assets'][role]=copy.deepcopy(matches[variant%len(matches)])
    used={c['role'] for n in tree['nodes'].values() for c in n.get('cues',[])}
    variation=tree['story'].get('variation',{})
    if not any(tree['needs'][r]['kind']=='voice' for r in used):variation['dialogue']='none'
    tree['story'].update(title=tree['story']['title']+'（既存素材構成）',weather=copy.deepcopy(weather),
        parent_id=parent,generation_basis='local recombination',strategy='local_recombine',
        change='有料APIを使わず、検証済み素材の組み合わせと背景音・声の重ね方を変更',local_variant=variant)
    for key in ('material_failure','preparation_failures','variation_signature'):tree['story'].pop(key,None)
    tree['story']['outline']=[{'node':k,'title':n.get('title'),'narrative':n.get('narrative'),'branches':n.get('branches')} for k,n in tree['nodes'].items()]
    route_visible_to_attack(tree);validate_climax(tree)
    return tree,manifest


def replenish_local(root,history,weather,count,progress):
    occupied=sum(r['status'] in ('ready','in_use') for r in history.rows(date=weather['date']))
    if occupied>=count:return
    tree,manifest=compose(root,history,weather)
    sid=history.draft(tree,weather)
    batch=Path(root)/('local-'+sid);batch.mkdir()
    try:
        (batch/'manifest.yaml').write_text(yaml.safe_dump(manifest,allow_unicode=True))
        path=compile_tree(tree,manifest,root,batch/'audio',progress=progress)
        history.publish(sid,path,load_tree(path))
    except Exception:
        history.fail_draft(sid)
        with history.connect() as c:c.execute("UPDATE stories SET status='unrealizable' WHERE id=? AND status='draft'",(sid,))
        raise
