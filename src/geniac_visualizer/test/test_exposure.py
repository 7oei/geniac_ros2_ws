import subprocess
from geniac_visualizer.exposure import AutoExposure,next_exposure

def test_dark_and_bright_converge_with_limits():
    v=166
    for _ in range(20):v=next_exposure(v,2,50,1000)
    assert v==1000
    for _ in range(20):v=next_exposure(v,220,50,1000)
    assert v==50
    assert next_exposure(200,88,50,1000)==200

def test_failure_restores_hardware_auto():
    calls=[]
    a=AutoExposure('/dev/video0')
    def command(*args):
        calls.extend(args)
        if args==('--list-ctrls-menus',):return 'exposure_time_absolute (int) : min=50 max=10000 value=166\n1: Manual Mode'
        if 'exposure_time_absolute=' in args[0]:raise subprocess.CalledProcessError(1,args)
        return ''
    a.command=command;a.start()
    assert not a.active
    assert calls[-1]=='--set-ctrl=auto_exposure=3'
