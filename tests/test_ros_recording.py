"""Real rosbag lifecycle, isolated DDS domain, synthetic camera, no audio/network APIs."""
import os
import json
import time
import threading
from pathlib import Path
import pytest
pytestmark=pytest.mark.skipif(os.getenv('GENIAC_ROS_TESTS')!='1',reason='Opt-in localhost ROS test')


def test_auto_record_camera_until_complete_escape(tmp_path):
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.executors import MultiThreadedExecutor
    from std_msgs.msg import String
    from sensor_msgs.msg import CompressedImage
    from geniac_scenario.node import ScenarioNode
    from geniac_visualizer.recorder_node import RecorderNode
    import yaml
    rclpy.init()
    nodes=[];executor=MultiThreadedExecutor(num_threads=4);thread=None
    try:
        recorder=RecorderNode(parameter_overrides=[Parameter('auto_record',value=True),Parameter('archive_enabled',value=True),Parameter('output_dir',value=str(tmp_path/'bags'))]);nodes.append(recorder)
        scenario=ScenarioNode(parameter_overrides=[Parameter('auto_record',value=True),Parameter('stock_dir',value=str(tmp_path/'stock')),Parameter('use_stock',value=False)]);nodes.append(scenario)
        probe=Node('recording_test_probe');nodes.append(probe)
        behavior=probe.create_publisher(String,'/geniac/behavior',10)
        camera=probe.create_publisher(CompressedImage,'/camera/image_raw/compressed',10)
        escaped=[False]
        def publish():
            stamp=probe.get_clock().now()
            target={'id':'test:1','present':not escaped[0],'label':'escaped' if escaped[0] else 'no_escape','stationary_seconds':3.}
            behavior.publish(String(data=json.dumps({'valid':True,'epoch':scenario.core.epoch,'stamp':stamp.nanoseconds/1e9,'targets':[target]})))
            msg=CompressedImage();msg.header.stamp=stamp.to_msg();msg.format='jpeg';msg.data=b'test-frame';camera.publish(msg)
        probe.create_timer(.1,publish)
        for n in nodes:executor.add_node(n)
        thread=threading.Thread(target=executor.spin,daemon=True);thread.start()
        def until(pred,timeout=15):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if pred():return
                time.sleep(.05)
            raise AssertionError(f'timeout: {scenario.core.state()} {recorder.recorder.status()}')
        until(lambda:scenario.core.running)
        assert recorder.recorder.running() and recorder.auto_owned
        assert scenario.player.process is None
        assert not (recorder.recorder.output/'metadata.yaml').exists()
        time.sleep(1)
        escaped[0]=True
        until(lambda:not recorder.recorder.running())
        until(lambda:(recorder.recorder.output/'metadata.yaml').exists())
        meta=yaml.safe_load((recorder.recorder.output/'metadata.yaml').read_text())['rosbag2_bagfile_information']
        counts={t['topic_metadata']['name']:t['message_count'] for t in meta['topics_with_message_count']}
        assert counts['/camera/image_raw/compressed']>0
        assert counts['/geniac/scenario/state']>0
        assert scenario.core.reason=='escaped'
        until(lambda:bool(recorder.archive_queue.rows()) and recorder.archive_queue.rows()[0]['state']=='queued')
        assert recorder.archive_queue.rows()[0]['outcome']=='escaped'
        from geniac_visualizer.bag_archive import Archiver
        Archiver(tmp_path/'bags','https://example.test',delete_raw=True,probe=lambda *a:True).step()
        assert recorder.archive_queue.rows()[0]['state']=='done'
        assert not recorder.recorder.output.exists()
        print('Recorded topic counts:',counts)
    finally:
        executor.shutdown(timeout_sec=3)
        if thread:thread.join(timeout=3)
        for n in reversed(nodes):n.destroy_node()
        if rclpy.ok():rclpy.shutdown()
