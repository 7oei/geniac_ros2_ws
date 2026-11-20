import signal
"""Bounded-latency ROS adapter: latest-only input, acquisition-stamped dynamic TF."""
import json
import uuid
import math
from pathlib import Path
import time

import rclpy
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor, ExternalShutdownException
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from rcl_interfaces.msg import ParameterDescriptor
from ament_index_python.packages import get_package_share_directory
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Header, String
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from visualization_msgs.msg import MarkerArray
from tf2_ros import TransformBroadcaster

from .cloud import decode_cloud
from .engine import Engine, Settings, LatestCloud, stamp_ns, timestamp_error
from .outputs import make_outputs


class DeerDetector(Node):
    def __init__(self, **kwargs):
        super().__init__('geniac_detector', **kwargs)
        def param(name, default):
            return self.declare_parameter(name, default, ParameterDescriptor(read_only=True)).value
        self.input_topic = param('input_topic', '/livox/lidar')
        self.expected_frame = param('expected_frame', 'livox_frame')
        self.rate = float(param('processing_rate_hz', 10.0))
        self.max_age = float(param('max_cloud_age_s', .35))
        self.max_future = float(param('max_future_stamp_s', .05))
        self.timeout = float(param('input_timeout_s', .5))
        self.max_points = int(param('max_points', 200000))
        self.publish_markers = bool(param('publish_markers', True))
        model_path = param('model_path', '')
        settings = Settings(**{k: param(k, v) for k, v in Settings().__dict__.items()})
        if not all(math.isfinite(v) for v in (self.rate, self.max_age, self.max_future, self.timeout)):
            raise ValueError('Timing parameters must be finite')
        if not 0 < self.rate <= 100 or not 0 < self.max_age <= 10 or not 0 <= self.max_future <= 1 or not 0 < self.timeout <= 10 or self.max_points < 1:
            raise ValueError('Invalid rate, timeout, cloud age, future tolerance, or max_points')
        if not model_path:
            model_path = str(Path(get_package_share_directory('geniac_detector')) / 'models/forest_camera_v2.json')
        self.engine = Engine(model_path, settings)
        self.stream_id = uuid.uuid4().hex
        self.engine_epoch = -1
        self.mailbox = LatestCloud()
        self.marker_ids = set()
        self.last_frame = self.expected_frame or 'livox_frame'
        self.last_output_wall = None
        self.active_count = 0
        self.timed_out = False
        self.last_status = 'waiting_for_cloud'
        self.processed = self.rejected = self.expired = 0
        self.reject_reasons = {}
        self.last_ms = self.last_quality = 0.0
        self.io_group = MutuallyExclusiveCallbackGroup()
        self.work_group = MutuallyExclusiveCallbackGroup()
        self.steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        input_qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                               reliability=ReliabilityPolicy.RELIABLE,
                               durability=DurabilityPolicy.VOLATILE)
        self.subscription = self.create_subscription(PointCloud2, self.input_topic, self.receive,
                                                     input_qos, callback_group=self.io_group)
        self.detections_pub = self.create_publisher(String, '~/tracks', 1)
        self.markers_pub = self.create_publisher(MarkerArray, '~/markers', 1)
        self.diagnostic_pub = self.create_publisher(DiagnosticArray, '~/diagnostics', 1)
        self.broadcaster = TransformBroadcaster(self)
        self.timer = self.create_timer(1.0 / self.rate, self.process_latest,
                                      callback_group=self.work_group, clock=self.steady_clock)
        self.watchdog = self.create_timer(.1, self.check_timeout,
                                         callback_group=self.io_group, clock=self.steady_clock)
        self.diagnostic_timer = self.create_timer(1.0, self.publish_diagnostics,
                                                  callback_group=self.io_group, clock=self.steady_clock)
        self.get_logger().info('LiDAR-only deer candidate detector ready: ' + self.input_topic
                               + '; TF prefix=' + settings.tf_prefix + '; model=' + model_path)

    def receive(self, msg):
        self.mailbox.put(msg, time.monotonic())
        with self.mailbox.lock:
            self.timed_out = False

    def emit_locked(self, header, tracks):
        detections, transforms, markers, self.marker_ids = make_outputs(
            header, tracks, self.marker_ids, self.timeout)
        payload = json.loads(detections.data)
        payload['stream_id'] = self.stream_id
        payload['valid'] = self.last_status in ('ok', 'low_ground_quality') and not self.timed_out
        detections.data = json.dumps(payload, allow_nan=False)
        self.detections_pub.publish(detections)
        if transforms:
            self.broadcaster.sendTransform(transforms)
        if self.publish_markers:
            self.markers_pub.publish(markers)
        self.active_count = len(tracks)
        self.last_output_wall = time.monotonic()

    def empty_header(self):
        return Header(stamp=self.get_clock().now().to_msg(), frame_id=self.last_frame)

    def reject(self, reason, epoch):
        with self.mailbox.lock:
            self.rejected += 1
            self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1
            self.last_status = reason
            if self.mailbox.epoch == epoch:
                self.mailbox.invalidate_locked()
                self.emit_locked(self.empty_header(), [])

    def process_latest(self):
        item = self.mailbox.take()
        if item is None:
            return
        msg, received, epoch = item
        stamp = stamp_ns(msg.header.stamp)
        frame = msg.header.frame_id
        error = timestamp_error(stamp, self.get_clock().now().nanoseconds, self.max_age, self.max_future)
        if not frame or frame.startswith('/') or (self.expected_frame and frame != self.expected_frame):
            error = 'unexpected_cloud_frame'
        if error:
            self.reject(error, epoch); return
        if epoch != self.engine_epoch:
            self.engine.reset(); self.engine_epoch = epoch
        start = time.perf_counter()
        try:
            points = decode_cloud(msg, self.max_points)
            tracks, meta = self.engine.process(points, stamp)
            if any(t['child_frame_id'] == frame for t in tracks):
                raise ValueError('TF child frame must differ from its parent')
        except (ValueError, TypeError, IndexError, RuntimeError) as exc:
            self.reject('invalid_cloud_or_inference: ' + str(exc), epoch); return
        ms = (time.perf_counter() - start) * 1000.0
        with self.mailbox.lock:
            error = timestamp_error(stamp, self.get_clock().now().nanoseconds, self.max_age, self.max_future)
            if epoch != self.mailbox.epoch:
                self.expired += 1; return
            if error or time.monotonic() - received > self.max_age:
                self.expired += 1
                self.last_status = error or 'processing_exceeded_age_limit'
                self.mailbox.invalidate_locked()
                self.emit_locked(self.empty_header(), []); return
            self.last_frame = frame
            self.last_ms, self.last_quality = ms, meta['ground_quality']
            self.last_status = 'ok' if self.last_quality >= self.engine.settings.min_ground_quality else 'low_ground_quality'
            self.processed += 1
            # Stamp is always copied from source; never refreshed to make an old TF look current.
            self.emit_locked(msg.header, tracks)

    def check_timeout(self):
        with self.mailbox.lock:
            last = self.mailbox.last_received
            if last is not None and time.monotonic() - last > self.timeout and not self.timed_out:
                self.mailbox.invalidate_locked()
                self.timed_out = True
                self.last_status = 'input_timeout'
                self.emit_locked(self.empty_header(), [])

    def publish_diagnostics(self):
        with self.mailbox.lock:
            status = DiagnosticStatus()
            status.name = self.get_fully_qualified_name() + '/detector'
            status.hardware_id = 'cpu_lidar'
            status.level = DiagnosticStatus.OK if self.last_status == 'ok' else DiagnosticStatus.WARN
            status.message = self.last_status
            values = dict(processed=self.processed, rejected=self.rejected,
                          expired=self.expired, replaced_pending=self.mailbox.replaced,
                          processing_ms=round(self.last_ms, 3), ground_quality=round(self.last_quality, 3),
                          active_targets=self.active_count,
                          reject_reasons=str(self.reject_reasons),
                          input_age_s=round(time.monotonic() - self.mailbox.last_received, 3)
                          if self.mailbox.last_received is not None else -1)
            status.values = [KeyValue(key=str(k), value=str(v)) for k, v in values.items()]
            d = DiagnosticArray(); d.header.stamp = self.get_clock().now().to_msg(); d.status = [status]
            self.diagnostic_pub.publish(d)


def main(args=None):
    rclpy.init(args=args)
    node = None
    executor = MultiThreadedExecutor(num_threads=2)
    try:
        node = DeerDetector()
        executor.add_node(node)
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
