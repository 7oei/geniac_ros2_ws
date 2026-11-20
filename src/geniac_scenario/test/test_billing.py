import json
from pathlib import Path
import numpy as np
import pytest
import yaml
from scipy.io import wavfile
from geniac_scenario.billing import BillingRequired,check_response,block,state,approve,guard


class Reply:
    def __init__(self,status,code):self.status_code=status;self.code=code
    def json(self):return {'error':{'code':self.code,'message':'not stored'}}


def test_billing_and_rate_limit_are_distinguished_and_gate_persists(tmp_path):
    check_response(Reply(429,'rate_limit_exceeded'))
    with pytest.raises(BillingRequired) as error:check_response(Reply(429,'insufficient_quota'))
    block(tmp_path,error.value)
    assert state(tmp_path)['blocked']
    with pytest.raises(BillingRequired):guard({'_billing_root':str(tmp_path)})
    assert 'not stored' not in (tmp_path/'billing.json').read_text()
    approve(tmp_path);guard({'_billing_root':str(tmp_path)})
    assert not state(tmp_path)['blocked']


def local_fixture(root):
    from geniac_scenario.history import History
    from geniac_scenario.prepare import compile_tree
    from geniac_scenario.tree import load_tree
    from geniac_scenario.weather import JST
    from datetime import datetime
    weather={'date':datetime.now(JST).date().isoformat(),'surface':'grass'}
    needs={'steps':{'description':'草の足音','kind':'footsteps','event':'movement','intensity':1,'queries':['footsteps grass']},
           'shot':{'description':'銃声','kind':'impulse','event':'attack','intensity':3,'queries':['rifle gunshot']}}
    def node(role,dest,stage):return {'title':role,'stage':stage,'level':needs[role]['intensity'],'duration':6.,'min_dwell':6.,
        'cues':[{'role':role,'start':0.,'duration':1.,'gain_db':0.}],
        'branches':{'no_escape':dest,'escaped':'end','unknown':'end','retreated_nearby':'end'}}
    tree={'version':1,'root':'start','needs':needs,'story':{'title':'元の物語','weather':weather,'design_version':3},
          'nodes':{'start':node('steps','attack','transport'),'attack':node('shot','end','interaction'),'end':{'terminal':True,'title':'終わり'}}}
    h=History(root);sid=h.draft(tree,weather)
    batch=root/'original';batch.mkdir()
    audio=batch/'asset.wav';wavfile.write(audio,24000,np.sin(np.arange(24000)*.1).astype(np.float32)*.2)
    manifest={'assets':{key:{'file':str(audio),'duration':1.,'license':'test','attribution':'test','description':key} for key in needs}}
    (batch/'manifest.yaml').write_text(yaml.safe_dump(manifest))
    path=compile_tree(tree,manifest,root,batch/'audio');h.publish(sid,path,load_tree(path));h.consume_manual(sid)
    return h,weather


def test_billing_block_keeps_producing_local_stock_without_paid_calls(tmp_path,monkeypatch):
    import geniac_scenario.stock as stock
    h,weather=local_fixture(tmp_path)
    block(tmp_path,BillingRequired())
    def forbidden(*a,**k):pytest.fail('No generation, acquisition or paid API while blocked')
    monkeypatch.setattr(stock,'generate',forbidden);monkeypatch.setattr(stock,'acquire',forbidden)
    assert stock.replenish(tmp_path,{},count=2,weather=weather)==1
    assert stock.replenish(tmp_path,{},count=2,weather=weather)==2
    assert state(tmp_path)['blocked']
    rows=h.rows('ready');assert all(json.loads(r['tree'])['story']['generation_basis']=='local recombination' for r in rows)
    h.consume_manual(rows[0]['id'])
    assert stock.replenish(tmp_path,{},count=2,weather=weather)==2


def test_billing_error_switches_to_local_mode_in_same_refill(tmp_path,monkeypatch):
    import geniac_scenario.stock as stock
    _,weather=local_fixture(tmp_path)
    calls=[]
    def fail(*a,**k):calls.append(1);raise BillingRequired('OpenAI','insufficient_quota')
    monkeypatch.setattr(stock,'generate',fail)
    assert stock.replenish(tmp_path,{},count=2,weather=weather)==1
    assert stock.replenish(tmp_path,{},count=2,weather=weather)==2
    assert len(calls)==1 and state(tmp_path)['blocked']
