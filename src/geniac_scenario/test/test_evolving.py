import copy
import json
from datetime import datetime
from pathlib import Path
import pytest
import yaml
from geniac_scenario.evolving import generate,validate_design,strategy_for
from geniac_scenario.history import History
from geniac_scenario.evaluation import Trial
from geniac_scenario.tree import Engine
from geniac_scenario.stock import Stock
from geniac_scenario.weather import JST


def design():
    def n(title,level,role,next_node):
        return {'title':title,'narrative':title,'location':'林道の入口','action':title,'cause':'遠方から移動して来たため',
                'stage':'transport' if role=='motor' else 'interaction','duration':6,'min_dwell':6,'level':level,'audio':None,
                'cues':[{'role':role,'start':0,'duration':1,'gain_db':-20}],
                'branches':{'escaped':'end','retreated_nearby':'end','no_escape':next_node,'unknown':'end'}}
    return {'version':1,'root':'arrival','story':{'title':'森の異音','premise':'機械が近づき止まる','direction':'machine','change':'接近速度を変える','design_version':3,'variation':{'actor_count':1,'roles':['機械'],'approach':'together','dialogue':'none','movement':'none','vehicle':'作業車','weapon':'none','sound_arrangement':'移動後に動作する'},
            'arrival':{'actor':'自走する作業機械','actor_kind':'machine','origin':'林道の作業拠点','destination':'林縁の作業場所','travel_mode':'vehicle','travel_reason':'作業場所へ移動するため','purpose':'資材を運ぶため',
                       'steps':['林道を進む','現場で停車する','作業を始める'],'assumptions':['近くに林道がある設定']}},
            'needs':{'motor':{'description':'モーター','kind':'mechanical','intensity':1,'queries':['electric motor start']},
                     'bang':{'event':'attack','description':'銃声','kind':'impulse','intensity':3,'queries':['metal impact clang']}},
            'nodes':{'arrival':n('遠くの機械',1,'motor','impact'),'impact':n('金属が落ちる',3,'bang','end'),
                     'end':{'terminal':True,'title':'終了'}}}


def result(sid='one',score=80,strategy='improve',mode='field',outcome='escaped',trial='t'):
    return {'trial_id':trial,'story_id':sid,'mode':mode,'score':score,'outcome':outcome,
            'story':{'strategy':strategy,'direction':'machine','premise':'parent'}}


def test_strategy_explore_every_third_and_recover():
    best=result();bad=result(score=0,strategy='explore',outcome='not_escaped')
    context={'best':[best],'recent':[bad]}
    assert strategy_for(3,context)[0]=='explore'
    assert strategy_for(6,context)[0]=='explore'
    assert strategy_for(4,context)==('recover',best)
    assert strategy_for(7,{'best':[best],'recent':[best]})[0]=='improve'


def test_llm_conceives_before_assets_and_uses_feedback():
    calls=[]
    class Response:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(design())}}]}
    def post(url,**kwargs):calls.append(kwargs);return Response()
    tree=generate({'surface':'snow'}, {'best':[],'recent':[]},1,{'OPENAI_API_KEY':'secret'},post)
    prompt=json.loads(calls[0]['json']['messages'][1]['content'])
    assert 'assets' not in prompt and tree['story']['strategy']=='seed'
    assert 'secret' not in json.dumps(calls[0]['json'])
    assert tree['interrupt_on_escape']

@pytest.mark.parametrize('mutate',[
    lambda t:t['nodes']['arrival']['branches'].update(escaped='impact'),
    lambda t:t['nodes']['arrival']['cues'][0].update(duration=100),
    lambda t:t['needs']['bang'].update(intensity=0),
])
def test_reject_unsafe_or_unrealizable_trees(mutate):
    t=design();mutate(t)
    with pytest.raises(ValueError):validate_design(t)


