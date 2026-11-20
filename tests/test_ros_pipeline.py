"""Opt-in localhost DDS integration: GENIAC_ROS_TESTS=1. Never touches k5/audio/Slack."""
import os
import json
from pathlib import Path
import threading
import time
import pytest

pytestmark=pytest.mark.skipif(os.getenv('GENIAC_ROS_TESTS')!='1',reason='Opt-in ROS localhost integration')


def test_detection_behavior_scenario_and_timeout(tmp_path):
    import numpy as np
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from sensor_msgs.msg import PointCloud2,PointField
    from std_msgs.msg import Header,String
    from std_srvs.srv import Trigger
    from geniac_detector.node import DeerDetector
    from geniac_behavior.node import BehaviorNode
    from geniac_scenario.node import ScenarioNode
    rclpy.init()
    nodes=[];executor=MultiThreadedExecutor(num_threads=4);worker=None
    try:
        detector=DeerDetector();nodes.append(detector)
        behavior=BehaviorNode();nodes.append(behavior)
        scenario=ScenarioNode();nodes.append(scenario)
        probe=Node('geniac_test_probe');nodes.append(probe)
        got={'tracks':None,'state':None,'behavior':None}
        for topic,key in [('/geniac_detector/tracks','tracks'),('/geniac/scenario/state','state'),('/geniac/behavior','behavior')]:
            probe.create_subscription(String,topic,lambda m,k=key:got.update({k:json.loads(m.data)}),10)
        cloud_pub=probe.create_publisher(PointCloud2,'/livox/lidar',1)
        p=np.load(Path(__file__).parents[1]/'src/geniac_detector/test/fixtures/deer_cloud.npz')['points'].astype('<f4')
        fields=[PointField(name=n,offset=i*4,datatype=PointField.FLOAT32,count=1) for i,n in enumerate(['x','y','z','intensity'])]
        def publish():
            cloud_pub.publish(PointCloud2(header=Header(stamp=probe.get_clock().now().to_msg(),frame_id='livox_frame'),
                height=1,width=len(p),fields=fields,is_bigendian=False,point_step=16,row_step=len(p)*16,data=p.tobytes(),is_dense=True))
        timer=probe.create_timer(.1,publish)
        for n in nodes:executor.add_node(n)
        worker=threading.Thread(target=executor.spin,daemon=True);worker.start()
        def until(pred,seconds=8):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                if pred():return
                time.sleep(.05)
            raise AssertionError(str(got))
        until(lambda:got['tracks'] and len(got['tracks']['tracks'])>=2)
        assert got['tracks']['valid']
        topics=[name for name,types in detector.get_subscriptions_info_by_topic('/odom')]
        assert not topics
        start=probe.create_client(Trigger,'/geniac/scenario/start')
        assert start.wait_for_service(timeout_sec=2)
        future=start.call_async(Trigger.Request());until(future.done)
        assert future.result().success
        until(lambda:got['state'] and got['state']['running'])
        until(lambda:got['state']['node']=='search',12)
        assert got['state']['dry_run'] and scenario.player.process is None
        timer.cancel()
        until(lambda:got['state']['reason'] in ('input_stale','input_invalid'),4)
        assert not got['state']['running']
        (tmp_path/'result.json').write_text(json.dumps(got))
    finally:
        executor.shutdown(timeout_sec=3)
        if worker:worker.join(timeout=3)
        for n in reversed(nodes):n.destroy_node()
        if rclpy.ok():rclpy.shutdown()


def test_dashboard_offscreen(tmp_path):
    import rclpy
    from rclpy.node import Node
    from PyQt5 import QtWidgets
    from geniac_visualizer.dashboard import Dashboard
    from geniac_scenario.tree import load_tree
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    rclpy.init();node=Node('geniac_dashboard_smoke');window=None
    try:
        window=Dashboard(node);window.timer.stop()
        tree=load_tree(Path(__file__).parents[1]/'src/geniac_scenario/config/demo_tree.yaml')
        window.model.update('tree',tree)
        window.model.update('scenario',{'node':'warning','running':True,'dry_run':True})
        window.model.update('tracks',{'stream_id':'test','valid':True,'tracks':[{'track_id':1,'center':[12.,2.,1.],'score':.9}]})
        import numpy as np
        rng=np.random.default_rng(42)
        cloud=np.column_stack([rng.uniform(0,40,2000),rng.uniform(-20,20,2000),np.zeros(2000),np.ones(2000)])
        window.model.update('cloud',cloud)
        window.model.update('behavior',{'state':'observing','targets':[
            {'id':'test:2','label':'observing','present':False,'missing_elapsed_seconds':2.5}]})
        window.show();window.tick();app.processEvents()
        assert '退避確認待ち 1頭' in window.status.text()
        assert window.scene.items()
        from PyQt5 import QtCore
        graph_at=window.graph.mapTo(window,QtCore.QPoint(0,0))
        position_at=window.position.mapTo(window,QtCore.QPoint(0,0))
        assert graph_at.x()>position_at.x() and graph_at.y()<position_at.y()
        assert window.grab().save(str(tmp_path/'dashboard.png'))
        artifact=Path(__file__).parents[1]/'artifacts';artifact.mkdir(exist_ok=True)
        window.grab().save(str(artifact/'dashboard-test.png'))
    finally:
        if window:window.close()
        node.destroy_node();rclpy.shutdown()


