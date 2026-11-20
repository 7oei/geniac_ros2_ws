import signal
import json
import socket
import time
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String
from std_srvs.srv import Trigger
from .recording import Recorder

class RecorderNode(Node):
    def __init__(self,**kwargs):
        super().__init__('geniac_recorder',**kwargs)
        self.recorder=Recorder(self.declare_parameter('output_dir',str(Path.home()/'geniac_bags')).value)
        self.auto_enabled=self.declare_parameter('auto_record',False).value
        self.auto_owned=False;self.auto_seen_running=False;self.last_scenario=None
        self.auto_started=0.;self.pending=False
        self.create_subscription(String,'/geniac/scenario/state',self.scenario,10)
        self.create_service(Trigger,'/geniac/recording/auto_start',self.start_auto)
        self.pub=self.create_publisher(String,'/geniac/recording/status',10)
        self.create_service(Trigger,'/geniac/recording/start',self.start)
        self.create_service(Trigger,'/geniac/recording/stop',self.stop)
        self.create_timer(.5,self.status)
    def start_auto(self,request,response):
        if not self.auto_enabled:
            response.success=False;response.message='Automatic recording disabled';return response
        self.last_scenario=time.monotonic()
        if self.recorder.running():
            response.success=True;response.message='Existing recording continues';return response
        response.success,response.message=self.recorder.start()
        if response.success:response.success,response.message=self.recorder.wait_ready()
        self.auto_owned=response.success;self.auto_seen_running=False
        self.auto_started=time.monotonic();self.pending=True
        return response
    def scenario(self,msg):
        try:data=json.loads(msg.data)
        except ValueError:return
        self.last_scenario=time.monotonic()
        self.pending=data.get('recording_pending',False)
        if self.auto_owned and data.get('running'):self.auto_seen_running=True
        if self.auto_owned and self.auto_seen_running and not data.get('running') and not data.get('paused') and (data.get('reason')=='escaped' or data.get('armed') is False):
            self.recorder.stop();self.auto_owned=False
    def start(self,request,response):
        response.success,response.message=self.recorder.start();return response
    def stop(self,request,response):
        response.success,response.message=self.recorder.stop();self.auto_owned=False;return response
    def status(self):
        if self.auto_owned and not self.auto_seen_running and not self.pending and time.monotonic()-self.auto_started>2:
            self.recorder.stop();self.auto_owned=False
        if self.auto_owned and self.last_scenario is not None and time.monotonic()-self.last_scenario>10:
            self.recorder.stop();self.auto_owned=False
            self.recorder.error='Scenario heartbeat lost; saved interrupted recording'
        d=self.recorder.status();d.update(automatic=self.auto_owned,host=socket.gethostname(),stamp=self.get_clock().now().nanoseconds/1e9)
        self.pub.publish(String(data=json.dumps(d)))
    def destroy_node(self):
        if self.recorder.running():self.recorder.stop()
        return super().destroy_node()

def main(args=None):
    rclpy.init(args=args);node=RecorderNode()
    try:rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
