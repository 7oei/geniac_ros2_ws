#!/usr/bin/env python3
"""Read-only D435 color/depth check on the k5 loopback ROS domain."""
import json
import time
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image,CameraInfo

rclpy.init();node=Node('geniac_d435_check');samples={};summary={};subscriptions=[]
def receive(name,msg):
    samples.setdefault(name,[]).append(time.monotonic())
    if isinstance(msg,Image):
        d=dict(width=msg.width,height=msg.height,encoding=msg.encoding,bytes=len(msg.data))
        if msg.encoding=='16UC1':
            values=np.frombuffer(msg.data,dtype='>u2' if msg.is_bigendian else '<u2')
            d['nonzero_depth_fraction']=round(float(np.count_nonzero(values)/values.size),3)
        summary[name]=d
for name,topic,typ in [('color','/d435/camera/color/image_raw',Image),('depth','/d435/camera/depth/image_rect_raw',Image),('color_info','/d435/camera/color/camera_info',CameraInfo),('depth_info','/d435/camera/depth/camera_info',CameraInfo)]:
    subscriptions.append(node.create_subscription(typ,topic,lambda m,n=name:receive(n,m),qos_profile_sensor_data))
end=time.monotonic()+12
try:
    while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.2)
    for name,stamps in samples.items():
        summary.setdefault(name,{}).update(frames=len(stamps),fps=round((len(stamps)-1)/(stamps[-1]-stamps[0]),2) if len(stamps)>1 else 0)
    print(json.dumps(summary,indent=2))
    assert all(len(samples.get(n,[]))>=2 for n in ('color','depth','color_info','depth_info')), 'Missing image/calibration stream'
finally:
    node.destroy_node();rclpy.shutdown()
