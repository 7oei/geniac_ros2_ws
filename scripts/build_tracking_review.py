#!/usr/bin/env python3
"""Stitch recognized frames for viewing; originals and source timestamps retained separately."""
import json
from pathlib import Path
import sys
import rosbag2_py
from rclpy.serialization import serialize_message,deserialize_message
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import String
from tf2_msgs.msg import TFMessage
from visualization_msgs.msg import Marker,MarkerArray
from geometry_msgs.msg import Point

root=Path(sys.argv[1]);reports=json.loads((root/'summary.json').read_text());dest=root/'review'
writer=rosbag2_py.SequentialWriter();writer.open(rosbag2_py.StorageOptions(uri=str(dest),storage_id='mcap'),rosbag2_py.ConverterOptions('',''))
types={'/livox/lidar':PointCloud2,'/geniac_detector/tracks':String,'/geniac_detector/markers':MarkerArray,'/tf':TFMessage}
names=['sensor_msgs/msg/PointCloud2','std_msgs/msg/String','visualization_msgs/msg/MarkerArray','tf2_msgs/msg/TFMessage']
for (topic,typ),name in zip(types.items(),names):writer.create_topic(rosbag2_py.TopicMetadata(name=topic,type=name,serialization_format='cdr'))
clock=100000000000;mapping=[];frame_id=None;centers=[]
def stamp(s,t):s.sec=int(t//1000000000);s.nanosec=int(t%1000000000)
for report in reports:
    if not report['recognized_frames']:continue
    reader=rosbag2_py.SequentialReader();reader.open(rosbag2_py.StorageOptions(uri=str(root/(report['bag']+'_recognized')),storage_id='mcap'),rosbag2_py.ConverterOptions('',''))
    last=None;paths={};cut=True
    while reader.has_next():
        topic,raw,t=reader.read_next();msg=deserialize_message(raw,types[topic])
        if topic=='/livox/lidar':
            cut=last is None or t-last>150000000
            if cut:paths={}
            clock+=100000000 if cut else t-last;last=t
            frame_id=msg.header.frame_id;stamp(msg.header.stamp,clock)
            mapping.append({'review_ns':clock,'source_bag':report['bag'],'source_record_ns':t,'cut':cut})
        elif topic=='/geniac_detector/tracks':
            payload=json.loads(msg.data);payload['original_stamp']=payload['stamp'];payload['stamp']=clock/1e9;payload['source_bag']=report['bag'];msg.data=json.dumps(payload)
            for tr in payload['tracks']:
                paths.setdefault(tr['track_id'],[]).append(tr['center']);centers.append(tr['center'])
        elif topic=='/tf':
            for tf in msg.transforms:stamp(tf.header.stamp,clock)
        elif topic=='/geniac_detector/markers':
            for marker in msg.markers:stamp(marker.header.stamp,clock)
            if cut:msg.markers.insert(0,Marker(action=Marker.DELETEALL))
            for key,points in paths.items():
                line=Marker(ns='track_trails',id=key,type=Marker.LINE_STRIP,action=Marker.ADD)
                line.header.frame_id=frame_id;stamp(line.header.stamp,clock);line.pose.orientation.w=1.;line.scale.x=.05
                line.color.r=1.;line.color.g=.8;line.color.a=1.;line.lifetime.sec=1
                line.points=[Point(x=float(p[0]),y=float(p[1]),z=float(p[2])) for p in points[-100:]];msg.markers.append(line)
            label=Marker(ns='source_bag',id=0,type=Marker.TEXT_VIEW_FACING,action=Marker.ADD)
            label.header.frame_id=frame_id;stamp(label.header.stamp,clock);label.pose.orientation.w=1.;label.pose.position.x=5.;label.pose.position.z=3.;label.scale.z=.45
            label.color.r=label.color.g=label.color.b=label.color.a=1.;label.text=report['bag']+'\nDEER CANDIDATES (unverified)';msg.markers.append(label)
        writer.write(topic,serialize_message(msg),clock)
del writer
(root/'review_mapping.json').write_text(json.dumps(mapping,indent=2))
import yaml,numpy as np
config=yaml.safe_load(Path('/home/air-water/geniac_ros2_ws/src/geniac_visualizer/config/geniac.rviz').read_text())
vm=config['Visualization Manager'];vm['Global Options']['Fixed Frame']=frame_id
view=vm['Views']['Current'];view['Target Frame']=frame_id
if centers:
 center=np.median(centers,axis=0);view.update(Distance=30.,Yaw=3.14,Pitch=.85);view['Focal Point']={k:float(v) for k,v in zip(('X','Y','Z'),center)}
vm['Displays'][0]['Color Transformer']='AxisColor';vm['Displays'][0]['Decay Time']=.15
(root/'tracking_review.rviz').write_text(yaml.safe_dump(config,sort_keys=False))
print(json.dumps({'frames':len(mapping),'duration_s':(clock-100000000000)/1e9,'fixed_frame':frame_id,'review':str(dest)}))
