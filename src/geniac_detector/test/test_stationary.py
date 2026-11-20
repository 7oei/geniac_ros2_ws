import inspect
import numpy as np
import pytest
from geniac_detector.core.tracking import Tracker
from geniac_detector.engine import Settings

def obs(x):return {'center':[x,0,1],'lo':[x-.5,-.2,0],'hi':[x+.5,.2,2],'score':.95,'n':50}

def test_stationary_tracking_without_odometry_or_icp():
    tr=Tracker();ids=[]
    for i in range(12):
        out,motion=tr.update([obs(10+i*.4)],np.empty((0,4)),1+i*.1)
        ids.append(out[0]['track_id']);assert motion['mode']=='stationary_sensor' and not motion['enabled']
    assert len(set(ids))==1 and out[0]['state']=='observed_candidate'
    assert 'ego' not in inspect.signature(Tracker).parameters
    with pytest.raises(TypeError):Settings(ego_compensation=True)

def test_tracks_expire_and_ids_never_reused():
    t=Tracker();a=t.update([obs(10)],np.empty((0,4)),1)[0][0]['track_id']
    for i in range(11):assert t.update([],np.empty((0,4)),1.1+i*.1)[0]==[]
    b=t.update([obs(10)],np.empty((0,4)),2.2)[0][0]['track_id'];assert b>a

def test_confirmed_tracks_are_json_serializable():
    import json
    from pathlib import Path
    from geniac_detector.engine import Engine
    p=Path(__file__).parents[1]
    cloud=np.load(p/'test/fixtures/deer_cloud.npz')['points']
    engine=Engine(p/'models/forest_camera_v2.json')
    for i in range(3):tracks,meta=engine.process(cloud,1_000_000_000+i*100_000_000)
    assert len(json.loads(json.dumps(tracks,allow_nan=False)))>=2


def test_speed_gate_rejects_jump_even_with_matching_prediction():
    t=Tracker(max_speed_mps=5.,position_tolerance_m=0.)
    t.update([obs(10)],None,1.)
    t.tracks[0]['velocity']=np.array([12.,0.,0.])
    out,meta=t.update([obs(11.2)],None,1.1)
    assert out[0]['track_id']==2 and out[0]['state']=='tentative'
    assert meta['speed_gate_rejected_pairs']==1


def test_gap_uses_last_actual_observation_for_speed():
    t=Tracker(max_speed_mps=5.,position_tolerance_m=.01)
    t.update([obs(10)],None,1.)
    t.update([obs(10.4)],None,1.1)
    t.update([],None,1.2)
    out,_=t.update([obs(11.2)],None,1.3)
    assert out[0]['track_id']==1
    assert out[0]['speed_mps']==pytest.approx(4.)


def test_speed_gate_before_assignment_preserves_valid_alternative():
    t=Tracker(max_speed_mps=1.,position_tolerance_m=0.)
    t.update([obs(10),obs(11)],None,1.)
    # Predictions are swapped; speed constraint must precede assignment.
    t.tracks[0]['velocity']=np.array([10.,0.,0.])
    t.tracks[1]['velocity']=np.array([-10.,0.,0.])
    out,_=t.update([obs(10.05),obs(11.05)],None,1.1)
    assert {x['track_id']:x['center'][0] for x in out}=={1:10.05,2:11.05}


def test_speed_parameter_validation_and_reset():
    from geniac_detector.engine import Engine
    from pathlib import Path
    with pytest.raises(ValueError):Settings(max_speed_mps=0.)
    with pytest.raises(ValueError):Settings(position_tolerance_m=-.1)
    e=Engine(Path(__file__).parents[1]/'models/forest_camera_v2.json',Settings(max_speed_mps=4.,position_tolerance_m=.1))
    e.reset();assert e.tracker.max_speed_mps==4. and e.tracker.position_tolerance_m==.1


def test_id_survives_ten_missing_frames_without_output():
    t=Tracker();first=t.update([obs(10)],None,1.)[0][0]['track_id']
    for i in range(10):assert t.update([],None,1.1+i*.1)[0]==[]
    assert t.update([obs(10)],None,2.1)[0][0]['track_id']==first
