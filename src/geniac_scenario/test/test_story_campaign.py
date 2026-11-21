from datetime import datetime
import json
from pathlib import Path
import pytest
from geniac_scenario.story import story_tree,attach_events
from geniac_scenario.campaign import Campaign
from geniac_scenario.tree import Engine,validate_tree
from geniac_scenario.weather import fetch_weather,surface_for,JST
from geniac_scenario.stock import Stock,atomic_json

WEATHER={'surface':'snow','date':'2026-11-20','source':'test'}

def report(core,label='no_escape',stationary=2.,second=None):
    rows=[{'id':'one','present':label not in ('escaped','missing'),
           'label':'observing' if label=='missing' else label,'stationary_seconds':stationary}]
    if second:rows.append({'id':'two','present':True,'label':second,'stationary_seconds':2.})
    return {'valid':True,'epoch':core.epoch,'targets':rows}

@pytest.mark.parametrize('opponent',['human','bear'])
@pytest.mark.parametrize('surface',['snow','rain','grass'])
def test_complete_story_and_weather_footsteps(opponent,surface):
    t=story_tree(dict(WEATHER,surface=surface),opponent)
    assert t['root']=='arrival' and t['needs']['footsteps']['query'].endswith({'snow':'snow','rain':'water','grass':'grass'}[surface])
    assert all(n['min_dwell']==n['duration'] for n in t['nodes'].values() if not n.get('terminal'))
    assets={'assets':{k:{'duration':3.} for k in t['needs']}}
    assert all(n.get('events') for n in attach_events(t,assets)['nodes'].values() if not n.get('terminal'))

@pytest.mark.parametrize('stage',['arrival','search','approach','prepare'])
def test_escape_never_reaches_shot(stage):
    e=Engine(story_tree(WEATHER));e.start(0,100,['one']);now=0
    while e.node_id!=stage:
        now+=e.tree['nodes'][e.node_id]['duration'];e.tick(now,100+now,report(e))
    now+=.1;e.tick(now,100+now,report(e,'escaped'))
    assert e.node_id=='escaped_end'
    now+=6;e.tick(now,100+now,report(e,'escaped'))
    assert e.node_id=='escaped_end' and 'attack' not in [t['node'] for t in e.transitions]


def test_branch_only_at_boundary_and_pending_never_shoots():
    e=Engine(story_tree(WEATHER));e.start(0,100,['one'])
    assert not e.tick(7.99,107.99,report(e))
    assert e.tick(8,108,report(e)) and e.node_id=='search'
    e.tick(16,116,report(e));e.tick(24,124,report(e));assert e.node_id=='prepare'
    e.tick(30,130,report(e,'missing'));assert e.node_id=='uncertain_end'


def test_two_second_start_repeat_until_escape_and_stop():
    c=Campaign(story_tree(WEATHER))
    assert not c.tick(0,100,report(c.core,'observing',0))
    assert not c.tick(1.99,101.99,report(c.core,'observing',1.99))
    assert c.tick(2,102,report(c.core,'observing',2)) and c.round==1
    for now in [10,18,26,32,34]:c.tick(now,100+now,report(c.core))
    assert c.core.node_id=='attack' and c.core.reason=='repeat_final_no_escape'
    assert not c.tick(34.1,134.1,report(c.core)) and c.round==1
    c.tick(35,135,report(c.core,'escaped'));assert c.core.node_id=='escaped_end'
    c.tick(41,141,report(c.core,'escaped'));c.tick(41.1,141.1,report(c.core,'escaped'))
    assert not c.active and c.round==1
    assert not c.tick(42,142,report(c.core,'escaped'))
    c.stop();assert not c.armed


def test_stock_wait_and_outage_and_mixed_deer():
    c=Campaign(story_tree(WEATHER))
    assert not c.tick(0,100,report(c.core),next_tree=lambda:None)
    assert c.waiting=='story_stock'
    c.tick(1,101,report(c.core,second='no_escape'))
    c.tick(9,109,report(c.core,'escaped',second='no_escape'))
    assert c.core.node_id=='search'
    c.tick(10,110,{},fresh=False)
    assert c.armed and c.paused and not c.core.running

