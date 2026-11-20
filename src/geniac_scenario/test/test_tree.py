from pathlib import Path
import copy
import pytest
from geniac_scenario.tree import Engine,load_tree,validate_tree,audio_paths
from geniac_scenario.audio import Player

TREE=Path(__file__).parents[1]/'config/demo_tree.yaml'

def report(e,label):
    return {'epoch':e.epoch,'valid':True,'targets':[{'id':'one','label':label}]}

@pytest.mark.parametrize('label,dest',[('retreated_nearby','caution'),('no_escape','strong')])
def test_branch_during_playback(label,dest):
    e=Engine(load_tree(TREE));e.start(0,100,['one'])
    assert not e.tick(4,104,report(e,label))
    assert e.tick(5,105,report(e,label));assert e.node_id==dest

def test_old_response_cannot_branch_new_node():
    e=Engine(load_tree(TREE));e.start(0,100,['one']);old=report(e,'no_escape')
    e.tick(5,105,old);assert e.node_id=='strong'
    assert not e.tick(11,111,old)
    e.tick(15,115,None);assert not e.running and e.node_id=='finish'

def test_unknown_missing_target_and_stop():
    e=Engine(load_tree(TREE));e.start(0,100,['one','two'])
    assert not e.tick(6,106,report(e,'escaped'))
    e.tick(12,112,None);assert not e.running
    e.start(20,120,['one']);e.stop();assert not e.tick(40,140,report(e,'no_escape'))

def test_no_cycles_invalid_edges_or_unreachable():
    for modify in [lambda t:t['nodes']['strong']['branches'].update(no_escape='warning'),
                   lambda t:t['nodes']['warning']['branches'].update(escaped='missing'),
                   lambda t:t['nodes'].update(orphan={'terminal':True}),
                   lambda t:t['nodes']['warning'].update(duration=float('nan'))]:
        t=load_tree(TREE);modify(t)
        with pytest.raises(ValueError):validate_tree(t)

def test_paths_and_audio_required(tmp_path):
    t=load_tree(TREE)
    with pytest.raises(ValueError):audio_paths(t,tmp_path)
    t['nodes']['warning']['audio']='../outside.wav'
    with pytest.raises(ValueError):audio_paths(t,tmp_path,False)

def test_duplicate_keys(tmp_path):
    p=tmp_path/'tree.yaml';p.write_text('version: 1\nversion: 2')
    with pytest.raises(ValueError):load_tree(p)

class Process:
    def __init__(self):self.returncode=None;self.terminated=False
    def poll(self):return self.returncode
    def terminate(self):self.terminated=True;self.returncode=0
    def wait(self,timeout):return 0

def test_player_stops_previous_and_uses_argv(tmp_path):
    p=tmp_path/'sound with spaces.wav';p.touch();calls=[];processes=[]
    def spawn(argv,**kw):
        calls.append(argv);proc=Process();processes.append(proc);return proc
    a=Player(20,False,spawn);a.play(p,5);a.play(p,3)
    assert processes[0].terminated and calls[1][-1]==str(p) and '-t' in calls[1]
    a.stop();assert processes[1].terminated

def test_dry_run_never_spawns():
    a=Player(dry_run=True,spawn=lambda *a,**k:pytest.fail('spawned'))
    a.play(None,5);a.stop()

def test_escape_cannot_escalate_unknown_cannot_continue():
    t=load_tree(TREE);t['nodes']['warning']['branches']['escaped']='strong'
    with pytest.raises(ValueError):validate_tree(t)
    t=load_tree(TREE);t['nodes']['warning']['branches']['unknown']='strong'
    with pytest.raises(ValueError):validate_tree(t)

def test_disappearance_result_is_consumed_during_continuing_empty_frames():
    from geniac_behavior.core import Classifier
    c=Classifier();e=Engine(load_tree(TREE));e.start(0,100,['run:1']);c.begin(e.epoch,100)
    def packet(t,tracks):return {'stamp':t,'frame_id':'livox_frame','stream_id':'run','valid':True,'tracks':tracks}
    c.update(packet(100,[{'track_id':1,'center':[8,0,0]}]))
    c.update(packet(100.25,[]));assert c.report(100.25)['state']=='observing'
    for i in range(1,21):c.update(packet(100.25+i*.25,[]))
    report=c.report(105.25);assert report['state']=='escaped'
    assert e.tick(5.25,105.25,report) and e.node_id=='finish' and not e.running


