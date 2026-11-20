from geniac_scenario.assets import search,download,preview_url
import pytest

class Response:
    status_code=200
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def json(self):return {'results':[{'id':1,'name':'steps','username':'author','license':'CC0','duration':2,
        'url':'https://freesound.org/s/1/','previews':{'preview-hq-mp3':'https://cdn.freesound.org/previews/1/1.mp3'}}]}
    def iter_content(self,n):yield b'fake-test-media'
class HTTP:
    def __init__(self):self.calls=[]
    def get(self,*a,**k):self.calls.append((a,k));return Response()

def test_search_download_keep_attribution_and_do_not_forward_key(tmp_path):
    http=HTTP();rows=search('footsteps','not-a-real-key',http)
    out=download(rows[0],tmp_path/'clip.mp3',http)
    assert out['license']=='CC0' and out['attribution']=='author — steps'
    assert 'headers' not in http.calls[1][1]
    assert (tmp_path/'clip.mp3.json').exists()

def test_download_url_validation():
    for url in ['http://cdn.freesound.org/previews/a','https://other.example/previews/a','https://cdn.freesound.org/private/a']:
        assert not preview_url(url)
    with pytest.raises(ValueError):search('test','')

def test_download_does_not_remove_existing_partial(tmp_path):
    p=tmp_path/'audio.mp3';partial=tmp_path/'audio.mp3.partial';partial.write_bytes(b'owned elsewhere')
    row=search('test','fake',HTTP())[0]
    with pytest.raises(FileExistsError):download(row,p,HTTP())
    assert partial.read_bytes()==b'owned elsewhere'


@pytest.mark.parametrize('payload',[
    {'match':False,'evidence':'utility knife, not a vehicle'},
    {'match':'true','evidence':'ambiguous'},
    {'match':True,'evidence':''},
])
def test_semantic_verification_fails_closed(payload):
    import json
    from geniac_scenario.assets import verify_candidate
    class Reply:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}]}
    assert verify_candidate({'description':'vehicle approach'},{'description':'Small Cutter Utility knife'},
                            {'OPENAI_API_KEY':'fake'},lambda *a,**k:Reply()) is None


def test_semantic_verification_preserves_audit_evidence():
    import json
    from geniac_scenario.assets import verify_candidate
    class Reply:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'match':True,'evidence':'Truck driving past microphone'})}}]}
    verification=verify_candidate({}, {}, {'OPENAI_API_KEY':'fake'},lambda *a,**k:Reply())
    assert verification['policy_version']==3 and 'not auditioned' in verification['method']


def test_music_veto_cannot_be_overridden_by_model():
    from geniac_scenario.assets import verify_candidate,forbidden_material
    candidate={'description':'Gun Click Jam 130BPM gun sync',
               'details':'Weapon handling click sample music loop 130 bpm.',
               'tags':['handling','reload','music']}
    assert forbidden_material(candidate)
    assert verify_candidate({},candidate,{},lambda *a,**k:pytest.fail('Music must be rejected before model')) is None
    assert not forbidden_material({'description':'Single rifle gunshot','tags':['rifle']})


def test_radio_noise_cannot_satisfy_human_speech():
    from geniac_scenario.assets import verify_candidate,speech_evidence
    candidate={'description':'Squelch.wav','details':'Squelch tones in a VHF communications channel','tags':['Radio','Communications']}
    assert not speech_evidence(candidate)
    assert verify_candidate({'speech_required':True},candidate,{},lambda *a,**k:pytest.fail('Squelch must be vetoed')) is None
    assert speech_evidence({'description':'Two people talking over radio','tags':['speech']})


@pytest.mark.parametrize('candidate',[
    {'description':'DOOR OPEN CLOSE-004.wav','details':'Door Open Close','tags':['Door','Open','Close']},
    {'description':'Door opening and closing 5','details':'Extremely squeaky door','tags':['wood','wooden','open']},
    {'description':'Car door slam','tags':['car','door','slam']},
])
def test_vehicle_exit_requires_explicit_car_opening_not_house_or_unspecified(candidate):
    from geniac_scenario.assets import verify_candidate
    need={'event':'exit','description':'運転席から降車する音','queries':['vehicle exit','door opening']}
    assert verify_candidate(need,candidate,{},lambda *a,**k:pytest.fail('Hard veto must precede model')) is None


def test_vehicle_door_positive_evidence_and_story_context():
    from geniac_scenario.assets import context_compatible,manifest_context_valid
    need={'event':'exit','queries':['car door opening']}
    assert context_compatible(need,{'description':'Car Door Opening','tags':['car','open','door']})
    tree={'story':{'arrival':{'travel_mode':'vehicle'}},'needs':{'exit':{'event':'exit','queries':['door opening']}}}
    assert not manifest_context_valid(tree,{'assets':{'exit':{'description':'Door Open Close'}}})


def test_wrong_door_cache_is_not_grandfathered(tmp_path,monkeypatch):
    import hashlib,json
    import numpy as np
    from geniac_scenario import stock
    need={'kind':'mechanical','event':'exit','description':'車のドアを開けて降車','queries':['car door opening']}
    queries=stock.search_queries(need,'grass')
    token=hashlib.sha256(json.dumps([3,need,queries,.5],sort_keys=True).encode()).hexdigest()[:16]
    cache=tmp_path/'assets';cache.mkdir();old=cache/'old.wav';old.touch()
    meta=cache/(token+'.json')
    meta.write_text(json.dumps({'id':'wrong','file':str(old),'description':'wooden house door opening',
                               'verification':{'policy_version':3}}))
    monkeypatch.setattr(stock,'search',lambda *a:[{'id':'car','duration':1,'description':'Car door opening'}])
    monkeypatch.setattr(stock,'verify_candidate',lambda *a:{'policy_version':3,'method':'test'})
    def download(candidate,path):path.touch();return dict(candidate,file=str(path))
    monkeypatch.setattr(stock,'download',download)
    monkeypatch.setattr(stock,'decode',lambda *a:np.ones(24000))
    tree={'story':{'weather':{'surface':'grass'}},'needs':{'door':need},'nodes':{'exit':{'cues':[{'role':'door','duration':1}]}}}
    result=stock.acquire(tree,tmp_path,{})
    assert result['assets']['door']['id']=='car'
    assert meta.with_suffix('.rejected.json').exists()
