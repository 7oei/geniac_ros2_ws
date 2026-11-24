import math
import pytest
from geniac_behavior.core import Classifier,Settings,group_response

def packet(t,x=10,ids=(1,),valid=True,stream='run'):
    return {'stamp':t,'frame_id':'livox_frame','stream_id':stream,'valid':valid,
            'tracks':[{'track_id':i,'center':[x,float(i),0.]} for i in ids]}

def run(xs,step=.25):
    c=Classifier();c.begin('episode:1',1.)
    for i,x in enumerate(xs):c.update(packet(1+i*step,x))
    return c,c.report(1+(len(xs)-1)*step)

@pytest.mark.parametrize('xs,label',[
    ([10]*25,'no_escape'),
    ([10,10.5,11,12,13]+[13]*25,'retreated_nearby'),
    ([10,15,20,25,30]+[30]*12,'retreated_nearby'),
    ([10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26],'retreated_nearby'),
])
def test_responses(xs,label):
    c,r=run(xs);assert r['targets'][0]['label']==label

def test_observed_disappearance_is_escape_but_invalid_is_unknown():
    c,r=run([10]*25)
    c.update(packet(7.5,ids=()))
    assert c.report(7.5)['targets'][0]['label']=='observing'
    for i in range(1,21):c.update(packet(7.5+i*.25,ids=()))
    assert c.report(12.5)['state']=='escaped'
    c.update(packet(12.75,30,valid=False))
    assert not c.report(12.75)['valid']
    assert c.report(13)['targets'][0]['label']=='unknown'

def test_gap_cannot_prove_stop():
    c=Classifier();c.update(packet(1,10));c.update(packet(8,10))
    assert c.report(8)['targets'][0]['label']=='observing'

def test_node_baseline_and_clock_reset_and_restart():
    c,r=run([10]*25);c.begin('next',7);c.update(packet(7,13))
    assert c.report(7)['targets'][0]['label']=='observing'
    c.update(packet(1,10));assert not c.histories  # old data predates this scenario baseline
    c.begin('clock-reset',1);c.update(packet(1.1,10));assert len(c.histories['run:1'])==1
    c.update(packet(2,10,stream='new'));assert 'run:1' not in c.histories

def test_group_requires_every_original_target():
    assert group_response([{'id':'a','label':'escaped'},{'id':'b','label':'no_escape'}],{'a','b'})=='no_escape'
    assert group_response([{'id':'a','label':'escaped'}],{'a','b'})=='unknown'
    assert group_response([],set())=='unknown'

def test_invalid_packet_does_not_change_history():
    c=Classifier();c.update(packet(1))
    with pytest.raises(ValueError):c.update(packet(2,float('nan')))
    assert c.last_stamp==1
    with pytest.raises(ValueError):Settings(observation_seconds=1)
    with pytest.raises(ValueError):Settings(stale_seconds=math.inf)

def test_tangential_motion_is_not_escape():
    c=Classifier()
    for i in range(25):
        a=i*.04;p=packet(1+i*.25);p['tracks'][0]['center']=[10*math.cos(a),10*math.sin(a),0];c.update(p)
    assert c.report(7)['targets'][0]['label']=='retreated_nearby'

def test_presence_lifecycle_and_reentry():
    c=Classifier()
    assert c.report(1)['state']=='escaped'
    c.update(packet(1,ids=()));assert c.report(1)['state']=='escaped'
    c.update(packet(1.25,10));assert c.report(1.25)['state']=='observing'
    c.update(packet(1.5,ids=()));assert c.report(1.5)['state']=='observing'
    for i in range(1,22):c.update(packet(1.5+i*.25,ids=()))
    r=c.report(6.75)
    assert r['state']=='escaped' and r['targets'][0]['label']=='escaped'
    assert group_response(r['targets'],{'run:1'})=='escaped'  # retained for slow scenario ticks
    c.update(packet(7,20));r=c.report(7)
    assert r['state']=='observing' and r['targets'][0]['displacement_m']==0
    assert r['targets'][0]['present']

def test_movement_in_any_direction_and_return_is_visible_movement():
    for destination in ([9,1,0],[10,3,0],[11,1,0]):
        c=Classifier();c.update(packet(1,10));p=packet(1.25);p['tracks'][0]['center']=destination;c.update(p)
        assert c.report(1.25)['state']=='retreated_nearby'
        c.update(packet(1.5,10));assert c.report(1.5)['state']=='retreated_nearby'

def test_scenario_start_uses_visible_position_and_does_not_erase_presence():
    c=Classifier();c.update(packet(100,10));c.update(packet(100.25,13))
    assert c.report(100.25)['state']=='retreated_nearby'
    c.begin('sound:1',100.3)
    c.update(packet(100.5,13))
    target=c.report(100.5)['targets'][0]
    assert target['baseline_stamp']==100.3 and target['displacement_m']==0
    assert target['label']=='observing'
    c.begin('sound:2',100.6);c.update(packet(100.75,ids=()))
    assert c.report(100.75)['state']=='observing'

def test_partial_group_exit_keeps_remaining_deer():
    c=Classifier();c.update(packet(1,ids=(1,2)))
    c.update(packet(1.25,ids=(2,)))
    r=c.report(1.25)
    assert r['state']=='observing' and r['present_ids']==['run:2']
    assert group_response(r['targets'],{'run:1','run:2'})=='unknown'
    c.update(packet(1.5,ids=()))
    for i in range(1,21):c.update(packet(1.5+i*.25,ids=()))
    assert group_response(c.report(6.5)['targets'],{'run:1','run:2'})=='escaped'