def test_history_claim_once_and_exclude_simulations(tmp_path):
    h=History(tmp_path);tree=design();sid=h.draft(tree,{'date':'2026-11-20','surface':'grass'})
    h.publish(sid,tmp_path/'tree.yaml',tree)
    assert h.claim(sid) and not History(tmp_path).claim(sid)
    h.record(result(sid,mode='manual',trial='manual'))
    assert not h.context()['best'] and h.rows()[0]['status']=='in_use'
    h.record(result(sid,trial='field'))
    h.record(result(sid,trial='field'))
    assert h.rows()[0]['status']=='used' and h.context()['field_trials']==1
    h.record(result(sid,trial='aborted',outcome='interrupted',score=None))
    assert h.context()['field_trials']==1


def test_shorter_and_less_intense_escape_scores_better():
    t=design();t['story']['id']='test'
    e=Engine(validate_design(t));e.start(0,100,['one'])
    a=Trial(e,0,'field');a.observe(2,e,[],False);quick=a.finish('escaped',2)
    b=Trial(e,0,'field');b.observe(6,e,[],False);slow=b.finish('escaped',12)
    assert quick['score']>slow['score']
    e._enter('impact',0,100,'no_escape')
    c=Trial(e,0,'field');c.observe(2,e,[],False);loud=c.finish('escaped',2)
    assert quick['score']>loud['score']
    assert c.finish('escaped',3) is None


def test_actual_event_exposure_not_entire_scene_or_unplayed_branches():
    t=validate_design(design());t['nodes']['arrival']['events']=[{'asset_id':'motor','start':1.,'duration':1.}]
    e=Engine(t);e.start(0,100,['one']);trial=Trial(e,0)
    trial.observe(.5,e,[],False);assert trial.dose==0
    trial.observe(1.5,e,[],False);assert trial.dose==pytest.approx(.5/9)
    trial.observe(5,e,[],False);assert trial.dose==pytest.approx(1/9) and trial.impulses==0


def test_repeated_material_failure_does_not_block_generation_forever(tmp_path):
    h=History(tmp_path);sid=h.draft(design(),{'date':'x','surface':'grass'})
    for _ in range(3):h.fail_draft(sid)
    assert h.rows()[0]['status']=='unrealizable' and h.next_sequence()==2

def test_all_time_best_survives_many_recent_failures(tmp_path):
    h=History(tmp_path);h.record(result(trial='champion',score=95))
    for i in range(110):h.record(result(trial=f'failure-{i}',score=0,outcome='not_escaped'))
    assert h.context()['best'][0]['trial_id']=='champion' and h.context()['field_trials']==111


def test_replenish_waits_for_outcome_then_uses_it(tmp_path,monkeypatch):
    import geniac_scenario.stock as stock
    from geniac_scenario.prepare import compile_tree
    import numpy as np
    from scipy.io import wavfile
    today=datetime.now(JST).date().isoformat();weather={'date':today,'surface':'grass'}
    calls=[]
    def generate(w,context,sequence,config,**kwargs):
        calls.append(context);tree=validate_design(design());tree['story']['weather']=w
        return tree
    wav=tmp_path/'fixture.wav';wavfile.write(wav,24000,np.full(24000,.1,dtype=np.float32))
    def acquire(tree,root,config):return {'assets':{key:{'file':str(wav),'duration':1.,'license':'test','attribution':'test'} for key in tree['needs']}}
    monkeypatch.setattr(stock,'generate',generate);monkeypatch.setattr(stock,'acquire',acquire)
    assert stock.replenish(tmp_path,{},count=1,weather=weather)==1
    first=Stock(tmp_path).next(consume=True);assert first and Stock(tmp_path).next(consume=True) is None
    assert stock.replenish(tmp_path,{},count=1,weather=weather)==0 and len(calls)==1
    h=History(tmp_path);sid=h.rows()[0]['id'];h.record(result(sid,trial='done'))
    assert stock.replenish(tmp_path,{},count=1,weather=weather)==1 and len(calls)==2
    assert calls[1]['field_trials']==1 and calls[1]['best'][0]['story_id']==sid
    assert Stock(tmp_path).next(consume=True)!=first


