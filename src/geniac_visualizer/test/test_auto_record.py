import json
from types import SimpleNamespace as NS
from pathlib import Path
from geniac_visualizer.recorder_node import RecorderNode
from geniac_visualizer.recording import Recorder, TOPICS
from geniac_scenario.node import ScenarioNode


def test_audio_waits_for_recording_ack_and_retries():
    tree={'root':'arrival'}
    future=NS(done=lambda:False)
    request=[]
    client=NS(service_is_ready=lambda:True,call_async=lambda r:request.append(r) or future)
    n=NS(auto_record=True,prepared_tree=tree,record_retry_at=0,record_future=None,record_client=client)
    assert ScenarioNode.prepare_episode(n) is None
    assert ScenarioNode.prepare_episode(n) is None
    assert len(request)==1
    future.done=lambda:True
    future.result=lambda:NS(success=True)
    assert ScenarioNode.prepare_episode(n) is tree
    assert n.prepared_tree is None


def test_automatic_bag_survives_pause_and_stops_after_escape():
    stopped=[]
    n=NS(auto_owned=True,auto_seen_running=False,last_scenario=None,pending=True,
         recorder=NS(stop=lambda:stopped.append(True)))
    def state(**d):RecorderNode.scenario(n,NS(data=json.dumps(d)))
    state(running=False,reason='escaped',armed=True)  # queued previous episode
    assert not stopped
    state(running=True,armed=True)
    state(running=False,paused=True,reason='input_stale',armed=True)
    assert not stopped
    state(running=False,paused=False,reason='escaped',armed=True)
    assert stopped==[True] and not n.auto_owned
    n.auto_owned=False
    state(running=False,reason='escaped')
    assert len(stopped)==1  # manual recordings are not stopped


def test_ready_requires_rosbag_ack_and_records_camera(tmp_path):
    assert '/camera/image_raw/compressed' in TOPICS
    class Process:
        pid=123
        code=None
        def poll(self):return self.code
        def wait(self,timeout):self.code=0
    process=Process()
    r=Recorder(tmp_path,lambda *a,**k:process,lambda *a:None)
    assert r.start()[0]
    Path(r.log.name).write_text('[INFO] Recording...\n')
    assert r.wait_ready(timeout=1)[0]
    assert r.stop()[0]
    assert r.start()[0]
    assert not r.wait_ready(timeout=.01)[0]
    assert not r.running()


def test_dashboard_drains_multiple_callbacks_without_blocking(monkeypatch):
    from geniac_visualizer.dashboard import Dashboard
    calls=[]
    monkeypatch.setattr('geniac_visualizer.dashboard.rclpy.spin_once',lambda node,timeout_sec:calls.append(timeout_sec))
    Dashboard.drain_ros(NS(node=object()))
    assert 1<len(calls)<=64
    assert set(calls)=={0}
