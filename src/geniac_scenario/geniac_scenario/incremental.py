"""Reuse a complete design and request only a small set of edits."""
import copy


def design_base(source):
    tree=copy.deepcopy(source)
    fields=('title','premise','direction','change','arrival','variation','design_version')
    tree['story']={k:v for k,v in tree['story'].items() if k in fields}
    for node in tree['nodes'].values():
        for field in ('events','cue_timeline_min_dwell'):
            node.pop(field,None)
        if node.get('terminal'):continue
        end=max((c['start']+c['duration'] for c in node['cues']),default=6)
        node['duration']=max(6,node.pop('cue_timeline_duration',node['duration']),end)
        node['min_dwell']=node['duration'];node['audio']=None
    return tree


def edit_paths(tree):
    paths=['/story/'+key for key in ('title','premise','change','arrival','variation')]
    for key,node in tree['nodes'].items():
        if node.get('terminal'):continue
        paths.extend(f'/nodes/{key}/{field}' for field in ('title','narrative','location','action','cause','cues','branches'))
    paths.extend('/needs/'+key for key in tree['needs'])
    # A single optional scene/material can be added without replacing collections.
    if len(tree['nodes'])<16:
        key='added_scene'
        while key in tree['nodes']:key+='x'
        paths.append('/nodes/'+key)
    if len(tree['needs'])<12:
        key='added_sound'
        while key in tree['needs']:key+='x'
        paths.append('/needs/'+key)
    return paths


def audible_plan(tree):
    """Compare playback instructions; prose, gains and duration alone are not novelty."""
    def walk(key,seen):
        if key in seen:return ('cycle',)
        node=tree['nodes'][key]
        if node.get('terminal'):return ('end',)
        cues=[]
        for cue in sorted(node.get('cues',[]),key=lambda c:(c['start'],c['role'])):
            need=tree['needs'][cue['role']]
            cues.append((cue['start'],need.get('kind'),need.get('event'),
                         tuple(sorted(q.strip().lower() for q in need.get('queries',[]))),
                         need.get('speech_required',False)))
        return (tuple(cues),tuple((label,walk(dest,seen|{key})) for label,dest in sorted(node['branches'].items())))
    return walk(tree['root'],set())


def validate_improvement(tree,base):
    from .story_repair import LocalRepairError
    if audible_plan(tree)!=audible_plan(base):return
    paths=[p for p in edit_paths(tree) if p.endswith('/cues') or p.startswith('/needs/')]
    paths+=['/story/variation','/story/change']
    raise LocalRepairError('Incremental edit did not change the audible plan. Keep this story and make one small real change: shift an existing cue placement, reorder overlapping actions, or add a characteristic voice/sound cue. Title, narrative, cast labels, volume and duration alone do not count. Do not regenerate the whole story.',paths)
