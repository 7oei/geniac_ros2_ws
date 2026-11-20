import signal
import json
import socket
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String
from std_srvs.srv import Trigger
from .recording import Recorder

class RecorderNode(Node):
    def __init__(self):
        super().__init__('geniac_recorder')
        self.recorder=Recorder(self.declare_parameter('output_dir',str(Path.home()/'geniac_bags')).value)
        self.pub=self.create_publisher(String,'/geniac/recording/status',10)
        self.create_service(Trigger,'/geniac/recording/start',self.start)
        self.create_service(Trigger,'/geniac/recording/stop',self.stop)
        self.create_timer(.5,self.status)
    def start(self,request,response):
        response.success,response.message=self.recorder.start();return response
    def stop(self,request,response):
        response.success,response.message=self.recorder.stop();return response
    def status(self):
        d=self.recorder.status();d.update(host=socket.gethostname(),stamp=self.get_clock().now().nanoseconds/1e9)
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
