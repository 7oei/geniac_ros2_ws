"""Full PointCloud2 bag -> production detector -> behavior -> audio/dashboard test."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from PyQt5 import QtCore,QtWidgets
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.executors import SingleThreadedExecutor
from rosbag2_interfaces.srv import Pause,Resume
from std_msgs.msg import String
from ament_index_python.packages import get_package_share_directory
from geniac_behavior.node import BehaviorNode
from geniac_scenario.node import ScenarioNode
from geniac_scenario.stock import DEFAULT_STOCK
from geniac_visualizer.dashboard import Dashboard


def playback_command(bag,qos):
    # Replay only sensor data, never recorded robot commands or old classifications.
    return ['ros2','bag','play',str(bag),'--clock','30','--rate','1.0',
            '--qos-profile-overrides-path',str(qos),'--topics','/livox/lidar']


class Journal:
    def __init__(self,path):
        self.path=Path(path);self.path.mkdir(parents=True,exist_ok=True)
        self.file=(self.path/'events.jsonl').open('a');self.counts=Counter();self.starts=set();self.last={}
    def record(self,kind,data):
        self.counts[kind]+=1
        if kind=='tracks' and data.get('tracks'):self.counts['frames_with_tracks']+=1
        if kind=='behavior':self.counts['behavior_'+data.get('state','unknown')]+=1
        if kind=='scenario' and data.get('running'):
            for transition in data.get('transitions',[]):
                if transition.get('reason')=='start':self.starts.add((data.get('story',{}).get('id'),transition['stamp']))
        self.file.write(json.dumps({'wall_time':time.time(),'kind':kind,'data':data},ensure_ascii=False)+'\n')
    def summary(self):
        data={'message_counts':dict(self.counts),'scenario_starts':len(self.starts),
              'note':'bag_test mode; excluded from live/provisional best scores. No forced stationary detections.'}
        self.file.flush();(self.path/'summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2));return data
    def close(self):self.summary();self.file.close()


class BagWindow(Dashboard):
    def __init__(self,node,scenario,executor,bag,output):
        def spin():
            deadline=time.monotonic()+.008
            for _ in range(40):
                executor.spin_once(timeout_sec=0)
                if time.monotonic()>deadline:break
        super().__init__(node,interactive=False,spin=spin)
        self.setWindowTitle('GENIAC — 元rosbagからの統合テスト（等速）')
        self.scenario_node=scenario;self.bag=Path(bag);self.output=Path(output);self.process=None;self.bag_log=None;self.paused=False
        self.journal=Journal(output)
        # Replace live-PC recording controls with bag controls.
        while self.toolbar.count():
            item=self.toolbar.takeAt(0)
            if item.widget():item.widget().deleteLater()
        for title,fn in [('▶ 先頭から開始',self.begin),('一時停止',self.pause),('再開',self.resume),('■ 停止',self.end)]:
            button=QtWidgets.QPushButton(title);button.clicked.connect(fn);self.toolbar.addWidget(button)
        self.sound=QtWidgets.QCheckBox('音声を再生');self.sound.setChecked(not scenario.dry_run)
        self.sound.toggled.connect(self.set_audio);self.toolbar.addWidget(self.sound)
        self.progress_label=QtWidgets.QLabel('元bag・等速／停止2秒、未検出5秒／手動の鹿入力なし')
        self.toolbar.addWidget(self.progress_label)
        self.pause_client=node.create_client(Pause,'/rosbag2_player/pause');self.resume_client=node.create_client(Resume,'/rosbag2_player/resume')
        self.qos=self.output/'bag_qos.yaml';self.qos.write_text('/livox/lidar:\n  reliability: reliable\n  durability: volatile\n  history: keep_last\n  depth: 5\n')
        self.monitor=QtCore.QTimer(self);self.monitor.timeout.connect(self.poll);self.monitor.start(1000)
        self.result.setText('元bagの入力から自動判定します。検出が2秒安定しなければシナリオは開始しません。')
    def packet(self,kind,msg):
        super().packet(kind,msg)
        if hasattr(self,'journal') and kind in ('tracks','behavior','scenario','tree'):
            try:
                data=json.loads(msg.data)
                if kind=='scenario':
                    data={k:v for k,v in data.items() if k not in ('story','evaluation')}
                    data['story']={k:self.model.scenario.get('story',{}).get(k) for k in ('id','sequence','title')}
                self.journal.record(kind,data)
            except (ValueError,TypeError):pass
    def set_audio(self,enabled):
        self.scenario_node.dry_run=not enabled;self.scenario_node.player.dry_run=not enabled
        if not enabled:self.scenario_node.player.stop()
    def begin(self):
        self.end()
        self.journal.record('control',{'action':'start','bag':str(self.bag)})
        self.bag_log=(self.output/'bag_player.log').open('a')
        self.process=subprocess.Popen(playback_command(self.bag,self.qos),stdout=self.bag_log,stderr=subprocess.STDOUT,start_new_session=True)
        self.scenario_node.campaign.armed=True;self.paused=False
        self.progress_label.setText('元bagを等速再生中／行動から自動分岐')
    def pause(self):
        if not self.process or not self.pause_client.service_is_ready():return
        future=self.pause_client.call_async(Pause.Request())
        def done(f):
            try:f.result()
            except Exception:return
            self.scenario_node.campaign.pause('bag_paused',time.monotonic());self.scenario_node.campaign.armed=False
            self.scenario_node.player.stop();self.paused=True
            self.journal.record('control',{'action':'pause'})
        future.add_done_callback(done)
    def resume(self):
        if not self.process or not self.resume_client.service_is_ready():return
        future=self.resume_client.call_async(Resume.Request())
        def done(f):
            try:f.result()
            except Exception:return
            self.scenario_node.campaign.armed=True;self.paused=False;self.journal.record('control',{'action':'resume'})
        future.add_done_callback(done)
    def end(self):
        self.scenario_node.campaign.stop('bag_test_stop');self.scenario_node.player.stop()
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid,signal.SIGINT)
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:os.killpg(self.process.pid,signal.SIGTERM);self.process.wait(timeout=2)
        self.process=None
        if self.bag_log:self.bag_log.close();self.bag_log=None
        self.paused=False;self.journal.summary()
    def poll(self):
        if self.process and self.process.poll() is not None:
            code=self.process.returncode;self.journal.record('control',{'action':'bag_end','returncode':code});self.end()
            self.progress_label.setText('bag終了：結果を保存しました。先頭から再実行できます。')
        data=self.journal.summary()
        if self.process:self.progress_label.setText(('一時停止' if self.paused else '等速再生中')+f" ／検出あり {data['message_counts'].get('frames_with_tracks',0)}回 ／シナリオ開始 {data['scenario_starts']}回")
    def open_rviz(self):
        if self.rviz and self.rviz.poll() is None:return
        cfg=Path(get_package_share_directory('geniac_visualizer'))/'config/geniac.rviz'
        self.rviz=subprocess.Popen(['rviz2','-d',str(cfg),'--ros-args','-p','use_sim_time:=true'])
    def closeEvent(self,event):
        self.monitor.stop();self.end();self.journal.close();super().closeEvent(event)


def main(args=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('bag');p.add_argument('--stock-dir',default=str(DEFAULT_STOCK));p.add_argument('--domain-id',type=int,default=175)
    p.add_argument('--output',default=str(Path.home()/'geniac_ros2_ws/artifacts/bag_integration'/datetime.now().strftime('%Y%m%d_%H%M%S')))
    p.add_argument('--mute',action='store_true');p.add_argument('--autostart',action='store_true');opt=p.parse_args(args)
    if not (Path(opt.bag)/'metadata.yaml').is_file():p.error('bag directory with metadata.yaml required')
    if not 0<=opt.domain_id<=232:p.error('invalid domain')
    os.environ.update(ROS_DOMAIN_ID=str(opt.domain_id),ROS_LOCALHOST_ONLY='1',RMW_IMPLEMENTATION='rmw_cyclonedds_cpp')
    output=Path(opt.output);output.mkdir(parents=True,exist_ok=True)
    rclpy.init(args=[]);app=QtWidgets.QApplication(sys.argv[:1]);executor=SingleThreadedExecutor();nodes=[];detector=None
    signal.signal(signal.SIGTERM,lambda *_:app.quit());signal.signal(signal.SIGINT,lambda *_:app.quit())
    log=(output/'detector.log').open('a')
    try:
        cfg=Path(get_package_share_directory('geniac_detector'))/'config/detector.yaml'
        detector=subprocess.Popen(['ros2','run','geniac_detector','detector','--ros-args','--params-file',str(cfg),'-p','use_sim_time:=true'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        sim=[Parameter('use_sim_time',value=True)]
        behavior=BehaviorNode(parameter_overrides=sim);nodes.append(behavior)
        scenario=ScenarioNode(parameter_overrides=sim+[Parameter('test_mode',value=True),Parameter('auto_arm',value=False),Parameter('dry_run',value=opt.mute),Parameter('stock_dir',value=opt.stock_dir),Parameter('use_stock',value=True)]);nodes.append(scenario)
        scenario.campaign.mode='bag_test'
        # Save outcomes for this run too; History excludes bag_test from learning scores.
        original_sink=scenario.campaign.sink
        def outcome(result):
            original_sink(result)
            with (output/'outcomes.jsonl').open('a') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
        scenario.campaign.sink=outcome
        node=Node('geniac_bag_dashboard',parameter_overrides=sim);nodes.append(node)
        for n in nodes:executor.add_node(n)
        window=BagWindow(node,scenario,executor,opt.bag,output);window.show()
        if opt.autostart:QtCore.QTimer.singleShot(2000,window.begin)
        app.exec_()
    finally:
        if 'window' in locals() and not window.journal.file.closed:window.close()
        if detector and detector.poll() is None:
            os.killpg(detector.pid,signal.SIGINT)
            try:detector.wait(timeout=3)
            except subprocess.TimeoutExpired:os.killpg(detector.pid,signal.SIGTERM)
        log.close();executor.shutdown()
        for node in reversed(nodes):node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
if __name__=='__main__':main()
