from pathlib import Path
from types import SimpleNamespace as S
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geniac_detector.cloud import decode_cloud
from geniac_detector.engine import Engine, Settings, LatestCloud, timestamp_error

PKG = Path(__file__).resolve().parents[1]


def test_organized_big_endian_padding_and_missing_intensity():
    buf = bytearray(96)
    dtype = np.dtype(dict(names=['x','y','z','intensity'],formats=['>f4']*4,offsets=[0,4,8,12],itemsize=20))
    a = np.ndarray((2,2),dtype=dtype,buffer=buf,strides=(48,20))
    for i,n in enumerate(dtype.names): a[n] = np.arange(4).reshape(2,2)+i
    msg=S(height=2,width=2,point_step=20,row_step=48,is_bigendian=True,data=buf,
          fields=[S(name=n,offset=i*4,count=1,datatype=7) for i,n in enumerate(dtype.names)])
    np.testing.assert_allclose(decode_cloud(msg),np.arange(4)[:,None]+np.arange(4))
    msg.fields=msg.fields[:3]
    with pytest.raises(ValueError,match='intensity'):decode_cloud(msg)


def test_overload_and_stream_discontinuity():
    slot=LatestCloud()
    def msg(t,frame='livox_frame'):return S(header=S(frame_id=frame,stamp=S(sec=t,nanosec=0)))
    for i in range(1,101):slot.put(msg(i),float(i))
    latest,received,epoch=slot.take()
    assert latest.header.stamp.sec==100 and slot.replaced==99 and slot.take() is None
    slot.put(msg(5),101.)
    assert slot.take()[2]>epoch
    epoch=slot.epoch;slot.put(msg(6,'other_lidar'),102.)
    assert slot.take()[2]>epoch


def test_timestamp_and_parameter_guards():
    assert timestamp_error(1_000_000_000,2_000_000_000,.35,.05)=='stale_cloud'
    assert timestamp_error(2_000_000_000,1_000_000_000,.35,.05).startswith('future')
    assert timestamp_error(0,0,.35,.05)
    assert timestamp_error(1_000_000_000,1_100_000_000,.35,.05) is None
    with pytest.raises(ValueError):Settings(min_score=float('nan'))
    with pytest.raises(ValueError):Settings(tf_prefix='/bad')


def test_real_cloud_confirmation_missing_and_id_nonreuse():
    p=np.load(PKG/'test/fixtures/deer_cloud.npz')['points']
    engine=Engine(PKG/'models/forest_camera_v2.json')
    a,_=engine.process(p,1_000_000_000);assert not a
    engine.process(p,1_100_000_000)
    tracks,meta=engine.process(p,1_200_000_000)
    assert len(tracks)>=2 and meta['ground_quality']>=.35
    old_ids={t['track_id'] for t in tracks}
    assert not engine.process(np.empty((0,4),np.float32),1_300_000_000)[0]
    engine.reset()
    for i in range(3):tracks,_=engine.process(p,2_000_000_000+i*100_000_000)
    assert not old_ids & {t['track_id'] for t in tracks}
