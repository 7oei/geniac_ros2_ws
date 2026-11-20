"""Bound Wi-Fi display traffic; detection and recording retain the original cloud."""
import math
import signal
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile,ReliabilityPolicy
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import PointCloud2


def decimate(msg,max_points=5000):
    if max_points<1 or msg.point_step<1 or msg.row_step<msg.width*msg.point_step or len(msg.data)<msg.height*msg.row_step:
        raise ValueError('Invalid cloud dimensions')
    points=np.ndarray((msg.height,msg.width),dtype=f'V{msg.point_step}',buffer=msg.data,
                      strides=(msg.row_step,msg.point_step)).reshape(-1)
    data=points[::max(1,math.ceil(len(points)/max_points))].tobytes()
    return PointCloud2(header=msg.header,height=1,width=len(data)//msg.point_step,
                      fields=msg.fields,is_bigendian=msg.is_bigendian,point_step=msg.point_step,
                      row_step=len(data),data=data,is_dense=msg.is_dense)


class CloudPreview(Node):
    def __init__(self):
        super().__init__('geniac_cloud_preview')
        self.limit=self.declare_parameter('max_points',5000).value
        rate=float(self.declare_parameter('rate_hz',5.).value)
        if self.limit<1 or not 0<rate<=30:raise ValueError('Invalid preview settings')
        qos=QoSProfile(depth=1,reliability=ReliabilityPolicy.BEST_EFFORT)
        self.pub=self.create_publisher(PointCloud2,'/geniac/visualization/cloud',qos)
        self.latest=None
        self.create_subscription(PointCloud2,'/livox/lidar',self.receive,qos)
        self.create_timer(1/rate,self.tick)
    def receive(self,msg):self.latest=msg
    def tick(self):
        msg=self.latest;self.latest=None
        if msg is None:return
        try:self.pub.publish(decimate(msg,self.limit))
        except ValueError:self.get_logger().warning('Invalid cloud skipped in preview')


def main(args=None):
    rclpy.init(args=args);node=CloudPreview()
    try:rclpy.spin(node)
    except (KeyboardInterrupt,ExternalShutdownException):pass
    finally:
        signal.signal(signal.SIGINT,signal.SIG_IGN);node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
