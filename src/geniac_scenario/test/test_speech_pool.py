from geniac_scenario.speech_pool import BASE_NEED,save,select,signature,read


def test_ten_distinct_recordings_before_repeat_and_persistent_cursor(tmp_path):
    assets=[];proof={'policy_version':3,'method':'test','evidence':'spoken words'}
    for i in range(10):
        path=tmp_path/f'{i}.mp3';path.touch()
        assets.append({'id':str(i),'file':str(path),'description':f'radio voice phrase {i}'})
    save(tmp_path/'speech_pool.json',{'assets':assets,'recent':[],
        'verified':{signature(BASE_NEED):{a['id']:proof for a in assets}}})
    first=[select(tmp_path,BASE_NEED)['id'] for _ in range(10)]
    assert len(set(first))==10
    assert select(tmp_path,BASE_NEED)['id']==first[0]
    assert select(tmp_path,BASE_NEED)['id']==first[1]


def test_offline_never_uses_unverified_requirement(tmp_path):
    asset=tmp_path/'voice.mp3';asset.touch()
    save(tmp_path/'speech_pool.json',{'assets':[{'id':'1','file':str(asset),'description':'radio speech'}],
        'recent':[],'verified':{}})
    assert select(tmp_path,BASE_NEED) is None
    assert read(tmp_path)['recent']==[]


def test_each_spoken_cue_gets_its_own_slot_idempotently():
    from geniac_scenario.speech_pool import expand_roles
    tree={'needs':{'voice':dict(BASE_NEED)},'nodes':{'one':{'cues':[{'role':'voice'},{'role':'voice'}]},
        'two':{'cues':[{'role':'voice'}]}}}
    expand_roles(tree)
    roles=[cue['role'] for node in tree['nodes'].values() for cue in node['cues']]
    assert len(set(roles))==3
    expand_roles(tree)
    assert set(tree['needs'])==set(roles)
