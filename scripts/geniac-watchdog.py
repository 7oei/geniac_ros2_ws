#!/usr/bin/env python3
"""k5 unattended recovery. No restart while explicitly stopped by the operator."""
import subprocess
import time
import rclpy
from sensor_msgs.msg import PointCloud2,CompressedImage
from std_msgs.msg import String
from rclpy.qos import qos_profile_sensor_data
from geniac_visualizer.health import Health

rclpy.init();node=rclpy.create_node('geniac_watchdog');health=Health(time.monotonic())
subscriptions=[]
for name,topic,typ in [('lidar','/livox/lidar',PointCloud2),('camera','/camera/image_raw/compressed',CompressedImage),('tracks','/geniac_detector/tracks',String),('behavior','/geniac/behavior',String),('scenario','/geniac/scenario/state',String),('recorder','/geniac/recording/status',String)]:
    subscriptions.append(node.create_subscription(typ,topic,lambda msg,n=name:health.seen(n,time.monotonic()),qos_profile_sensor_data))
try:
    while rclpy.ok():
        rclpy.spin_once(node,timeout_sec=.2)
        missing=health.due(['lidar','camera','tracks','behavior','scenario','recorder'],time.monotonic())
        if not missing:continue
        active=subprocess.run(['systemctl','--user','is-active','--quiet','geniac-sensor.service']).returncode==0
        if not active:continue
        services=['geniac-sensor.service']
        if 'lidar' in missing:services.insert(0,'geniac-hap.service')
        node.get_logger().error('No heartbeat for 30s: '+','.join(missing)+'; restarting '+','.join(services))
        try:subprocess.run(['systemctl','--user','restart',*services],check=True,timeout=90)
        except (subprocess.SubprocessError,OSError) as exc:node.get_logger().error('Restart failed: '+type(exc).__name__)
        # Ignore queued pre-restart packets; allow services time to reconnect.
        health.last.clear();health.started=time.monotonic()
finally:
    node.destroy_node()
    if rclpy.ok():rclpy.shutdown()
