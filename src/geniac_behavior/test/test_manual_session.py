import json
import pytest
from geniac_behavior.core import Classifier
from geniac_behavior.manual_session import ManualSession, main

@pytest.mark.parametrize('positions,label',[
    ([[10,0]]*20, 'no_escape'),
    ([[10,0],[11,0],[12,0]]+[[13,0]]*20, 'retreated_nearby'),
    ([[10,0],[15,0],[20,0]]+[None]*21, 'escaped'),
])
def test_clicked_positions_use_real_classifier(positions,label):
    s=ManualSession()
    for pos in positions:s.append(pos)
    assert isinstance(s.classifier,Classifier)
    assert s.results[-1]['label']==label
    assert s.results[-1]['elapsed']==(len(positions)-1)*.25

def test_missing_undo_and_baseline():
    s=ManualSession()
    for _ in range(20):s.append([10,0])
    before=s.results[-1]
    s.append(None,'observing');assert s.results[-1]['passed']
    s.undo();assert s.results[-1]==before
    for _ in range(20):s.undo()
    assert not s.frames
    s.append([30,0]);assert s.results[-1]['metrics']['radial_gain_m']==0

def test_expectations_saved_recomputed_and_cli_exit(tmp_path,capsys):
    s=ManualSession();s.append([10,0],'observing');s.append([10,0],'escaped')
    assert s.summary()=={'frames':2,'checked':2,'passed':1,'failed':1}
    path=tmp_path/'case.json';s.save(path)
    payload=json.loads(path.read_text());payload['results']=[{'label':'escaped'}]
    path.write_text(json.dumps(payload))
    replay=ManualSession.load(path)
    assert replay.results==s.results
    assert main([str(path)])==1
    s.undo();s.save(path);assert main([str(path)])==0

def test_frame_gap_not_mistaken_for_stop():
    s=ManualSession(interval=2)
    for _ in range(5):s.append([10,0])
    assert s.results[-1]['label']=='observing'

@pytest.mark.parametrize('pos',[[float('nan'),0],[51,0],[1,31],[1],['1',0]])
def test_invalid_positions_do_not_advance_frame(pos):
    s=ManualSession()
    with pytest.raises(ValueError):s.append(pos)
    assert not s.frames

def test_bad_import_is_rejected(tmp_path):
    p=tmp_path/'case.json';p.write_text('{"format":"other","version":1}')
    with pytest.raises(ValueError):ManualSession.load(p)

def test_empty_escape_empty_and_scenario_baseline_replay(tmp_path):
    s=ManualSession();s.append(None,'escaped');s.append([10,0],'observing')
    s.append([12,0],'retreated_nearby')
    s.pending_baseline=True;s.append([12,0],'observing')
    for _ in range(20):s.append(None,'observing')
    s.append(None,'escaped');s.append(None,'escaped')
    s.append([20,0],'observing')
    assert s.summary()['failed']==0
    p=tmp_path/'baseline.json';s.save(p);replay=ManualSession.load(p)
    assert replay.results==s.results
    replay.undo();assert replay.results[-1]['label']=='escaped'
    replay.undo();assert replay.results[-1]['label']=='escaped'

def test_legacy_absent_expectation_migrates_to_escaped(tmp_path):
    s=ManualSession();s.append(None,'escaped')
    p=tmp_path/'legacy.json';s.save(p)
    data=json.loads(p.read_text());data['frames'][0]['expected']='absent'
    data['results'][0]['label']='absent';p.write_text(json.dumps(data))
    loaded=ManualSession.load(p)
    assert loaded.frames[0]['expected']=='escaped'
    assert loaded.results[0]['label']=='escaped' and loaded.results[0]['passed']
