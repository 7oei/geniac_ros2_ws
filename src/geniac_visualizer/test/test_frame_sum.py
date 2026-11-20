import numpy as np
from geniac_visualizer.frame_sum import FrameSum,luminance

def frame(value):return np.full((8,8,3),value,dtype=np.uint8)

def test_dark_frames_add_to_target_without_overflow():
    s=FrameSum()
    for _ in range(20):out=s.apply(frame(9),True)
    assert abs(luminance(out)-80)<=1
    assert len(s.frames)==9

def test_bright_frame_and_disabled_clear_history():
    s=FrameSum();s.apply(frame(9),True)
    assert np.array_equal(s.apply(frame(180),True),frame(180))
    assert not s.frames
    s.apply(frame(9),True);s.apply(frame(9),False)
    assert not s.frames

def test_black_history_is_bounded_and_old_frames_expire():
    s=FrameSum(max_frames=3)
    s.apply(frame(20),True)
    for _ in range(6):out=s.apply(frame(0),True)
    assert len(s.frames)==3 and not out.any()

def test_saturation_is_measured_after_clipping():
    s=FrameSum();a=frame(4);a[:2]=200
    for _ in range(40):out=s.apply(a,True)
    assert abs(luminance(out)-80)<=1
    assert out.max()==255