def test_campaign_scores_escape_at_confirmation_not_withdrawal_end():
    from geniac_scenario.story import story_tree
    from geniac_scenario.campaign import Campaign
    recorded=[];c=Campaign(story_tree({'surface':'grass'}),sink=recorded.append,mode='field')
    def report(label):return {'valid':True,'epoch':c.core.epoch,'targets':[{'id':'one','label':label,'present':label!='escaped','stationary_seconds':2.}]}
    c.tick(0,100,report('no_escape'));c.tick(3,103,report('escaped'))
    assert len(recorded)==1 and recorded[0]['escape_seconds']==3 and c.core.node_id=='escaped_end'
    c.tick(9,109,report('escaped'));c.tick(10,110,report('escaped'));c.stop()
    assert len(recorded)==1

def test_without_field_results_improves_previous_concept_not_fake_scores():
    previous={'id':'previous','direction':'machine','premise':'unassessed'}
    strategy,parent=strategy_for(2,{'recent_concepts':[previous]})
    assert strategy=='improve' and parent['story_id']=='previous' and parent['score'] is None
    assert strategy_for(3,{'recent_concepts':[previous]})[0]=='explore'


def test_rejected_generation_gets_bounded_correction():
    calls=[]
    class Response:
        status_code=200
        def json(self):
            t=design()
            if len(calls)==1:t['nodes']['arrival']['branches']['escaped']='impact'
            else:t={'changes':[{'path':'/nodes/arrival/branches/escaped','value_json':'"end"','reason':'escape ends playback'}]}
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(t)}}]}
    def post(*args,**kwargs):calls.append(copy.deepcopy(kwargs['json']));return Response()
    generate({'surface':'grass'},{},1,{'OPENAI_API_KEY':'fake'},post)
    assert len(calls)==2 and 'validation_error' in calls[1]['messages'][-1]['content']

def test_search_query_fallback_keeps_requested_sound_and_weather():
    from geniac_scenario.stock import search_queries
    queries=search_queries({'kind':'footsteps','queries':['distant human footsteps on grass field recording']},'grass')
    assert queries[0]=='footsteps grass'
    queries=search_queries({'kind':'voice','queries':['short handheld radio squelch click field recording']},'grass')
    assert queries[0]=='handheld radio squelch click' and 'handheld radio' not in queries

def test_model_array_normalization_and_unknown_scene_guard():
    t=design();t['nodes']['uncertain']=copy.deepcopy(t['nodes']['arrival'])
    t['nodes']['uncertain']['branches']={key:'end' for key in t['nodes']['uncertain']['branches']}
    t['nodes']['arrival']['branches']['unknown']='uncertain'
    t['nodes']=[dict(value,id=key) for key,value in t['nodes'].items()]
    t=validate_design(t)
    destination=t['nodes']['arrival']['branches']['unknown']
    assert t['nodes'][destination]['terminal'] and 'uncertain' not in t['nodes']
    assert t['story']['policy_adjustments']


def test_duplicate_model_array_ids_rejected():
    t=design();t['nodes']=[dict(t['nodes']['arrival'],id='same')]*2
    with pytest.raises(ValueError,match='Duplicate'):validate_design(t)

def human_arrival_design():
    t=design();t['story']['arrival'].update(actor_kind='human',actor='作業員',travel_mode='vehicle')
    t['needs']['motor']['event']='transport'
    t['needs']['voice']={'kind':'voice','intensity':1,'description':'作業員の声','queries':['human voice call'],'speech_required':True}
    t['nodes']['arrival']['cues'].append({'role':'voice','start':0,'duration':1,'gain_db':-20})
    t['needs']['stop']={'kind':'mechanical','intensity':1,'description':'車が停車する','event':'stop','queries':['car engine stop']}
    t['needs']['door']={'kind':'mechanical','intensity':1,'description':'車から降りる','event':'exit','queries':['car door close']}
    arrival=copy.deepcopy(t['nodes']['arrival']);arrival['stage']='arrival'
    arrival['cues']=[{'role':'stop','start':0,'duration':2,'gain_db':-20},{'role':'door','start':3,'duration':1,'gain_db':-20}]
    t['nodes']['parking']=arrival;t['nodes']['arrival']['branches']['no_escape']='parking'
    return t


