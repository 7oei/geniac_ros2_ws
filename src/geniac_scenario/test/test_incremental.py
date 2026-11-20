import copy
import json
from test_evolving import design
from geniac_scenario.evolving import generate
from geniac_scenario.incremental import design_base,edit_paths
from geniac_scenario.story_repair import apply_patch


def test_improvement_uses_parent_patch_and_preserves_materials():
    source=design();source['story']['id']='parent'
    source['nodes']['arrival'].update(duration=2,min_dwell=2,cue_timeline_duration=6,events=[{}],audio='old.wav')
    before=copy.deepcopy(source);calls=[]
    changes={'changes':[{'path':'/story/premise','value_json':json.dumps('機械が別の配置で接近する'),'reason':'small improvement'},
                        {'path':'/story/variation','value_json':json.dumps(dict(source['story']['variation'],approach='sequential')),'reason':'change coordination'}]}
    cues=copy.deepcopy(source['nodes']['arrival']['cues']);cues[0]['start']=1
    changes['changes'].append({'path':'/nodes/arrival/cues','value_json':json.dumps(cues),'reason':'audible placement'})
    class Response:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(changes)}}]}
    def post(*a,**kw):calls.append(copy.deepcopy(kw['json']));return Response()
    result=generate({}, {'source_designs':{'parent':source}},2,{'OPENAI_API_KEY':'test'},post)
    assert len(calls)==1
    assert calls[0]['response_format']['json_schema']['name']=='incremental_story_edits'
    assert result['story']['parent_id']=='parent'
    assert result['story']['generation_basis']=='incremental parent edits'
    for role,need in source['needs'].items():
        for field,value in need.items():assert result['needs'][role][field]==value
    assert result['nodes']['arrival']['audio'] is None
    assert result['nodes']['arrival']['duration']==6
    assert source==before


def test_every_third_still_generates_full_story(monkeypatch):
    from geniac_scenario import exploration
    monkeypatch.setattr(exploration,'choose',lambda *a:{'element':'tractor','name':'トラクター'})
    source=design();calls=[]
    class Response:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(dict(design(),needs=dict(design()['needs'],motor=dict(design()['needs']['motor'],description='tractor driving'))))}}]}
    def post(*a,**kw):calls.append(kw['json']);return Response()
    result=generate({}, {'source_designs':{'parent':source}},3,{'OPENAI_API_KEY':'test'},post)
    assert calls[0]['response_format']['json_schema']['name']=='branching_acoustic_story'
    assert result['story']['strategy']=='explore'


def test_edit_paths_allow_one_addition_but_not_replacing_graph():
    tree=design_base(design());paths=edit_paths(tree)
    assert '/nodes' not in paths and '/needs' not in paths
    assert '/story/direction' not in paths
    result=apply_patch(tree,{'changes':[{'path':'/nodes/added_scene','value_json':json.dumps({'terminal':True,'title':'追加'}),'reason':'add'}]},paths)
    assert len(result['nodes'])==len(tree['nodes'])+1
    assert result['nodes']['arrival']==tree['nodes']['arrival']


def test_incremental_accepts_small_audible_placement_change():
    from geniac_scenario.incremental import validate_improvement
    from geniac_scenario.evolving import validate_variation
    base=design();validate_variation(base,{})
    changed=copy.deepcopy(base);changed['nodes']['arrival']['cues'][0]['start']=1
    validate_variation(changed,{'recent_concepts':[base['story']]},incremental=True)
    validate_improvement(changed,base)


def test_incremental_rejects_prose_and_length_only_with_repair_paths():
    import pytest
    from geniac_scenario.incremental import validate_improvement
    from geniac_scenario.story_repair import LocalRepairError
    base=design();changed=copy.deepcopy(base)
    changed['story']['title']='別タイトル';changed['nodes']['arrival']['duration']=7
    changed['nodes']['arrival']['cues'][0]['gain_db']=-10
    with pytest.raises(LocalRepairError) as error:validate_improvement(changed,base)
    assert '/nodes/arrival/cues' in error.value.paths