def test_real_local_bag_start_stop(tmp_path):
    import sqlite3
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from geniac_visualizer.recording import Recorder
    rclpy.init();node=Node('geniac_recording_smoke');recorder=Recorder(tmp_path/'bags')
    try:
        pub=node.create_publisher(String,'/geniac/behavior',10)
        assert recorder.start()[0]
        deadline=time.monotonic()+8
        while pub.get_subscription_count()==0 and time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=.1)
        assert pub.get_subscription_count()>0, recorder.status()
        for _ in range(10):
            pub.publish(String(data='{"version":1,"test":true}'))
            rclpy.spin_once(node,timeout_sec=.05)
        assert recorder.stop()[0]
        assert (recorder.output/'metadata.yaml').is_file()
        db=next(recorder.output.glob('*.db3'))
        with sqlite3.connect(db) as conn:
            count=conn.execute("SELECT count(*) FROM messages m JOIN topics t ON t.id=m.topic_id WHERE t.name='/geniac/behavior'").fetchone()[0]
        assert count>0
    finally:
        if recorder.running():recorder.stop()
        node.destroy_node();rclpy.shutdown()


def test_drag_position_behavior_player_visualizer_end_to_end(tmp_path):
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.executors import SingleThreadedExecutor
    from PyQt5 import QtWidgets
    import yaml
    from geniac_behavior.node import BehaviorNode
    from geniac_scenario.node import ScenarioNode
    from geniac_scenario.integration import SimulatedTracker,IntegrationWindow
    from geniac_scenario.tree import load_tree
    from geniac_scenario.evolving import route_visible_to_attack
    tree=load_tree(Path(__file__).parents[1]/'src/geniac_scenario/config/story_tree.yaml')
    tree['needs']['attack']['event']='attack';tree=route_visible_to_attack(tree)
    import numpy as np
    from scipy.io import wavfile
    wavfile.write(tmp_path/'tone.wav',24000,np.ones(24000,dtype=np.float32)*.1)
    for n in tree['nodes'].values():
        if not n.get('terminal'):n['audio']='tone.wav'
    path=tmp_path/'tree.yaml';path.write_text(yaml.safe_dump(tree))
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    rclpy.init();nodes=[];executor=SingleThreadedExecutor();w=None
    try:
        tracker=SimulatedTracker();nodes.append(tracker)
        behavior=BehaviorNode();nodes.append(behavior)
        scenario=ScenarioNode(parameter_overrides=[Parameter('tree_path',value=str(path)),Parameter('auto_arm',value=False),
            Parameter('dry_run',value=False),Parameter('test_mode',value=True),Parameter('use_stock',value=False),
            Parameter('stock_dir',value=str(tmp_path/'history'))]);nodes.append(scenario)
        calls=[]
        class Playback:
            def __init__(self):self.returncode=None
            def poll(self):return self.returncode
            def terminate(self):self.returncode=0
            def wait(self,timeout):return self.returncode
        def spawn(argv,**kwargs):calls.append(argv);return Playback()
        scenario.player.spawn=spawn
        node=Node('integration_test_dashboard');nodes.append(node)
        for n in nodes:executor.add_node(n)
        w=IntegrationWindow(node,tracker,scenario,executor);w.timer.stop();w.show();app.processEvents()
        def until(predicate,seconds=8):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                w.tick();app.processEvents()
                if predicate():return
                time.sleep(.01)
            raise AssertionError(str((scenario.core.state(),w.model.behavior)))
        w.begin();started=time.monotonic()
        until(lambda:scenario.core.running)
        assert time.monotonic()-started>=1.9
        until(lambda:getattr(w.model,'stock',{}).get('status')=='disabled')
        assert '個別ファイル' in w.stock_panel.summary.text()
        until(lambda:behavior.core.epoch==scenario.core.epoch)
        w.position.positions[1]=[15.,4.]
        until(lambda:w.model.behavior.get('state')=='retreated_nearby')
        until(lambda:scenario.core.node_id=='watch',10)
        assert w.graph.nodes and not w.model.cloud.size and w.camera.image is None
        assert scenario.campaign.mode=='simulation' and len(calls)>=2
        assert all(call[0]=='ffplay' and call[-1]==str(tmp_path/'tone.wav') for call in calls)
        assert scenario.history.context()['field_trials']==0
        w.position.positions[1]=[46.,4.]
        until(lambda:w.model.behavior.get('state')=='observing')
        assert scenario.core.running
        until(lambda:w.model.behavior.get('state')=='escaped',7)
        until(lambda:scenario.core.node_id=='escaped_end')
        assert not scenario.core.running and not scenario.campaign.active
        assert '完全退避' in w.status.text()
        artifact=Path(__file__).parents[1]/'artifacts';artifact.mkdir(exist_ok=True)
        w.grab().save(str(artifact/'integration-drag-test.png'))
        w.position.positions[1]=[15.,0.]
        until(lambda:scenario.core.running,8)
        tracker.valid=False
        until(lambda:scenario.campaign.paused,3)
        assert scenario.core.reason=='input_invalid'
        paused_node=scenario.core.node_id
        tracker.valid=True
        until(lambda:scenario.core.running and not scenario.campaign.paused,8)
        assert scenario.core.node_id==paused_node
        assert float(calls[-1][calls[-1].index('-ss')+1])>0
        scenario.player.process.returncode=1
        until(lambda:scenario.campaign.paused,3)
        assert scenario.core.reason=='audio_playback_error'
        retry_offset=scenario.campaign.pause_elapsed
        until(lambda:scenario.core.running and not scenario.campaign.paused,4)
        assert float(calls[-1][calls[-1].index('-ss')+1])==retry_offset
        w.end()
        assert not scenario.campaign.armed and not scenario.campaign.paused
    finally:
        if w:w.close()
        executor.shutdown()
        for n in reversed(nodes):n.destroy_node()
        if rclpy.ok():rclpy.shutdown()