def test_human_vehicle_requires_audible_arrival_before_approach():
    t=human_arrival_design();validate_design(t,require_arrival=True)
    t=human_arrival_design();t['nodes']['arrival']['branches'].update(no_escape='impact',retreated_nearby='parking')
    with pytest.raises(ValueError,match='before vehicle'):validate_design(t,require_arrival=True)
    t=human_arrival_design();t['nodes']['parking']['cues'].pop()
    with pytest.raises(ValueError,match='stopping'):validate_design(t,require_arrival=True)


def test_missing_origin_is_not_a_credible_story():
    t=design();del t['story']['arrival']['origin']
    with pytest.raises(ValueError,match='origin'):validate_design(t,require_arrival=True)


def test_generation_refreshes_weather_even_with_recent_cache(tmp_path,monkeypatch):
    import geniac_scenario.stock as stock
    today=datetime.now(JST).date().isoformat()
    old={'date':today,'surface':'grass','fetched_at':'old'};new=dict(old,surface='rain',fetched_at='new')
    stock.atomic_json(tmp_path/'weather.json',old);fetched=[];seen=[]
    def weather():fetched.append(True);return new
    def generation(w,*args,**kwargs):seen.append(w);raise RuntimeError('Stop before API/material acquisition')
    monkeypatch.setattr(stock,'fetch_weather',weather);monkeypatch.setattr(stock,'generate',generation)
    with pytest.raises(RuntimeError):stock.replenish(tmp_path,{},count=1)
    assert len(fetched)==1 and seen[0]['fetched_at']=='new' and seen[0]['surface']=='rain'


def test_missing_final_attack_rejected():
    from geniac_scenario.evolving import validate_climax
    t=design();t['nodes']['arrival']['branches']['retreated_nearby']='impact';validate_climax(t)
    del t['needs']['bang']['event']
    with pytest.raises(ValueError,match='explicit attack'):validate_climax(t)


def test_partial_then_stationary_cannot_end_without_attack():
    from geniac_scenario.evolving import validate_climax
    t=design();t['nodes']['partial']=copy.deepcopy(t['nodes']['arrival'])
    t['nodes']['arrival']['branches']['retreated_nearby']='partial'
    t['nodes']['partial']['branches']['no_escape']='end'
    with pytest.raises(ValueError,match='explicit attack'):validate_climax(t)


def test_vehicle_query_never_loses_vehicle():
    from geniac_scenario.stock import search_queries
    assert search_queries({'queries':['small utility vehicle']},'grass')==['small utility vehicle']


def test_wrong_and_short_vehicle_assets_never_download(tmp_path,monkeypatch):
    import geniac_scenario.stock as stock
    t=design();t['story']['weather']={'surface':'grass'}
    t['needs']={'motor':dict(t['needs']['motor'],event='transport')}
    t['nodes']={'arrival':t['nodes']['arrival']}
    t['nodes']['arrival']['cues'][0]['duration']=6
    candidates=[{'id':'knife','duration':.7},{'id':'music','duration':20}]
    monkeypatch.setattr(stock,'search',lambda *a:candidates)
    checked=[]
    def verify(need,item,config):checked.append(item['id']);return None
    monkeypatch.setattr(stock,'verify_candidate',verify)
    monkeypatch.setattr(stock,'download',lambda *a:pytest.fail('Must not download mismatched material'))
    with pytest.raises(ValueError,match='No verified recording'):stock.acquire(t,tmp_path,{})
    assert checked==['music']


def ready_fixture(root):
    today=datetime.now(JST).date().isoformat()
    tree=design();tree['story']['weather']={'date':today,'surface':'grass'}
    h=History(root);sid=h.draft(tree,tree['story']['weather'])
    folder=root/sid;folder.mkdir()
    for node in tree['nodes'].values():
        if not node.get('terminal'):
            node['audio']='sound.wav'
    (folder/'sound.wav').write_bytes(b'fixture')
    path=folder/'tree.yaml';path.write_text(yaml.safe_dump(tree))
    h.publish(sid,path,tree)
    return h,sid,path