@pytest.mark.parametrize('code,rain,snow,expected',[(0,0,0,'grass'),(3,0,0,'grass'),(61,0,0,'rain'),(0,.1,0,'rain'),(71,0,0,'snow'),(61,1,.1,'snow')])
def test_surface(code,rain,snow,expected):assert surface_for(code,rain,snow)==expected


def test_weather_date_validation():
    class HTTP:
        status_code=200
        def get(self,*args,**kwargs):return self
        def json(self):return {'current':{'time':'2026-11-20T12:00','weather_code':71,'rain':0,'snowfall':1}}
    w=fetch_weather(datetime(2026,11,20,12,10,tzinfo=JST),HTTP())
    assert w['surface']=='snow' and w['source'].startswith('https:')
    with pytest.raises(ValueError):fetch_weather(datetime(2026,11,21,12,tzinfo=JST),HTTP())


def test_stock_rejects_old_incomplete_and_outside(tmp_path):
    atomic_json(tmp_path/'ready.json',{'date':'2026-11-20','trees':['missing/tree.yaml']})
    assert not Stock(tmp_path).ready('2026-11-20')
    assert not Stock(tmp_path).ready('2026-11-21')
    atomic_json(tmp_path/'ready.json',{'date':'2026-11-20','trees':['../tree.yaml']})
    assert not Stock(tmp_path).ready('2026-11-20')

def test_pending_after_cycle_waits_then_escape_does_not_restart():
    c=Campaign(story_tree(WEATHER));c.tick(0,100,report(c.core))
    c.tick(8,108,report(c.core,'missing'))
    assert c.core.node_id=='arrival' and c.paused
    assert not c.tick(9,109,report(c.core,'missing'))
    assert c.waiting=='input_unknown'
    assert c.tick(13,113,report(c.core,'escaped')) and not c.active
    assert c.core.node_id=='escaped_end' and not c.paused


def test_confirmed_old_deer_does_not_block_later_rounds():
    c=Campaign(story_tree(WEATHER));c.tick(0,100,report(c.core,second='no_escape'))
    for now in [8,16,24,30,32]:c.tick(now,100+now,report(c.core,'escaped',second='no_escape'))
    c.tick(32.1,132.1,report(c.core,'escaped',second='no_escape'))
    assert c.round==1 and c.core.node_id=='attack'
    assert c.core.running


@pytest.mark.parametrize('kind,event,expected',[
    ('mechanical','stop',1),('mechanical','exit',1),('mechanical','transport',1),
    ('mechanical','action',1),('impulse','attack',1),('voice','action',1),
    ('ambience','stop',1),('footsteps','movement',4),('ambience','ambience',4),
])
def test_discrete_actions_do_not_loop_to_fill_time(kind,event,expected):
    t={'needs':{'sound':{'kind':kind,'event':event}},'nodes':{'scene':{
        'cues':[{'role':'sound','start':3.,'duration':7.,'gain_db':-10}]}}}
    compiled=attach_events(t,{'assets':{'sound':{'duration':2.}}})
    events=compiled['nodes']['scene']['events']
    assert len(events)==expected and events[0]['start']==3
    assert sum(e['duration'] for e in events)==(2 if expected==1 else 7)



def test_trimmed_stop_and_exit_are_adjacent_and_rebinding_is_idempotent():
    tree={'needs':{'stop':{'kind':'mechanical','event':'stop'},'exit':{'kind':'mechanical','event':'exit'}},
          'nodes':{'arrival':{'duration':16.,'min_dwell':16.,'cues':[
              {'role':'stop','start':0.,'duration':7.,'gain_db':0.},
              {'role':'exit','start':7.,'duration':9.,'gain_db':0.}]}}}
    manifest={'assets':{'stop':{'duration':2.},'exit':{'duration':5.}}}
    t=attach_events(tree,manifest);n=t['nodes']['arrival']
    assert [e['start'] for e in n['events']]==[0.,2.]
    assert n['duration']==n['min_dwell']==7.
    assert attach_events(t,manifest)==t


