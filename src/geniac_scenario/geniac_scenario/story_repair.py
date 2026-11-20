"""Apply bounded field patches to an existing design; never regenerate it on repair."""
import copy
import json


class LocalRepairError(ValueError):
    def __init__(self,message,paths):
        super().__init__(message);self.paths=list(dict.fromkeys(paths))


def canonical(tree):
    tree=copy.deepcopy(tree)
    for field in ('nodes','needs'):
        rows=tree.get(field)
        if isinstance(rows,list):
            if any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in rows):raise ValueError('Invalid design IDs')
            if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate design IDs')
            tree[field]={r['id']:{k:v for k,v in r.items() if k!='id'} for r in rows}
    for node in tree.get('nodes',{}).values():
        for cue in node.get('cues',[]):
            if 'sound_id' in cue:
                sound=cue.pop('sound_id')
                if 'role' in cue and cue['role']!=sound:raise ValueError('Conflicting sound references')
                cue['role']=sound
    return tree


def patch_schema(paths):
    return {'type':'object','properties':{'changes':{'type':'array','minItems':1,'maxItems':8,'items':{
        'type':'object','properties':{'path':{'type':'string','enum':paths},'value_json':{'type':'string'},
                                    'reason':{'type':'string'}},
        'required':['path','value_json','reason'],'additionalProperties':False}}},
        'required':['changes'],'additionalProperties':False}


def apply_patch(tree,response,allowed):
    if not isinstance(response,dict) or set(response)!={'changes'}:raise ValueError('Expected field patches, not a complete story')
    changes=response['changes']
    if not isinstance(changes,list) or not 1<=len(changes)<=8:raise ValueError('Expected 1..8 field patches')
    result=copy.deepcopy(tree);seen=set()
    for change in changes:
        if not isinstance(change,dict) or set(change)!={'path','value_json','reason'}:raise ValueError('Invalid patch shape')
        path=change['path']
        if path not in allowed or path in seen:raise ValueError('Patch is outside the diagnosed problem: '+str(path))
        seen.add(path)
        parts=path.lstrip('/').split('/');parent=result
        for part in parts[:-1]:parent=parent[int(part)] if isinstance(parent,list) else parent[part]
        key=int(parts[-1]) if isinstance(parent,list) else parts[-1]
        try:value=json.loads(change['value_json'])
        except json.JSONDecodeError:
            if not isinstance(parent.get(key) if isinstance(parent,dict) else parent[key],str):raise
            value=change['value_json']
        if isinstance(parent,list):parent[int(parts[-1])]=value
        else:parent[parts[-1]]=value
    return result