def test_bad_entry_does_not_hide_good_stock(tmp_path):
    h,sid,path=ready_fixture(tmp_path)
    _,bad_id,bad_path=ready_fixture(tmp_path)
    bad_path.write_text('invalid: [')
    assert Stock(tmp_path).ready()==[path]


def test_completed_story_is_reused_after_refill_failure(tmp_path,monkeypatch):
    import geniac_scenario.stock as stock
    h,sid,path=ready_fixture(tmp_path)
    assert Stock(tmp_path).next(consume=True)==path
    assert Stock(tmp_path).next(consume=True) is None
    h.record(result(sid,trial='first'))
    def fail(*a,**k):raise ValueError('Invalid generated cue')
    monkeypatch.setattr(stock,'generate',fail)
    with pytest.raises(ValueError):stock.replenish(tmp_path,{},count=1,weather=load_weather(path))
    assert Stock(tmp_path).next(consume=True)==path
    assert Stock(tmp_path).next(consume=True) is None
    h.record(result(sid,trial='repeat'))
    assert h.context()['field_trials']==2


def load_weather(path):return yaml.safe_load(path.read_text())['story']['weather']


def test_new_story_precedes_reserve_and_weather_mismatch_is_not_reused(tmp_path):
    h,sid,path=ready_fixture(tmp_path)
    h.claim(sid);h.record(result(sid))
    _,new_sid,new_path=ready_fixture(tmp_path)
    assert Stock(tmp_path).next()==new_path
    (tmp_path/'weather.json').write_text(json.dumps(dict(load_weather(path),surface='snow')))
    assert Stock(tmp_path).next() is None


def test_timing_only_changes_are_rejected_but_cast_changes_are_allowed():
    from geniac_scenario.evolving import validate_variation
    t=design();validate_variation(t,{})
    context={'recent_concepts':[t['story']]}
    changed=copy.deepcopy(t)
    changed['nodes']['arrival']['duration']=12
    changed['nodes']['arrival']['cues'][0]['gain_db']=-5
    changed['story']['title']='別の題名'
    with pytest.raises(ValueError,match='Timing'):validate_variation(changed,context)
    changed['story']['variation'].update(actor_count=2,roles=['運転役','探索役'],approach='split')
    validate_variation(changed,context)


def test_dialogue_requires_voice_not_radio_click():
    from geniac_scenario.evolving import validate_variation
    t=design();t['story']['variation']['dialogue']='radio_exchange'
    with pytest.raises(ValueError,match='voice'):validate_variation(t,{})
    t['needs']['motor']['kind']='voice'
    validate_variation(t,{})
    t['story']['variation']['dialogue']='conversation'
    with pytest.raises(ValueError,match='multiple'):validate_variation(t,{})


def test_vehicle_name_change_requires_different_sound_queries():
    from geniac_scenario.evolving import validate_variation
    t=design();t['needs']['motor']['event']='transport'
    validate_variation(t,{})
    previous=copy.deepcopy(t['story']);previous['sound_plan']=copy.deepcopy(t['needs'])
    t['story']['variation']['vehicle']='motorcycle'
    with pytest.raises(ValueError,match='Changing vehicle'):validate_variation(t,{'recent_concepts':[previous]})
    t['needs']['motor']['queries']=['motorcycle approaching']
    validate_variation(t,{'recent_concepts':[previous]})


def test_running_queries_preserve_gait_and_weather():
    from geniac_scenario.stock import search_queries
    q=search_queries({'kind':'footsteps','queries':['running footsteps grass']},'snow')
    assert q[0]=='running footsteps snow'
    assert 'footsteps snow' not in q
    assert search_queries({'kind':'footsteps','queries':['sneaking footsteps']},'rain')[0]=='stealth footsteps puddles'