def test_outage_or_detector_restart_is_not_an_observed_departure():
    c=Classifier();c.update(packet(1));c.update(packet(1.25,ids=(),valid=False))
    assert c.report(1.25)['state']=='unknown'
    c.update(packet(1.5,ids=()));assert c.report(1.5)['state']=='observing'
    assert c.report(1.5)['targets'][0]['label']=='observing'
    c.update(packet(2));c.update(packet(5,ids=()))
    assert c.report(5)['state']=='observing'
    c.update(packet(5.25));c.update(packet(5.5,ids=(),stream='new'))
    assert c.report(5.5)['state']=='escaped'

def test_new_visible_id_prevents_false_all_escaped_and_departures_survive_node_change():
    c=Classifier();c.update(packet(1,ids=(1,)))
    c.update(packet(1.25,ids=(2,)))
    r=c.report(1.25)
    assert group_response(r['targets'],{'run:1'})=='unknown'
    c.update(packet(1.5,ids=()));c.begin('next-node',1.6)
    c.update(packet(1.75,ids=()))
    assert c.report(1.75)['state']=='observing'
    for i in range(1,20):c.update(packet(1.75+i*.25,ids=()))
    assert c.report(6.5)['state']=='escaped'
    assert group_response(c.report(6.5)['targets'],{'run:1','run:2'})=='escaped'

def test_empty_scene_is_escaped_but_cannot_start_a_scenario():
    from geniac_behavior.core import LABELS
    c=Classifier()
    assert 'absent' not in LABELS
    r=c.report(1)
    assert r['state']=='escaped' and not r['targets'] and not r['valid']
    for i in range(10):
        c.update(packet(1+i*.25,ids=()))
        r=c.report(1+i*.25)
        assert r['state']=='escaped' and r['valid'] and not r['present_ids'] and not r['targets']
    assert group_response(r['targets'],set())=='unknown'
    assert c.report(10)['state']=='unknown'  # sensor outage remains distinct


def test_missing_boundary_reappearance_and_outage_reset():
    c=Classifier();c.update(packet(1,10));c.update(packet(1.25,12))
    for i in range(20):c.update(packet(1.5+i*.25,ids=()))
    assert c.report(6.25)['state']=='observing'  # 4.75 seconds
    c.update(packet(6.5,12))
    assert c.report(6.5)['state']=='retreated_nearby'  # original baseline retained
    c.update(packet(6.75,ids=()))
    assert c.report(6.75)['targets'][0]['missing_elapsed_seconds']==0
    for i in range(1,17):c.update(packet(6.75+i*.25,ids=()))
    c.update(packet(11,ids=(),valid=False))
    c.update(packet(11.25,ids=()))
    assert c.report(11.25)['targets'][0]['missing_elapsed_seconds']==0
    assert c.report(20)['state']=='unknown'  # silence never confirms escape
    c.update(packet(20.25,ids=()))
    for i in range(1,20):c.update(packet(20.25+i*.25,ids=()))
    assert c.report(25)['state']=='observing'
    c.update(packet(25.25,ids=()))
    assert c.report(25.25)['state']=='escaped'

def test_stationary_start_evidence_is_two_seconds_not_four_second_response():
    c=Classifier()
    for i in range(8):c.update(packet(1+i*.25))
    assert c.report(2.75)['targets'][0]['stationary_seconds']==0
    c.update(packet(3))
    t=c.report(3)['targets'][0]
    assert t['stationary_seconds']==2 and t['label']=='observing'
    c.update(packet(3.25,12))
    assert c.report(3.25)['targets'][0]['stationary_seconds']==0
    for i in range(1,9):c.update(packet(3.25+i*.25,12))
    t=c.report(5.25)['targets'][0]
    assert t['stationary_seconds']==2 and t['label']=='retreated_nearby'


def test_scene_changes_preserve_stop_evidence_without_waiting_again():
    c=Classifier()
    for i in range(9):c.update(packet(1+i*.25,10))
    assert c.report(3)['targets'][0]['stationary_seconds']==2
    for i in range(1,7):
        stamp=3+i*.25
        c.begin(f'scene:{i}',stamp-.1)
        c.update(packet(stamp,10))
        target=c.report(stamp)['targets'][0]
        assert target['stationary_seconds']==2 and target['label']=='no_escape'
    c.begin('moved',4.6);c.update(packet(4.75,13))
    assert c.report(4.75)['targets'][0]['label']=='retreated_nearby'
    assert c.report(4.75)['targets'][0]['stationary_seconds']==0


def test_outage_does_not_carry_stationary_evidence_into_next_scene():
    c=Classifier()
    for i in range(9):c.update(packet(1+i*.25,10))
    invalid=packet(3.1,10);invalid['valid']=False;c.update(invalid)
    c.update(packet(3.2,10));c.begin('after-outage',3.25);c.update(packet(3.3,10))
    assert c.report(3.3)['targets'][0]['stationary_seconds']==0
    assert c.report(3.3)['targets'][0]['label']=='observing'


def test_inflight_pre_scene_frame_does_not_invalidate_input():
    c=Classifier()
    c.update(packet(100.,10))
    c.begin('new-scene',100.15)
    c.update(packet(100.1,10))
    assert c.report(100.2)['valid'] is True
    assert c.last_stamp==100.  # Never restamp old data as new.
    assert c.report(101.2)['valid'] is False
    c.update(packet(100.3,10))
    assert c.report(100.4)['valid'] is True


def test_invalid_inflight_frame_is_not_ignored():
    c=Classifier();c.update(packet(100.,10));c.begin('new-scene',100.15)
    p=packet(100.1,10);p['valid']=False;c.update(p)
    assert c.report(100.2)['valid'] is False
