"""USB camera publisher: JPEG for transport/bag, optional raw image for consumers."""
import signal
import time
import cv2
from .exposure import AutoExposure
from .frame_sum import FrameSum
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
        self.capture_format=self.declare_parameter('capture_format','MJPG').value
        if self.capture_format not in ('YUYV','MJPG'):raise ValueError('Unsupported capture_format')
        self.fps=fps
        self.frame=self.declare_parameter('frame_id','camera_frame').value
        self.raw=self.declare_parameter('publish_raw',False).value
        adaptive=self.declare_parameter('adaptive_exposure',True).value
        maximum=int(self.declare_parameter('max_exposure_ms',1000).value)
        if maximum<=0:raise ValueError('max_exposure_ms must be positive')
        self.stack_enabled=self.declare_parameter('frame_sum_enabled',True).value
        self.stack=FrameSum(float(self.declare_parameter('frame_sum_target',80.).value),
                            int(self.declare_parameter('frame_sum_max_frames',64).value))
        self.stack_log=0.
        self.exposure=AutoExposure(self.device,maximum*10,self.get_logger().info) if adaptive else None
        if not 0<fps<=60 or not 1<=self.quality<=100 or min(self.width,self.height)<1:raise ValueError('Invalid camera parameters')
        self.pub=self.create_publisher(CompressedImage,'/camera/image_raw/compressed',3)
        self.raw_pub=self.create_publisher(Image,'/camera/image_raw',3) if self.raw else None
        self.capture=None;self.retry=0.;self.create_timer(1/fps,self.tick)
    def tick(self):
        if self.capture is None:
            if time.monotonic()<self.retry:return
            self.capture=cv2.VideoCapture(self.device,cv2.CAP_V4L2)
            self.capture.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*self.capture_format))
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH,self.width);self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT,self.height)
            self.capture.set(cv2.CAP_PROP_FPS,self.fps)
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE,1)
            if self.capture.isOpened() and self.exposure:self.exposure.start()
        ok,image=self.capture.read()
        if not ok:
            if self.exposure:self.exposure.close()
            self.stack.reset()
            self.capture.release();self.capture=None;self.retry=time.monotonic()+2
            self.get_logger().warning('Camera frame unavailable; retrying in 2s');return
        # Exposure feedback always uses the original frame, never the brightened sum.
        at_limit=bool(self.exposure and self.exposure.active and self.exposure.current>=self.exposure.maximum)
        if self.exposure:self.exposure.update(image)
        image=self.stack.apply(image,self.stack_enabled and at_limit)
        if self.stack.frames and time.monotonic()>=self.stack_log:
            self.get_logger().info(f'Frame sum: {len(self.stack.frames)} frames, mean={self.stack.level:.1f}/255, target={self.stack.target:g}')
            self.stack_log=time.monotonic()+30
        stamp=self.get_clock().now().to_msg()
        ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,self.quality])
        if not ok:return
        msg=CompressedImage();msg.header.stamp=stamp;msg.header.frame_id=self.frame;msg.format='jpeg';msg.data=encoded.tobytes();self.pub.publish(msg)
        if self.raw_pub:
            raw=Image();raw.header=msg.header;raw.height,raw.width=image.shape[:2];raw.encoding='bgr8';raw.step=raw.width*3;raw.data=image.tobytes();self.raw_pub.publish(raw)
    def destroy_node(self):
        if self.exposure:self.exposure.close()
        if self.capture is not None:self.capture.release()
        return super().destroy_node()
def main(args=None):
    rclpy.init(args=args);node=CameraNode()
    try:rclpy.spin(node)
    except (KeyboardInterrupt,ExternalShutdownException):pass
    finally:
        signal.signal(signal.SIGINT,signal.SIG_IGN);node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
