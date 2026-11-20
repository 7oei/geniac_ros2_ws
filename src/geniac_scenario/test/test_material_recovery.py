import copy
import pytest
from geniac_scenario import stock,material_recovery as recovery


def tree():
    return {'story':{'id':'same-story','weather':{'surface':'snow'}},
        'needs':{'shot':{'kind':'impulse','event':'attack','intensity':3,'description':'single rifle shot','queries':['rifle gunshot']}},
        'nodes':{'scene':{'title':'発砲','cues':[{'role':'shot'}],'branches':{'escaped':'end'},'duration':2},'end':{'terminal':True}}}


def run(tmp_path,monkeypatch,answers,fetch):
    t=tree();calls=[]
    def ask(stage,payload,config):calls.append(stage);return answers[stage]
    monkeypatch.setattr(recovery,'ask',ask);monkeypatch.setattr(stock,'fetch_alternative',fetch)
    failure=stock.MaterialUnavailable('shot',t['needs']['shot'],['rifle gunshot'],'No verified recording')
    return t,calls,lambda:stock.recover_material(t,'shot',['rifle gunshot'],.5,tmp_path,'token',{'OPENAI_API_KEY':'test'},tmp_path,failure)


def test_query_recovery_keeps_same_story_and_graph(tmp_path,monkeypatch):
    t,calls,retry=run(tmp_path,monkeypatch,{'queries':{'queries':['rifle discharge']}},lambda *a:{'id':'new'})
    nodes=copy.deepcopy(t['nodes']);assert retry()['id']=='new'
    assert t['nodes']==nodes and t['story']['id']=='same-story' and calls==['queries']
    assert t['needs']['shot']['event']=='attack'


def test_local_scene_repair_only_after_query_search_fails(tmp_path,monkeypatch):
    attempts=[]
    def fetch(need,queries,*args):
        attempts.append(queries)
        if queries==['rifle discharge']:raise stock.MaterialUnavailable('shot',need,queries,'No verified recording')
        return {'id':'found'}
    answers={'queries':{'queries':['rifle discharge']},
        'scene':{'description':'A single rifle report','queries':['single rifle report'],
                 'scenes':{'scene':{'title':'単発の銃声'}}},'check':{'compatible':True}}
    t,calls,retry=run(tmp_path,monkeypatch,answers,fetch)
    assert retry()['id']=='found' and calls==['queries','scene','check']
    assert t['nodes']['scene']['title']=='単発の銃声'
    assert t['nodes']['scene']['branches']=={'escaped':'end'} and t['nodes']['scene']['duration']==2
    assert t['needs']['shot']['event']=='attack' and t['needs']['shot']['kind']=='impulse'


def test_incoherent_repair_does_not_change_tree(tmp_path,monkeypatch):
    def missing(need,queries,*args):raise stock.MaterialUnavailable('shot',need,queries,'No verified recording')
    answers={'queries':{'queries':['rifle discharge']},'scene':{'description':'metal impact','queries':['metal impact'],
             'scenes':{}},'check':{'compatible':False}}
    t,calls,retry=run(tmp_path,monkeypatch,answers,missing);original=copy.deepcopy(t)
    with pytest.raises(stock.MaterialUnavailable) as failure:retry()
    assert t==original and len(failure.value.failure['recovery_attempts'])==2
    assert calls==['queries','scene','check']


def test_local_edit_cannot_change_edges_or_other_scenes():
    proposal={'description':'rifle report','queries':['rifle report'],'scenes':{'scene':{'branches':{}}}}
    with pytest.raises(ValueError):recovery.local_edit(tree(),'shot',proposal)
    proposal['scenes']={'end':{'title':'changed'}}
    with pytest.raises(ValueError):recovery.local_edit(tree(),'shot',proposal)


def test_search_does_not_spend_entire_budget_on_first_query(tmp_path,monkeypatch):
    import numpy as np
    calls=[]
    def search(query,key):
        calls.append(query)
        return [{'id':query+str(i),'duration':1} for i in range(10)]
    monkeypatch.setattr(stock,'search',search)
    monkeypatch.setattr(stock,'verify_candidate',lambda need,item,config:
                        {'method':'test','policy_version':3} if item['id'].startswith('synonym') else None)
    monkeypatch.setattr(stock,'download',lambda item,path:dict(item,file=str(path)))
    monkeypatch.setattr(stock,'decode',lambda path:np.ones(24000))
    result=stock.fetch_alternative(tree()['needs']['shot'],['original','synonym'],.5,tmp_path,'token',{},'shot')
    assert result['id']=='synonym0' and calls==['original','synonym']


def test_scene_request_restricts_model_to_affected_node_ids():
    import json
    calls=[]
    class Response:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'description':'single rifle report','queries':['rifle report'],'scenes':{}})}}]}
    def post(*a,**k):calls.append(k['json']);return Response()
    recovery.ask('scene',{'story':tree(),'role':'shot'},{'OPENAI_API_KEY':'test'},post)
    schema=calls[0]['response_format']['json_schema']['schema']
    assert set(schema['properties']['scenes']['properties'])=={'scene'}
    assert schema['properties']['scenes']['additionalProperties'] is False
