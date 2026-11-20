"""USB camera publisher: JPEG for transport/bag, optional raw image for consumers."""
import signal
import time
import cv2
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import CompressedImage,Image

class CameraNode(Node):
    def __init__(self,**kwargs):
        super().__init__('geniac_camera',**kwargs)
        self.device=self.declare_parameter('device','/dev/video0').value
        self.width=self.declare_parameter('width',1280).value;self.height=self.declare_parameter('height',720).value
        fps=float(self.declare_parameter('fps',10.).value)
        self.quality=self.declare_parameter('jpeg_quality',80).value
        self.frame=self.declare_parameter('frame_id','camera_frame').value
        self.raw=self.declare_parameter('publish_raw',False).value
        if not 0<fps<=60 or not 1<=self.quality<=100 or min(self.width,self.height)<1:raise ValueError('Invalid camera parameters')
        self.pub=self.create_publisher(CompressedImage,'/camera/image_raw/compressed',3)
        self.raw_pub=self.create_publisher(Image,'/camera/image_raw',3) if self.raw else None
        self.capture=None;self.retry=0.;self.create_timer(1/fps,self.tick)
    def tick(self):
        if self.capture is None:
            if time.monotonic()<self.retry:return
            self.capture=cv2.VideoCapture(self.device,cv2.CAP_V4L2)
            self.capture.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH,self.width);self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT,self.height)
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE,1)
        ok,image=self.capture.read()
        if not ok:
            self.capture.release();self.capture=None;self.retry=time.monotonic()+2
            self.get_logger().warning('Camera frame unavailable; retrying in 2s');return
        stamp=self.get_clock().now().to_msg()
        ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,self.quality])
        if not ok:return
        msg=CompressedImage();msg.header.stamp=stamp;msg.header.frame_id=self.frame;msg.format='jpeg';msg.data=encoded.tobytes();self.pub.publish(msg)
        if self.raw_pub:
            raw=Image();raw.header=msg.header;raw.height,raw.width=image.shape[:2];raw.encoding='bgr8';raw.step=raw.width*3;raw.data=image.tobytes();self.raw_pub.publish(raw)
    def destroy_node(self):
        if self.capture is not None:self.capture.release()
        return super().destroy_node()
def main(args=None):
    rclpy.init(args=args);node=CameraNode()
    try:rclpy.spin(node)
    except (KeyboardInterrupt,ExternalShutdownException):pass
    finally:
        signal.signal(signal.SIGINT,signal.SIG_IGN);node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
