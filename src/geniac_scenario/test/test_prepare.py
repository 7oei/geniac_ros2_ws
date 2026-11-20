from pathlib import Path
import numpy as np
import pytest
from scipy.io import wavfile
from geniac_scenario.prepare import render_events, compile_tree, credentials, design
from geniac_scenario.tree import load_tree,audio_paths

TREE=Path(__file__).parents[1]/'config/demo_tree.yaml'

def event(**kwargs):
    return dict({'asset_id':'a','start':0.,'source_start':0.,'duration':1.,'gain_db':0.},**kwargs)

def test_audio_mixing_without_peak_limiter():
    y=render_events([event(),event()],{'a':np.ones(24000)},2)
    assert np.max(abs(y))==2. and np.all(y[24000:]==0)
    for e in [event(start=2.),event(source_start=1.),event(gain_db=1.),event(duration=float('nan')),event(asset_id='missing')]:
        with pytest.raises(ValueError):render_events([e],{'a':np.ones(24000)},2)

def test_compile_all_branches_and_provenance(tmp_path):
    audio=tmp_path/'local.wav';wavfile.write(audio,24000,np.sin(np.arange(24000)*.1).astype(np.float32)*.1)
    tree=load_tree(TREE);manifest={'assets':{'a':{'file':'local.wav','license':'test-only','attribution':'synthetic test fixture'}},
        'timelines':{k:[event()] for k,n in tree['nodes'].items() if not n.get('terminal')}}
    out=compile_tree(tree,manifest,tmp_path,tmp_path/'compiled')
    assert len(audio_paths(load_tree(out),out.parent))==4
    assert (out.parent/'provenance.json').is_file()
    with pytest.raises(ValueError):compile_tree(tree,manifest,tmp_path,tmp_path/'compiled')

def test_env_is_data_not_shell(tmp_path,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    p=tmp_path/'env';p.write_text('OPENAI_API_KEY="fake-key"\nLLM_MODEL=model\nUNUSED=$(touch /tmp/should-not-run)\n')
    assert credentials(p)['OPENAI_API_KEY']=='fake-key'
    monkeypatch.setenv('OPENAI_API_KEY','environment-wins')
    assert credentials(p)['OPENAI_API_KEY']=='environment-wins'

def test_llm_transport_mock_and_policy_validation():
    import json
    class Reply:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(load_tree(TREE.with_name('story_tree.yaml')))}}]}
    calls=[]
    def post(url,**kw):calls.append((url,kw));return Reply()
    t=design({'assets':{}},{'OPENAI_API_KEY':'fake','LLM_MODEL':'test'},'test',post)
    assert t['root']=='arrival' and len(calls)==1
    assert 'fake' not in json.dumps(calls[0][1]['json'])


def test_normal_levels_match_despite_source_gain_and_silence():
    from geniac_scenario.prepare import level_clip
    wave=np.sin(np.arange(24000)*.1)
    assert np.allclose(level_clip(wave*.005),level_clip(wave*.8))
    padded=np.r_[np.zeros(24000),wave*.1]
    assert np.allclose(level_clip(padded)[24000:],level_clip(wave*.1))
    assert not np.any(level_clip(padded)[:24000])


def test_attack_amplification_is_not_limited():
    from geniac_scenario.prepare import level_clip
    wave=np.sin(np.arange(24000)*.1)
    assert np.max(abs(level_clip(wave,True,True)))>4*np.max(abs(level_clip(wave)))
    y=render_events([event(),event()],{'a':wave},2,needs={'a':{'kind':'impulse','event':'attack'}})
    assert np.max(abs(y))>3.9 and np.isfinite(y).all()


def test_trim_edges_preserves_internal_pause_and_low_volume():
    from geniac_scenario.prepare import trim_edge_silence
    signal=np.r_[np.zeros(24000),np.ones(2400),np.zeros(12000),np.ones(2400),np.zeros(24000)]
    trimmed=trim_edge_silence(signal)
    assert len(trimmed)==2400+12000+2400+480
    assert np.all(trimmed[2640:14640]==0)
    assert np.allclose(trim_edge_silence(signal*.0001),trimmed*.0001)
    with pytest.raises(ValueError,match='Silent'):trim_edge_silence(np.zeros(24000))


def test_mixed_scene_tail_is_shortened_and_quiet_decay_is_kept():
    from geniac_scenario.prepare import trim_scene_tail
    rate=24000
    sound=np.sin(np.arange(rate)*.1)*.1
    data=np.r_[sound,np.zeros(rate*8)]
    result=trim_scene_tail(data)
    assert len(result)<=rate+round(.15*rate)
    assert np.array_equal(result[:rate],sound)


def test_compiled_boundary_tracks_audio_end(tmp_path):
    audio=tmp_path/'sound.wav';wavfile.write(audio,24000,np.ones(24000,dtype=np.float32)*.1)
    tree=load_tree(TREE)
    manifest={'assets':{'a':{'file':'sound.wav','license':'test','attribution':'test'}},
              'timelines':{key:[event()] for key,n in tree['nodes'].items() if not n.get('terminal')}}
    path=compile_tree(tree,manifest,tmp_path,tmp_path/'compiled')
    for n in load_tree(path)['nodes'].values():
        if n.get('terminal'):continue
        rate,data=wavfile.read(path.parent/n['audio'])
        assert n['duration']==len(data)/rate
        assert n['min_dwell']<=n['duration']<=1.15


def test_all_impacts_use_the_same_unlimited_amplification():
    wave=np.sin(np.arange(24000)*.1)*np.exp(-np.arange(24000)/5000)
    impact=render_events([event()],{'a':wave},1,needs={'a':{'kind':'impulse','event':'action'}})
    attack=render_events([event()],{'a':wave},1,needs={'a':{'kind':'impulse','event':'attack'}})
    assert np.allclose(attack,impact)
    assert np.max(abs(attack))>1.8
