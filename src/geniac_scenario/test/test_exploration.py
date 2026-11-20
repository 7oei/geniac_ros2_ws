import pytest
from test_evolving import design
from geniac_scenario.exploration import ELEMENTS,choose,validate,history_summary


def test_unused_elements_preferred_over_drone():
    context={'exploration_counts':{'drone':10,'truck':20}}
    for _ in range(60):
        plan=choose(context,{'surface':'grass'})
        assert plan['element'] not in ('drone','truck','snowmobile')
        assert plan['new_element']


def test_all_used_selects_least_used_and_snow_permits_snowmobile():
    counts={key:3 for key in ELEMENTS};counts['snowmobile']=0
    assert choose({'exploration_counts':counts},{'surface':'snow'})['element']=='snowmobile'
    counts['wolf']=1
    assert choose({'exploration_counts':counts},{'surface':'grass'})['element']=='wolf'


def test_novelty_requires_actual_sound_reference():
    t=design();t['story']['premise']='猟犬の登場'
    plan={'element':'hunting_dog','name':'猟犬'}
    with pytest.raises(ValueError):validate(t,plan)
    t['needs']['motor']['description']='hunting dog barking'
    validate(t,plan)
    assert history_summary([t,t])['hunting_dog']==2


def test_historical_plan_suggestions_are_not_counted():
    t=design();t['story']['exploration_plan']={'name':'ドローン'}
    assert 'drone' not in history_summary([t])
