import json
from geniac_scenario.bag_test import Journal,playback_command


def test_only_raw_cloud_is_replayed_at_real_time():
    cmd=playback_command('/recording/with spaces','qos.yaml')
    assert cmd[3]=='/recording/with spaces'
    assert cmd[cmd.index('--rate')+1]=='1.0'
    assert cmd[cmd.index('--topics')+1:]==['/livox/lidar']
    assert '--loop' not in cmd and '--clock' in cmd


def test_journal_counts_episodes_not_repeated_scene_messages(tmp_path):
    j=Journal(tmp_path)
    packet={'running':True,'story':{'id':'a'},'transitions':[{'reason':'start','stamp':5.},{'reason':'repeat_final_no_escape','stamp':7.}]}
    for _ in range(10):j.record('scenario',packet)
    j.record('tracks',{'tracks':[{'track_id':1}]});j.record('tracks',{'tracks':[]})
    j.record('behavior',{'state':'escaped'})
    assert j.summary()['scenario_starts']==1
    packet['transitions']=[{'reason':'start','stamp':9.}];j.record('scenario',packet)
    j.close()
    saved=json.loads((tmp_path/'summary.json').read_text())
    assert saved['scenario_starts']==2
    assert saved['message_counts']['frames_with_tracks']==1


def test_bag_test_outcomes_do_not_select_learning_champion(tmp_path):
    from geniac_scenario.history import History
    from test_evolving import design,result
    h=History(tmp_path);t=design();sid=h.draft(t,{'date':'2026-11-20','surface':'grass'});h.publish(sid,tmp_path/'tree.yaml',t)
    h.record(result(sid=sid,score=100,mode='bag_test'))
    context=h.context()
    assert context['best']==[] and context['provisional_best']==[] and context['field_trials']==0
