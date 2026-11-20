#!/usr/bin/env python3
"""Offline production-engine replay; writes only recognized cloud/marker frames."""
import argparse,json,time
from pathlib import Path
import rosbag2_py
from rclpy.serialization import deserialize_message,serialize_message
from sensor_msgs.msg import PointCloud2
from tf2_msgs.msg import TFMessage
from ament_index_python.packages import get_package_share_directory
from geniac_detector.engine import Engine,stamp_ns
from geniac_detector.cloud import decode_cloud
from geniac_detector.outputs import make_outputs


def main():
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('output');args=p.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    model=Path(get_package_share_directory('geniac_detector'))/'models/forest_camera_v2.json'
    reports=[]
    for bag in sorted(Path(args.source).iterdir()):
        if not (bag/'metadata.yaml').exists():continue
        reader=rosbag2_py.SequentialReader();reader.open(rosbag2_py.StorageOptions(uri=str(bag),storage_id='mcap'),rosbag2_py.ConverterOptions('',''))
        reader.set_filter(rosbag2_py.StorageFilter(topics=['/livox/lidar']))
        engine=Engine(str(model));writer=None;prev=set();frames=hits=0;start=None;last=None;windows=[];tracks={};times=[]
        log=(out/(bag.name+'.jsonl')).open('w');wall=time.monotonic()
        while reader.has_next():
            topic,data,t=reader.read_next();msg=deserialize_message(data,PointCloud2);stamp=stamp_ns(msg.header.stamp)
            start=t if start is None else start
            now=time.perf_counter();selected,meta=engine.process(decode_cloud(msg,200000),stamp);times.append(time.perf_counter()-now)
            frames+=1
            log.write(json.dumps({'record_ns':t,'stamp_ns':stamp,'tracks':selected,'meta':meta})+'\n')
            if selected:
                hits+=1
                if last is None or t-last>150000000:windows.append({'start_ns':t,'end_ns':t,'frames':0})
                windows[-1]['end_ns']=t;windows[-1]['frames']+=1;last=t
                if writer is None:
                    writer=rosbag2_py.SequentialWriter();writer.open(rosbag2_py.StorageOptions(uri=str(out/(bag.name+'_recognized')),storage_id='mcap'),rosbag2_py.ConverterOptions('',''))
                    for name,typ in [('/livox/lidar','sensor_msgs/msg/PointCloud2'),('/geniac_detector/tracks','std_msgs/msg/String'),('/geniac_detector/markers','visualization_msgs/msg/MarkerArray'),('/tf','tf2_msgs/msg/TFMessage')]:
                        writer.create_topic(rosbag2_py.TopicMetadata(name=name,type=typ,serialization_format='cdr'))
                detection,transforms,markers,prev=make_outputs(msg.header,selected,prev,.3)
                writer.write(topic,data,t)
                for name,obj in [('/geniac_detector/tracks',detection),('/geniac_detector/markers',markers),('/tf',TFMessage(transforms=transforms))]:writer.write(name,serialize_message(obj),t)
                for tr in selected:
                    key=str(tr['track_id']);r=tracks.setdefault(key,{'first_ns':t,'last_ns':t,'frames':0,'max_score':0})
                    r.update(last_ns=t,frames=r['frames']+1,max_score=max(r['max_score'],tr['score']))
            if frames%100==0:print(json.dumps({'bag':bag.name,'frames':frames,'recognized':hits,'wall_s':round(time.monotonic()-wall,1)}),flush=True)
        log.close()
        if writer is not None:del writer
        report={'bag':bag.name,'frames':frames,'recognized_frames':hits,'tracks':tracks,'windows':windows,'start_ns':start,'inference_mean_ms':1000*sum(times)/max(len(times),1),'wall_s':time.monotonic()-wall,'memo':(bag/'memo.txt').read_text() if (bag/'memo.txt').exists() else '', 'model':str(model),'settings':engine.settings.__dict__}
        reports.append(report);(out/'summary.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
        print(json.dumps({'complete':bag.name,'frames':frames,'recognized':hits,'tracks':len(tracks),'windows':len(windows)}),flush=True)
if __name__=='__main__':main()