def test_manual_consumption_frees_slot_without_field_learning(tmp_path):
    h,sid,path=ready_fixture(tmp_path)
    assert h.consume_manual(sid)
    assert not h.consume_manual(sid)
    assert h.rows()[0]['status']=='used'
    assert Stock(tmp_path).ready()==[]
    assert Stock(tmp_path).next()==path  # reserve until replacement arrives
    h.record(result(sid,mode='manual',trial='manual-only'))
    assert h.context()['field_trials']==0 and not h.context()['best']


def test_manual_consumption_does_not_take_field_claim(tmp_path):
    h,sid,path=ready_fixture(tmp_path)
    assert h.claim(sid)
    assert not h.consume_manual(sid)
    assert h.rows()[0]['status']=='in_use'


def test_progress_updates_preserve_story_number_and_stage_clock(tmp_path):
    from geniac_scenario.stock import report_progress
    report_progress(tmp_path,status='acquiring',sequence=23,completed=0,total=5)
    first=json.loads((tmp_path/'status.json').read_text())
    report_progress(tmp_path,status='acquiring',completed=2,item='足音')
    second=json.loads((tmp_path/'status.json').read_text())
    assert second['sequence']==23 and second['total']==5 and second['completed']==2
    assert second['stage_started']==first['stage_started']


def test_failed_material_is_context_and_cannot_be_renamed(tmp_path):
    from geniac_scenario.evolving import validate_material_history
    h=History(tmp_path);tree=design();sid=h.draft(tree,{'date':'2026-11-20','surface':'grass'})
    failure={'role':'bang','need':copy.deepcopy(tree['needs']['bang']),
             'search_queries':tree['needs']['bang']['queries'],'reason':'No verified recording'}
    h.fail_draft(sid,failure)
    assert h.rows()[0]['status']=='unrealizable'
    context=h.context();assert context['material_failures'][0]['reason']=='No verified recording'
    renamed=design();renamed['needs']['different_id']=renamed['needs'].pop('bang')
    with pytest.raises(ValueError,match='Recently unavailable'):validate_material_history(renamed,context)
    renamed['needs']['different_id'].update(description='別の実現可能な動作',queries=['rifle gunshot'])
    validate_material_history(renamed,context)


def test_transient_failure_does_not_blacklist_material(tmp_path):
    h=History(tmp_path);sid=h.draft(design(),{'date':'2026-11-20','surface':'grass'})
    h.fail_draft(sid)
    assert h.rows()[0]['status']=='draft' and h.context()['material_failures']==[]


def test_visible_deer_paths_reach_attack_and_escape_is_unchanged():
    from geniac_scenario.evolving import route_visible_to_attack
    t=route_visible_to_attack(design())
    assert t['nodes']['arrival']['branches']['retreated_nearby']=='impact'
    assert t['nodes']['arrival']['branches']['escaped']=='end'
    validate_design(t)


def test_multiple_humans_require_speech():
    from geniac_scenario.evolving import validate_variation
    t=design();t['story']['arrival']['actor_kind']='human'
    t['story']['variation'].update(actor_count=2,roles=['運転','探索'])
    with pytest.raises(ValueError,match='Multiple humans'):validate_variation(t,{})
    t['story']['variation']['dialogue']='radio_exchange'
    t['needs']['motor'].update(kind='voice',queries=['radio speech'])
    validate_variation(t,{})
    assert t['needs']['motor']['speech_required']


def test_every_visible_response_combination_reaches_and_repeats_attack():
    from itertools import product
    from geniac_scenario.tree import Engine
    t=design()
    t['nodes']['arrival']['branches']['no_escape']='end'
    t['nodes']['arrival']['branches']['retreated_nearby']='detour'
    t['nodes']['detour']=copy.deepcopy(t['nodes']['arrival'])
    t['nodes']['detour']['branches'].update(no_escape='impact',retreated_nearby='end')
    for labels in product(('no_escape','retreated_nearby'),repeat=4):
        e=Engine(t);e.start(0,100,['one'])
        for i,label in enumerate(labels,1):
            assert e.tick(i*6,100+i*6,{'epoch':e.epoch,'valid':True,'targets':[{'id':'one','label':label,'present':True}]})
            assert e.running
        assert e.node_id=='impact' and e.reason.startswith('repeat_final_')
        assert e.tick(25,125,{'epoch':e.epoch,'valid':True,'targets':[{'id':'one','label':'escaped','present':False}]})
        assert not e.running