def test_stock_progress_does_not_validate_on_sensor_executor(tmp_path):
    import json
    import rclpy
    from rclpy.parameter import Parameter
    from geniac_scenario.node import ScenarioNode
    rclpy.init()
    scenario=ScenarioNode(parameter_overrides=[Parameter('stock_dir',value=str(tmp_path)),
        Parameter('auto_arm',value=False),Parameter('dry_run',value=True),Parameter('use_stock',value=False)])
    try:
        class SlowStock:
            def ready(self,*args,**kwargs):
                pytest.fail('Stock validation must never block the sensor executor')
        scenario.stock=SlowStock()
        (tmp_path/'status.json').write_text(json.dumps({'status':'designing','ready_count':2,'target_count':3}))
        for _ in range(5):scenario.publish_stock()
    finally:
        scenario.destroy_node();rclpy.shutdown()


def test_repeat_gap_stops_audio_until_fractional_deadline(tmp_path,monkeypatch):
    import rclpy
    from rclpy.parameter import Parameter
    from geniac_scenario.node import ScenarioNode
    import geniac_scenario.tree as engine_module
    rclpy.init()
    node=ScenarioNode(parameter_overrides=[Parameter('stock_dir',value=str(tmp_path)),Parameter('use_stock',value=False),Parameter('dry_run',value=True)])
    try:
        monkeypatch.setattr(engine_module.random,'uniform',lambda a,b:1.375)
        calls=[]
        monkeypatch.setattr(node.player,'play',lambda *a,**kw:calls.append((a,kw)))
        now=time.monotonic();stamp=node.get_clock().now().nanoseconds/1e9
        node.core.start(now,stamp,['one']);node.core._enter('attack',now-3,stamp-3,'test')
        node.campaign.active=True;node.campaign.cohort={'one'}
        def fresh():
            node.received=time.monotonic()
            node.report={'stamp':node.get_clock().now().nanoseconds/1e9,'epoch':node.core.epoch,'valid':True,
                         'targets':[{'id':'one','present':True,'label':'no_escape'}]}
        fresh();node.tick()
        assert node.core.reason=='repeat_interval' and calls==[]
        fresh();node.tick();assert calls==[]
        node.core.repeat_until=time.monotonic()-.01
        fresh();node.tick()
        assert node.core.reason=='repeat_final_no_escape' and len(calls)==1
    finally:node.destroy_node();rclpy.shutdown()
