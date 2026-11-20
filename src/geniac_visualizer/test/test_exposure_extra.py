import numpy as np
from geniac_visualizer.exposure import AutoExposure

def test_feedback_adjusts_dark_then_bright_and_restores():
    a=AutoExposure('/dev/video0');calls=[]
    def command(*args):
        calls.extend(args)
        if args==('--list-ctrls-menus',):return 'exposure_time_absolute (int) : min=50 max=10000 value=166\n1: Manual Mode'
        return ''
    a.command=command;a.start()
    assert a.active
    for _ in range(10):
        a.next_update=0;a.update(np.zeros((80,80,3),dtype=np.uint8))
    assert a.current==1000
    for _ in range(10):
        a.next_update=0;a.update(np.full((80,80,3),255,dtype=np.uint8))
    assert a.current==50
    a.close()
    assert calls[-1]=='--set-ctrl=auto_exposure=3'
