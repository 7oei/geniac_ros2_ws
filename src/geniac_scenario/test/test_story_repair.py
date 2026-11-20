import copy
import json
import pytest
from test_evolving import design
from geniac_scenario.evolving import generate
from geniac_scenario.story_repair import apply_patch


def patch(path,value):
    return {'changes':[{'path':path,'value_json':json.dumps(value),'reason':'fix diagnosed error'}]}


def test_patch_is_atomic_and_preserves_unrelated_fields():
    tree=design();before=copy.deepcopy(tree)
    path='/nodes/arrival/cues/0/role'
    fixed=apply_patch(tree,patch(path,'bang'),[path])
    assert tree==before
    assert fixed['story']==before['story']
    assert fixed['nodes']['impact']==before['nodes']['impact']
    with pytest.raises(ValueError):apply_patch(tree,patch('/story/title','rewrite'),[path])
    with pytest.raises(ValueError):apply_patch(tree,design(),[path])


def test_generation_repairs_reference_without_regenerating_story():
    tree=design();tree['nodes']['arrival']['cues'][0]['role']='actor'
    responses=[tree,patch('/nodes/arrival/cues/0/role','motor')];calls=[]
    class Response:
        status_code=200
        def __init__(self,value):self.value=value
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(self.value)}}]}
    def post(url,**kwargs):
        calls.append(copy.deepcopy(kwargs['json']));return Response(responses.pop(0))
    fixed=generate({}, {},1,{'OPENAI_API_KEY':'test'},post)
    assert len(calls)==2
    assert calls[1]['response_format']['json_schema']['name']=='story_field_repairs'
    assert json.loads(calls[1]['messages'][1]['content'])['allowed_paths']==['/nodes/arrival/cues/0/role']
    assert fixed['nodes']['arrival']['cues'][0]['role']=='motor'
    for key,value in tree['story'].items():assert fixed['story'][key]==value
    assert len(fixed['story']['validation_repairs'])==1


def test_bad_patch_does_not_replace_draft_and_can_retry():
    tree=design();tree['nodes']['arrival']['cues'][0]['role']='actor'
    replies=[tree,patch('/story/title','unrelated'),patch('/nodes/arrival/cues/0/role','motor')]
    class Response:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(replies.pop(0))}}]}
    fixed=generate({}, {},1,{'OPENAI_API_KEY':'test'},lambda *a,**k:Response())
    assert fixed['story']['title']==tree['story']['title']
    assert len(fixed['story']['validation_repairs'])==1


def test_attack_followup_is_locally_repairable():
    from geniac_scenario.evolving import validate_design
    from geniac_scenario.story_repair import LocalRepairError
    tree=design()
    tree['nodes']['first_attack']=copy.deepcopy(tree['nodes']['impact'])
    tree['nodes']['arrival']['branches']['no_escape']='first_attack'
    tree['nodes']['first_attack']['branches']['no_escape']='impact'
    with pytest.raises(LocalRepairError) as err:validate_design(copy.deepcopy(tree),require_arrival=True)
    assert err.value.paths==['/nodes/first_attack/branches/no_escape']
    fixed=apply_patch(tree,patch(err.value.paths[0],'end'),err.value.paths)
    validate_design(fixed,require_arrival=True)


def test_failed_material_repairs_only_search_description():
    from geniac_scenario.evolving import validate_material_history
    from geniac_scenario.story_repair import LocalRepairError
    tree=design();context={'material_failures':[{'need':copy.deepcopy(tree['needs']['motor']),'reason':'No verified recording'}]}
    with pytest.raises(LocalRepairError) as err:validate_material_history(tree,context)
    assert set(err.value.paths)=={'/needs/motor/queries','/needs/motor/description'}
    changes=patch('/needs/motor/queries',['electric machinery driving'])
    changes['changes']+=patch('/needs/motor/description','移動する作業機械のモーター録音')['changes']
    fixed=apply_patch(tree,changes,err.value.paths)
    validate_material_history(fixed,context)
    assert fixed['nodes']==tree['nodes']
    assert fixed['needs']['motor']['kind']==tree['needs']['motor']['kind']


def test_new_search_terms_are_allowed_without_renaming_physical_sound():
    from geniac_scenario.evolving import validate_material_history
    t=design();context={'material_failures':[{'need':copy.deepcopy(t['needs']['motor'])}]}
    t['needs']['motor']['queries']=['electric motor driving']
    validate_material_history(t,context)


def test_plain_string_patch_is_accepted_only_for_string_field():
    tree=design()
    change=patch('/nodes/arrival/branches/escaped','end')
    change['changes'][0]['value_json']='end'
    fixed=apply_patch(tree,change,['/nodes/arrival/branches/escaped'])
    assert fixed['nodes']['arrival']['branches']['escaped']=='end'
    change['changes'][0]['path']='/nodes/arrival/duration'
    with pytest.raises(ValueError):apply_patch(tree,change,['/nodes/arrival/duration'])