def test_late_arrival_remains_in_cohort_while_missing():
    e=Engine(load_tree(TREE));e.start(0,100,['one'])
    def reaction(two, present=False):
        return {'epoch':e.epoch,'valid':True,'targets':[
            {'id':'one','label':'escaped','present':False},
            {'id':'two','label':two,'present':present}]}
    assert not e.tick(4,104,reaction('observing',True))
    assert e.state()['targets']==['one','two']
    assert not e.tick(5,105,reaction('observing'))
    assert not e.tick(9.75,109.75,reaction('observing'))
    assert e.tick(10,110,reaction('escaped'))
    assert e.node_id=='finish' and not e.running


def test_pending_exit_at_deadline_uses_unknown_branch():
    e=Engine(load_tree(TREE));e.start(0,100,['one'])
    assert e.tick(12,112,report(e,'observing'))
    assert e.node_id=='finish' and e.reason=='timeout_unknown'


def test_invalid_or_previous_epoch_cannot_add_cohort():
    e=Engine(load_tree(TREE));e.start(0,100,['one'])
    for validity,epoch in [(False,e.epoch),(True,'old')]:
        e.tick(1,101,{'epoch':epoch,'valid':validity,
                     'targets':[{'id':'two','label':'observing','present':True}]})
    assert e.cohort=={'one'}


def test_fresh_observation_waits_after_audio_then_branches():
    e=Engine(dict(load_tree(TREE),wait_for_observation=True));e.start(0,100,['one'])
    observing=report(e,'observing')
    assert not e.tick(20,120,observing) and e.running and e.reason=='awaiting_behavior'
    assert e.tick(20.1,120.1,report(e,'retreated_nearby')) and e.node_id=='caution'
    assert e.tick(40,140,dict(report(e,'observing'),valid=False)) and not e.running


def test_escape_ends_immediately_and_legacy_tail_is_removed():
    original=load_tree(TREE)
    e=Engine(original)
    assert 'gentle' in original['nodes']
    for node in e.tree['nodes'].values():
        if not node.get('terminal'):
            assert e.tree['nodes'][node['branches']['escaped']].get('terminal')
    e.start(0,100,['one'])
    assert e.tick(.1,100.1,report(e,'escaped'))
    assert not e.running and e.reason=='escaped'
    assert not e.tick(10,110,report(e,'no_escape'))


def test_audio_failure_keeps_stderr_after_stop(tmp_path):
    path=tmp_path/'sound.wav';path.touch()
    def spawn(argv,**kwargs):
        kwargs['stderr'].write(b'Failed to open audio device')
        kwargs['stderr'].flush()
        process=Process();process.returncode=1
        return process
    player=Player(dry_run=False,spawn=spawn)
    player.play(path,1)
    assert player.failed()
    player.stop()
    assert 'exit=1' in player.last_error and 'audio device' in player.last_error
    assert player.error_file is None


def test_fractional_repeat_gap_and_escape_during_wait(monkeypatch):
    from geniac_scenario.story import story_tree
    import geniac_scenario.tree as module
    gaps=iter([1.375,.625])
    monkeypatch.setattr(module.random,'uniform',lambda lo,hi:next(gaps))
    e=Engine(dict(story_tree({'surface':'grass'}),repeat_gap_max_seconds=2.))
    e.start(0,100,['one']);e._enter('attack',0,100,'test')
    assert e.tick(2,102,report(e,'no_escape')) and e.reason=='repeat_interval'
    epoch=e.epoch
    assert e.state()['repeat_gap_seconds']==1.375
    assert not e.tick(3.374,103.374,report(e,'no_escape')) and e.epoch==epoch
    assert e.tick(3.375,103.375,report(e,'retreated_nearby'))
    assert e.reason=='repeat_final_retreated_nearby' and e.epoch!=epoch
    assert e.tick(5.375,105.375,report(e,'no_escape'))
    assert e.state()['repeat_gap_seconds']==.625
    assert e.tick(5.5,105.5,report(e,'escaped')) and not e.running


def test_repeat_gap_zero_and_pending_confirmation(monkeypatch):
    from geniac_scenario.story import story_tree
    import geniac_scenario.tree as module
    monkeypatch.setattr(module.random,'uniform',lambda lo,hi:0.)
    e=Engine(dict(story_tree({'surface':'grass'}),repeat_gap_max_seconds=2.))
    e.start(0,100,['one']);e._enter('attack',0,100,'test')
    assert e.tick(2,102,report(e,'no_escape')) and e.reason=='repeat_final_no_escape'
    monkeypatch.setattr(module.random,'uniform',lambda lo,hi:2.)
    assert e.tick(4,104,report(e,'no_escape')) and e.reason=='repeat_interval'
    assert not e.tick(6,106,report(e,'observing')) and e.reason=='awaiting_behavior'
    assert e.tick(6.1,106.1,report(e,'escaped')) and not e.running