def test_climax_rejects_visible_only_bypass():
    from geniac_scenario.evolving import validate_climax
    with pytest.raises(ValueError,match='explicit attack'):
        validate_climax(design())


def test_generated_schema_distinguishes_cast_from_audio_references():
    from geniac_scenario.story_schema import SCHEMA,SOUND_IDS
    scene=SCHEMA['properties']['nodes']['items']['anyOf'][0]
    cue=scene['properties']['cues']['items']
    assert 'role' not in cue['properties']
    assert set(cue['properties']['sound_id']['enum'])==set(SOUND_IDS)
    assert 'radio_operator' not in cue['properties']['sound_id']['enum']


def test_explicit_sound_ids_resolve_before_climax_validation():
    t=design()
    for node in t['nodes'].values():
        for cue in node.get('cues',[]):cue['sound_id']=cue.pop('role')
    checked=validate_design(t,require_arrival=True)
    assert checked['nodes']['impact']['cues'][0]['role']=='bang'
    assert 'sound_id' not in checked['nodes']['impact']['cues'][0]


def test_actor_role_reference_reports_root_cause_not_missing_attack():
    t=design();t['nodes']['impact']['cues'][0]['role']='forward_searcher'
    with pytest.raises(ValueError,match='NOT story.variation.roles'):
        validate_design(t,require_arrival=True)


def test_attack_definition_must_be_referenced_by_a_scene():
    t=design();t['nodes']['impact']['cues'][0]['role']='motor'
    with pytest.raises(ValueError,match='not connected to audio'):
        validate_design(t,require_arrival=True)


def test_normal_improvement_always_uses_champion_not_recent_success():
    champion=result(sid='best',score=90)
    recent=result(sid='explore',score=85,strategy='explore')
    for sequence in (1,2,4,5,7,8):
        assert strategy_for(sequence,{'best':[champion],'recent':[recent]})[1]['story_id']=='best'
    assert strategy_for(4,{'best':[recent],'recent':[recent]})[1]['story_id']=='explore'


def test_provisional_scores_do_not_override_field_champion():
    field=result(sid='field',score=50)
    simulated=result(sid='test',score=100,mode='simulation')
    assert strategy_for(4,{'best':[field],'provisional_best':[simulated]})[1]['story_id']=='field'
    assert strategy_for(4,{'provisional_best':[simulated]})[1]['story_id']=='test'


def test_no_scores_keeps_baseline_after_exploration():
    base={'id':'baseline','strategy':'seed'}
    context={'baseline_concept':base,'recent_concepts':[{'id':'new','strategy':'explore'}]}
    assert strategy_for(4,context)[1]['story_id']=='baseline'


def test_used_story_cross_day_requires_matching_current_surface(tmp_path):
    h,sid,path=ready_fixture(tmp_path)
    h.claim(sid);h.record(result(sid))
    tomorrow='2099-01-01'
    stock=Stock(tmp_path)
    assert stock.ready(tomorrow,status='used')==[]
    (tmp_path/'weather.json').write_text(json.dumps({'date':tomorrow,'surface':'grass'}))
    assert stock.ready(tomorrow,status='used')==[path]
    assert stock.ready(tomorrow)==[]
    (tmp_path/'weather.json').write_text(json.dumps({'date':tomorrow,'surface':'rain'}))
    assert stock.ready(tomorrow,status='used')==[]
    (tmp_path/'weather.json').write_text(json.dumps({'date':'2000-01-01','surface':'grass'}))
    assert stock.ready(tomorrow,status='used')==[]
