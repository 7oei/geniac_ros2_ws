import copy
import numpy as np
import pytest
from geniac_scenario import stock


def prepare_fixture(tmp_path,monkeypatch):
    need={'kind':'impulse','event':'attack','queries':['single rifle gunshot'],'description':'single gunshot','intensity':3}
    tree={'story':{'weather':{'surface':'grass'}},'needs':{'shot':need},'nodes':{'shot':{'cues':[{'role':'shot','duration':1}]}}}
    searches=[]
    monkeypatch.setattr(stock,'search',lambda *a:searches.append(a) or [{'id':str(i),'duration':1} for i in range(3)])
    monkeypatch.setattr(stock,'verify_candidate',lambda *a:{'policy_version':3,'method':'test'})
    def download(item,path):
        path.write_text(item['id'])
        return dict(item,file=str(path),description='gunshot')
    monkeypatch.setattr(stock,'download',download)
    monkeypatch.setattr(stock,'decode',lambda path:np.full(24000,int(path.read_text())+1,dtype=np.float32))
    return tree,searches


def test_cached_common_material_refreshes_probabilistically_after_five_uses(tmp_path,monkeypatch):
    tree,searches=prepare_fixture(tmp_path,monkeypatch)
    draws=iter([.9,.7,.69])
    monkeypatch.setattr(stock.random,'random',lambda:next(draws))
    ids=[stock.acquire(copy.deepcopy(tree),tmp_path,{})['assets']['shot']['id'] for _ in range(9)]
    assert ids==['0']*7+['1','1']
    assert len(searches)==2


def test_failed_refresh_retains_working_recording(tmp_path,monkeypatch):
    tree,_=prepare_fixture(tmp_path,monkeypatch)
    first=stock.acquire(copy.deepcopy(tree),tmp_path,{})['assets']['shot']
    monkeypatch.setattr(stock,'search',lambda *a:[])
    next_asset=stock.acquire(copy.deepcopy(tree),tmp_path,{},refresh=True)['assets']['shot']
    assert next_asset['id']==first['id']


def test_replay_counts_once_and_triggers_refresh(tmp_path,monkeypatch):
    from geniac_scenario.history import History
    tree,searches=prepare_fixture(tmp_path,monkeypatch)
    history=History(tmp_path)
    sid=history.draft(tree,{'date':'2026-11-20','surface':'grass'})
    history.publish(sid,tmp_path/'tree.yaml',tree)
    first=stock.acquire(copy.deepcopy(tree),tmp_path,{})['assets']['shot']['id']
    history.begin_playback(sid,'initial')
    assert history.reuse_counts()=={}
    history.consume_manual(sid)
    for i in range(4):
        for _ in range(10):history.begin_playback(sid,'replay'+str(i))
    assert history.reuse_counts()=={'impulse:attack':4}
    monkeypatch.setattr(stock.random,'random',lambda:0.)
    second=stock.acquire(copy.deepcopy(tree),tmp_path,{})['assets']['shot']['id']
    assert second!=first
    assert stock.acquire(copy.deepcopy(tree),tmp_path,{})['assets']['shot']['id']==second
    assert len(searches)==2


def test_field_claim_reuse_counts_only_successful_claim(tmp_path):
    from geniac_scenario.history import History
    h=History(tmp_path)
    tree={'story':{},'needs':{'a':{'kind':'impulse','event':'attack'}},'nodes':{'x':{'cues':[{'role':'a'},{'role':'a'}]}}}
    sid=h.draft(tree,{'date':'2026-11-20','surface':'grass'})
    h.publish(sid,tmp_path/'tree.yaml',tree)
    assert h.claim(sid)
    assert h.reuse_counts()=={}
    with h.connect() as c:c.execute("UPDATE stories SET status='used' WHERE id=?",(sid,))
    assert h.claim(sid,reuse=True)
    assert not h.claim(sid,reuse=True)
    assert h.reuse_counts()=={'impulse:attack':1}


def test_transport_accepts_real_clip_shorter_than_planned_window(tmp_path,monkeypatch):
    tree,_=prepare_fixture(tmp_path,monkeypatch)
    tree['needs']['shot'].update(kind='mechanical',event='transport')
    tree['nodes']['shot']['cues'][0]['duration']=18
    seen=[]
    def fetch(need,queries,duration,*args):
        seen.append(duration);path=tmp_path/'car.mp3';path.write_text('1')
        return {'id':'car','file':str(path),'sha256':'a','verification':{'policy_version':3}}
    monkeypatch.setattr(stock,'fetch_alternative',fetch)
    monkeypatch.setattr(stock,'decode',lambda path:np.ones(3*24000))
    asset=stock.acquire(tree,tmp_path,{})['assets']['shot']
    assert seen==[2.] and asset['duration']==3.
