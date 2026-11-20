import signal
import numpy as np
from geniac_visualizer.recording import Recorder,TOPICS
from geniac_visualizer.notifications import EntryGate,send
from geniac_visualizer.view_model import ViewModel,tree_layers

class Process:
    pid=123
    def __init__(self):self.code=None
    def poll(self):return self.code
    def wait(self,timeout):self.code=0;return 0

def test_recorder_argv_and_owned_stop(tmp_path):
    calls=[];signals=[];process=Process()
    def spawn(argv,**kw):calls.append((argv,kw));return process
    r=Recorder(tmp_path/'bag directory',spawn,lambda pid,sig:signals.append((pid,sig)))
    assert r.start()[0] and r.running()
    assert not r.start()[0] and len(calls)==1
    argv,kw=calls[0];assert argv[:3]==['ros2','bag','record'] and kw['start_new_session']
    assert set(TOPICS).issubset(argv) and '--all' not in argv
    assert r.stop()[0] and signals==[(123,signal.SIGINT)] and not r.running()
    assert not r.stop()[0]

def test_recorder_spawn_failure(tmp_path):
    def fail(*a,**k):raise FileNotFoundError()
    r=Recorder(tmp_path,fail);assert not r.start()[0] and not r.running()

def test_notification_entry_and_cooldown_no_network():
    g=EntryGate(cooldown=60,absence=5)
    assert g.update([1],0)
    assert not g.update([2],1) # ID churn is not a fresh entry.
    assert not g.update([],10)
    assert not g.update([3],11)
    assert g.update([4],72)
    assert not g.update([5],80,valid=False)
    calls=[]
    class R:status_code=200
    assert send('https://discord.com/api/webhooks/123/test-token','test',lambda *a,**k:(calls.append((a,k)) or R()))
    assert len(calls)==1
    assert calls[0][1]['json']=={'content':'test','allowed_mentions':{'parse':[]}}
    assert calls[0][1]['params']=={'wait':'true'}

def test_view_expiry_restart_and_layers():
    m=ViewModel();p={'stream_id':'a','valid':True,'tracks':[{'track_id':1,'center':[10,0,1]}]}
    m.update('tracks',p,0);m.update('cloud',np.ones((3,4)),0)
    assert len(m.paths['1'])==1
    m.expire(3);assert not m.tracks and not len(m.cloud)
    p['stream_id']='b';m.update('tracks',p,4);assert len(m.paths['1'])==1
    layers=tree_layers({'root':'a','nodes':{'a':{'branches':{'x':'b'}},'b':{'terminal':True}}})
    assert layers=={0:['a'],1:['b']}

def test_recording_abnormal_shutdown_is_reported(tmp_path):
    class Failed(Process):
        def wait(self,timeout):self.code=1;return 1
    r=Recorder(tmp_path,lambda *a,**k:Failed(),lambda *a:None)
    assert r.start()[0]
    assert not r.stop()[0]
    assert r.status()['error']
