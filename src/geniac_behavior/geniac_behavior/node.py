import signal
import json
import time
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.clock import Clock, ClockType
from std_msgs.msg import String
from .core import Classifier, Settings

class BehaviorNode(Node):
    def __init__(self,**kwargs):
        super().__init__('geniac_behavior',**kwargs)
        self.core = Classifier(Settings(**{k:self.declare_parameter(k,v).value for k,v in Settings().__dict__.items()}))
        self.publisher = self.create_publisher(String, '/geniac/behavior', 10)
        self.last_received = None
        self.create_subscription(String, '/geniac_detector/tracks', self.tracks, 1)
        self.create_subscription(String, '/geniac/scenario/state', self.scenario, 10)
        self.create_timer(.2, self.publish, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def tracks(self,msg):
        try:
            self.core.update(json.loads(msg.data)); self.last_received=time.monotonic()
        except (ValueError,KeyError,TypeError):
            self.core.valid=False
            self.get_logger().warning('Rejected malformed track packet')

    def scenario(self,msg):
        try:
            d=json.loads(msg.data)
            if d.get('running') or d.get('paused'):
                self.core.begin(d['epoch'],float(d['entered_stamp']))
        except (ValueError,KeyError,TypeError):
            self.get_logger().warning('Rejected malformed scenario state')

    def publish(self):
        if self.last_received is None or time.monotonic()-self.last_received>self.core.settings.stale_seconds:
            self.core.valid=False
        d=self.core.report(self.get_clock().now().nanoseconds/1e9)
        self.publisher.publish(String(data=json.dumps(d,allow_nan=False)))


def main(args=None):
    rclpy.init(args=args); node=BehaviorNode()
    try:rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
