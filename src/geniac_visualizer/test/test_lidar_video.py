import numpy as np
from geniac_visualizer.lidar_video import Raster


def test_projection_and_nearest_point_per_pixel():
    r=Raster(120,80)
    r.add(np.array([[10,0,0],[5,0,0],[np.nan,0,0],[-1,0,0],[1,100,0]]),0.)
    depth=r.frames[0][1].reshape(80,120)
    assert depth[40,60]==5 and np.isfinite(depth).sum()==1
    u,v,_=r.project([[10,1,1]])
    assert u[0]<60 and v[0]<40


def test_ten_frame_bound_and_expiry():
    r=Raster(120,80)
    for i in range(15):r.add([[5,i/10,0]],i*.1)
    assert len(r.frames)==10 and r.frames[0][0]==.5
    assert r.render(1.5).shape==(80,120,3)
    r.render(4.)
    assert not r.frames


def test_old_points_fade_newest_points_do_not():
    r=Raster(120,80)
    r.add([[5,0,-2]],0.)
    u,v,_=r.project([[5,0,-2]])
    old=r.render(.1)[v[0],u[0]].copy()
    r.add([[5,2,-2]],.1)
    faded=r.render(.2)[v[0],u[0]]
    # The near-red point blends toward the dark background as it ages.
    assert faded[2]<old[2]