def test_compaction_preserves_overlap_and_explicit_pause():
    tree={'needs':{'a':{'kind':'mechanical'},'b':{'kind':'mechanical'}},'nodes':{'n':{
        'duration':12.,'min_dwell':12.,'cues':[
            {'role':'a','start':0.,'duration':7.,'gain_db':0.},
            {'role':'b','start':1.,'duration':4.,'gain_db':0.},
            {'role':'b','start':9.,'duration':3.,'gain_db':0.}]}}}
    t=attach_events(tree,{'assets':{'a':{'duration':2.},'b':{'duration':4.}}})
    # Only 5..7 is reclaimed; overlapping audio 1..5 and intentional pause 7..9 survive.
    assert [e['start'] for e in t['nodes']['n']['events']]==[0.,1.,7.]
    assert t['nodes']['n']['duration']==10.


def test_new_arrival_after_escape_requires_stationary_trigger():
    c=Campaign(story_tree(WEATHER))
    c.tick(0,100,report(c.core))
    c.tick(1,101,report(c.core,'escaped'))
    assert not c.active and not c.core.running
    assert not c.tick(1.1,101.1,report(c.core,'observing',0))
    assert not c.tick(3,103,report(c.core,'observing',1.9))
    assert c.tick(3.1,103.1,report(c.core,'observing',2))
    assert c.core.running and c.core.node_id=='arrival'


@pytest.mark.parametrize('node',['arrival','search','approach','watch','prepare','attack'])
@pytest.mark.parametrize('reason',['input_stale','input_invalid','audio_playback_error','audio_start_error'])
def test_every_scene_resumes_same_position_after_recovery(node,reason):
    c=Campaign(story_tree(WEATHER));c.tick(0,100,report(c.core))
    c.core._enter(node,1,101,'test')
    epoch=c.core.epoch
    assert c.pause(reason,1.5)
    assert c.armed and c.paused and not c.core.running
    assert not c.tick(2,102,dict(report(c.core),epoch='old'))
    assert not c.tick(2,102,report(c.core),fresh=False)
    assert c.tick(4,104,report(c.core))
    assert c.core.running and not c.paused and c.core.node_id==node
    assert c.core.epoch==epoch and 4-c.core.entered==.5
    assert c.round==1


def test_pause_then_escape_finishes_without_replaying_attack():
    c=Campaign(story_tree(WEATHER));c.tick(0,100,report(c.core))
    c.core._enter('attack',1,101,'test');c.pause('input_stale',1.2)
    assert c.tick(7,107,report(c.core,'escaped'))
    assert c.core.node_id=='escaped_end' and not c.core.running and not c.paused


def test_manual_stop_cancels_auto_recovery():
    c=Campaign(story_tree(WEATHER));c.tick(0,100,report(c.core))
    c.pause('input_stale',1);c.stop()
    assert not c.tick(10,110,report(c.core))
    assert not c.armed and not c.paused and not c.core.running


def test_unknown_at_checkpoint_resumes_with_confirmed_reaction():
    c=Campaign(story_tree(WEATHER));c.tick(0,100,report(c.core))
    assert c.tick(8,108,report(c.core,'unknown'))
    assert c.paused and c.core.node_id=='arrival' and c.core.reason=='input_unknown'
    assert c.tick(9,109,report(c.core))
    assert c.core.node_id=='search' and c.core.running


def test_long_pause_closes_episode_but_remains_armed():
    c=Campaign(story_tree(WEATHER));c.tick(0,100,report(c.core))
    c.pause('input_stale',1)
    assert c.tick(31,131,{},fresh=False)
    assert c.core.reason=='auto_recovery_reset' and c.armed and not c.paused
    assert not c.tick(32,132,report(c.core))
    assert c.tick(35,135,report(c.core)) and c.core.running


def test_expired_ids_reconciled_only_after_valid_window():
    c=Campaign(story_tree(WEATHER));c.tick(0,100,report(c.core))
    c.core.cohort.add('forgotten');c.pause('input_stale',1)
    c.tick(2,102,report(c.core),fresh=False)
    assert not c.tick(3,103,report(c.core))
    assert c.tick(8,108,report(c.core)) and not c.paused
    assert 'forgotten' not in c.core.cohort
