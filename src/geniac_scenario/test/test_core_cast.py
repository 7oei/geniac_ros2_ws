import copy
import pytest
from test_evolving import design
from geniac_scenario.core_cast import validate
from geniac_scenario.story_repair import LocalRepairError


def dog_tree():
    t=design();t['story']['arrival']['actor']='警備犬';t['story']['variation']['roles']=['guard_dog']
    t['needs']['motor'].update(description='警備犬の草の足音',kind='footsteps',queries=['dog footsteps grass'])
    return t


def barking(t):
    t['needs']['bark']={'kind':'voice','description':'犬の吠え声','queries':['dog barking'],'intensity':1,'speech_required':False}
    t['nodes']['arrival']['cues'].append({'role':'bark','start':0,'duration':1,'gain_db':-10})
    return t


def test_dog_footsteps_do_not_prove_presence():
    t=dog_tree()
    with pytest.raises(LocalRepairError) as err:validate(t)
    assert '/needs/core_dog' in err.value.paths
    validate(barking(t))


def test_unused_or_escape_only_bark_does_not_count():
    t=barking(dog_tree());t['nodes']['arrival']['cues'].pop()
    with pytest.raises(LocalRepairError):validate(t)
    t['nodes']['exit']=copy.deepcopy(t['nodes']['arrival'])
    t['nodes']['exit']['cues']=[{'role':'bark','duration':1}]
    t['nodes']['arrival']['branches']['escaped']='exit'
    with pytest.raises(LocalRepairError):validate(t)


def test_manifest_must_contain_real_bark_metadata():
    t=barking(dog_tree())
    with pytest.raises(ValueError):validate(t,{'assets':{'bark':{'description':'grass footsteps'}}})
    validate(t,{'assets':{'bark':{'description':'Dog barking outdoors'}}})


def test_bypass_branch_missing_core_sound_is_rejected():
    t=barking(dog_tree())
    t['nodes']['impact']['cues']+=t['nodes']['arrival']['cues'][1:]
    t['nodes']['arrival']['cues'].pop()
    with pytest.raises(LocalRepairError):validate(t)


def test_cached_grass_recording_cannot_satisfy_bark_need():
    from geniac_scenario.assets import context_compatible
    need=barking(dog_tree())['needs']['bark']
    assert not context_compatible(need,{'description':'Dog running on grass'})
    assert context_compatible(need,{'description':'Dog barking'})
