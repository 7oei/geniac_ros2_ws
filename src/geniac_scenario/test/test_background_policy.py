import numpy as np
from geniac_scenario.background_policy import apply_background_policy
from geniac_scenario.prepare import render_events


def test_engine_off_removes_hum_through_attack():
    tree={'needs':{'hum':{'kind':'ambience','description':'vehicle engine hum'},'stop':{'event':'stop','description':'engine off'},
          'shot':{'kind':'impulse','event':'attack'}},'nodes':{
        'stop':{'stage':'arrival','cues':[{'role':'stop'},{'role':'hum'}],'branches':{'no_escape':'attack'}},
        'attack':{'stage':'interaction','narrative':'A single shot','cues':[{'role':'shot'},{'role':'hum'}],'events':[{}],'branches':{}}}}
    apply_background_policy(tree)
    assert [c['role'] for c in tree['nodes']['attack']['cues']]==['shot']
    assert 'events' not in tree['nodes']['attack'] and 'hum' not in tree['needs']
    assert [c['role'] for c in tree['nodes']['stop']['cues']]==['stop']


def test_background_is_quieter_without_limiting_impulses():
    wave=np.sin(np.arange(24000)*.1)
    events=[{'asset_id':'a','start':0,'source_start':0,'duration':1,'gain_db':0}]
    normal=render_events(events,{'a':wave},1,needs={'a':{'kind':'mechanical'}})
    background=render_events(events,{'a':wave},1,needs={'a':{'kind':'ambience','event':'ambience'}})
    assert np.allclose(background,normal*10**(-12/20))
    impulse=render_events(events,{'a':wave},1,needs={'a':{'kind':'impulse'}})
    assert np.max(abs(impulse))>1.9
