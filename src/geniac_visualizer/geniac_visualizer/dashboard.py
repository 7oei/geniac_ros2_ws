"""Mother-PC desktop dashboard. ROS services execute recording on the sensor host."""
import json
from collections import deque
import signal
import math
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2, Image, CompressedImage
from std_msgs.msg import String
from std_srvs.srv import Trigger
from ament_index_python.packages import get_package_share_directory
from geniac_detector.cloud import decode_cloud
from .view_model import ViewModel, tree_layers
from .position_view import PositionView,NAMES
from .stock_panel import StockPanel
from .story_graph import StoryGraph
from .screen_video import ScreenCapture,VideoWriter
from .microphone import MicrophoneMonitor,TOPIC as MICROPHONE_TOPIC

class CloudView(QtWidgets.QWidget):
    def __init__(self,model):
        super().__init__();self.model=model;self.setMinimumSize(480,360)
        self.frames=deque(maxlen=10)

    def add_frame(self,points):
        now=time.monotonic()
        self.frames.append((now,np.asarray(points).copy()))
    def paintEvent(self,event):
        p=QtGui.QPainter(self);p.fillRect(self.rect(),QtGui.QColor('#111c27'))
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if not self.model.fresh('cloud'):
            p.setPen(QtGui.QColor('#94a3b8'));p.drawText(self.rect(),QtCore.Qt.AlignCenter,'点群未接続');p.end();return
        # Pinhole view at the LiDAR origin: x forward, y left, z up.
        focal=1.5*self.width()/(2*math.tan(math.radians(60)))
        def project(point):
            x,y,z=map(float,point[:3])
            if not all(math.isfinite(v) for v in (x,y,z)) or x<=.2:return None
            return QtCore.QPointF(self.width()/2-focal*y/x,self.height()/2-focal*z/x)
        p.setPen(QtGui.QPen(QtGui.QColor('#304657'),1))
        p.drawLine(0,self.height()//2,self.width(),self.height()//2)
        p.drawLine(self.width()//2-5,self.height()//2,self.width()//2+5,self.height()//2)
        # Draw distant points first so nearby objects remain visible.
        # Bound persistence across interruptions; old frames fade behind the newest.
        now=time.monotonic()
        while self.frames and now-self.frames[0][0]>1.:self.frames.popleft()
        frames=list(self.frames)
        if not frames:frames=[(now,np.asarray(self.model.cloud))]
        for index,(_,cloud) in enumerate(frames):
            alpha=0.2+0.8*(index+1)/len(frames)
            for row in sorted(cloud,key=lambda v:float(v[0]) if math.isfinite(v[0]) else -1,reverse=True):
                at=project(row)
                if at is None or not self.rect().contains(at.toPoint()):continue
                distance=float(np.linalg.norm(row[:3]))
                color=QtGui.QColor.fromHsvF(min(distance/45.,1.)*.65,.65,1.)
                color.setAlphaF(alpha)
                p.setPen(QtGui.QPen(color,2));p.drawPoint(at)
        labels={t['id'].split(':')[-1]:t.get('label','') for t in self.model.behavior.get('targets',[])}
        for t in self.model.tracks:
            at=project(t['center'])
            if at is None:continue
            p.setPen(QtGui.QPen(QtGui.QColor('#ff785a'),2))
            if 'lo' in t and 'hi' in t:
                corners=[project([t['hi' if mask&(1<<axis) else 'lo'][axis] for axis in range(3)]) for mask in range(8)]
                for mask in range(8):
                    for axis in range(3):
                        other=mask^(1<<axis)
                        if mask<other and corners[mask] is not None and corners[other] is not None:
                            p.drawLine(corners[mask],corners[other])
            else:p.drawEllipse(at,7,7)
            p.drawText(at+QtCore.QPointF(10,-5),f"ID {t['track_id']}  {t['score']:.2f}  {labels.get(str(t['track_id']), '')}")
        p.setPen(QtGui.QColor('white'));p.drawText(12,22,'LiDAR主観・前方視点（1.5倍拡大・直近10フレーム／色：近=赤、遠=青）')
        if not self.model.fresh('tracks'):p.drawText(12,45,'検知結果待機 / 通信途絶')
        p.end()

class CameraView(QtWidgets.QWidget):
    def __init__(self):
        super().__init__();self.image=None;self.received=0.;self.setMinimumSize(320,150)
    def receive(self,msg):
        formats={'rgb8':(3,QtGui.QImage.Format_RGB888),'bgr8':(3,QtGui.QImage.Format_RGB888),'mono8':(1,QtGui.QImage.Format_Grayscale8)}
        if msg.encoding not in formats:return
        channels,fmt=formats[msg.encoding]
        if msg.width<=0 or msg.height<=0 or msg.step<msg.width*channels or len(msg.data)<msg.step*msg.height:return
        image=QtGui.QImage(bytes(msg.data),msg.width,msg.height,msg.step,fmt).copy()
        self.image=image.rgbSwapped() if msg.encoding=='bgr8' else image;self.received=time.monotonic();self.update()
    def receive_compressed(self,msg):
        image=QtGui.QImage.fromData(bytes(msg.data))
        if image.isNull():return
        self.image=image;self.received=time.monotonic();self.update()
    def paintEvent(self,event):
        p=QtGui.QPainter(self);p.fillRect(self.rect(),QtGui.QColor('#111c27'))
        if self.image is not None and time.monotonic()-self.received<2:
            image=self.image.scaled(self.size(),QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation)
            p.drawImage((self.width()-image.width())//2,(self.height()-image.height())//2,image)
        else:p.setPen(QtGui.QColor('#94a3b8'));p.drawText(self.rect(),QtCore.Qt.AlignCenter,getattr(self,'waiting_text','カメラ未接続'))
        p.end()


class Dashboard(QtWidgets.QMainWindow):
    def __init__(self,node,interactive=False,spin=None):
        super().__init__();self.node=node;self.spin=spin or self.drain_ros
        self.model=ViewModel();self.futures=[];self.rviz=None;self.last_tree_key=None;self.interactive=interactive
        self.setWindowTitle('GENIAC — '+('ドラッグ位置入力・統合テスト' if interactive else '鹿の認識・反応・シナリオ'))
        self.resize(1500,960)
        self.screen_capture=ScreenCapture(node.declare_parameter('screen_record_dir',str(Path.home()/'geniac_screen_recordings')).value) if node.declare_parameter('screen_record',False).value and not interactive else None
        central=QtWidgets.QWidget();self.setCentralWidget(central);outer=QtWidgets.QVBoxLayout(central)
        columns=QtWidgets.QSplitter();outer.addWidget(columns)
        controls=QtWidgets.QWidget();columns.addWidget(controls);layout=QtWidgets.QVBoxLayout(controls)
        layout.setContentsMargins(0,0,0,0)
        self.status=QtWidgets.QLabel('接続待機');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.toolbar=QtWidgets.QGridLayout();layout.addLayout(self.toolbar)
        def add_control(widget):
            index=self.toolbar.count();self.toolbar.addWidget(widget,index//3,index%3)
        self.webrtc=None;self.lidar_webrtc=None
        self.use_webrtc=node.declare_parameter('webrtc_enabled',False).value and not interactive
        self.microphone=MicrophoneMonitor() if not interactive else None
        if self.microphone:
            self.mic_toggle=QtWidgets.QCheckBox('現地マイクを聞く');self.mic_toggle.setChecked(True)
            self.microphone.enabled=True
            self.mic_toggle.toggled.connect(lambda enabled:setattr(self.microphone,'enabled',enabled))
            add_control(self.mic_toggle)
            self.mic_volume=QtWidgets.QSlider(QtCore.Qt.Horizontal);self.mic_volume.setRange(0,100);self.mic_volume.setValue(50);self.mic_volume.setMaximumWidth(100)
            self.mic_volume.setToolTip('マイクの試聴音量（録音音量は変わりません）')
            self.mic_volume.valueChanged.connect(lambda value:setattr(self.microphone,'volume',value))
            add_control(self.mic_volume)
            self.mic_status=QtWidgets.QLabel('マイク接続待機');self.mic_status.setWordWrap(True);add_control(self.mic_status)
            if not self.use_webrtc:
                node.create_subscription(String,MICROPHONE_TOPIC,lambda m:self.microphone.receive(m.data,node.get_clock().now().nanoseconds/1e9),qos_profile_sensor_data)
        self.screen_status=QtWidgets.QLabel('画面録画：待受' if self.screen_capture else '');layout.addWidget(self.screen_status)
        self.result=QtWidgets.QLabel('' if not interactive else 'テスト開始後、鹿をドラッグしてください。放すと固定。破線の外に出して5秒で完全退避。');self.result.setWordWrap(True);layout.addWidget(self.result)
        if not interactive:self.result.hide()
        self.stock_panel=StockPanel()
        left=QtWidgets.QSplitter(QtCore.Qt.Vertical);layout.addWidget(left,1)
        self.media=QtWidgets.QGroupBox('カメラ');media_layout=QtWidgets.QVBoxLayout(self.media)
        self.camera=CameraView();self.cloud=CameraView() if self.use_webrtc else CloudView(self.model);self.cloud.setMinimumSize(320,150)
        if self.use_webrtc:self.cloud.waiting_text='点群映像未接続'
        media_layout.addWidget(self.camera)
        right=QtWidgets.QSplitter(QtCore.Qt.Vertical);columns.addWidget(right)
        cloud_panel=QtWidgets.QGroupBox('LiDAR点群');cloud_layout=QtWidgets.QVBoxLayout(cloud_panel)
        cloud_layout.addWidget(self.cloud);right.addWidget(cloud_panel)
        left.addWidget(self.media)
        self.position=PositionView(self.model,interactive);left.addWidget(self.position)
        graph_panel=QtWidgets.QGroupBox('現在のシナリオツリー');self.graph_panel=graph_panel;gl=QtWidgets.QVBoxLayout(graph_panel)
        self.graph=StoryGraph();self.scene=self.graph.scene()
        gl.addWidget(self.graph);right.addWidget(graph_panel)
        story_area=QtWidgets.QWidget();story_layout=QtWidgets.QVBoxLayout(story_area);story_layout.setContentsMargins(0,0,0,0)
        story_layout.addWidget(self.stock_panel)
        text_panel=QtWidgets.QGroupBox('ストーリー・前回からの改善');tl=QtWidgets.QVBoxLayout(text_panel)
        story_layout.addWidget(text_panel,1)
        self.details=QtWidgets.QPlainTextEdit();self.details.setReadOnly(True);tl.addWidget(self.details);left.addWidget(story_area)
        columns.setSizes([480,980]);left.setSizes([320,280,200])
        right.setSizes([250,630]);right.setStretchFactor(0,1);right.setStretchFactor(1,3)
        columns.setStretchFactor(0,1);columns.setStretchFactor(1,2)
        left.setStretchFactor(0,3);left.setStretchFactor(1,3);left.setStretchFactor(2,2)
        self.clients={s:node.create_client(Trigger,s) for s in ['/geniac/scenario/start','/geniac/scenario/stop','/geniac/recording/start','/geniac/recording/stop']}
        qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        for topic,kind,quality in [('/geniac_detector/tracks','tracks',1),('/geniac/behavior','behavior',10),
                ('/geniac/scenario/stock','stock',qos),('/geniac/scenario/state','scenario',qos),('/geniac/scenario/tree','tree',qos),('/geniac/recording/status','recording',10)]:
            node.create_subscription(String,topic,lambda m,k=kind:self.packet(k,m),quality)
        self.cloud_topic=node.declare_parameter('cloud_topic','/livox/lidar').value
        if not self.use_webrtc:node.create_subscription(PointCloud2,self.cloud_topic,self.pointcloud,qos_profile_sensor_data)
        camera_topic=node.declare_parameter('camera_topic','/camera/image_raw').value
        if self.use_webrtc:
            from .webrtc_client import WebRTCClient
            self.webrtc=WebRTCClient(node.declare_parameter('webrtc_url','http://192.168.1.64:8766').value,
                node.declare_parameter('webrtc_token_file',str(Path.home()/'geniac_ros2_ws/.media-token')).value,self.microphone)
            self.lidar_webrtc=WebRTCClient(self.webrtc.url+'/lidar',node.get_parameter('webrtc_token_file').value)
        else:
            node.create_subscription(Image,camera_topic,self.camera.receive,qos_profile_sensor_data)
            node.create_subscription(CompressedImage,camera_topic+'/compressed',self.camera.receive_compressed,qos_profile_sensor_data)
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)

    def drain_ros(self):
        # Camera + LiDAR + status exceed one callback per 50 ms GUI frame.
        # Bound the work so rendering stays responsive without queueing stale images.
        deadline=time.monotonic()+.015
        for _ in range(64):
            if time.monotonic()>=deadline:break
            rclpy.spin_once(self.node,timeout_sec=0)

    def packet(self,kind,msg):
        try:
            data=json.loads(msg.data)
            if kind=='scenario':data['_received_mono']=time.monotonic()
            self.model.update(kind,data)
        except (ValueError,KeyError,TypeError):self.result.setText('不正な'+kind+'メッセージを破棄')
    def pointcloud(self,msg):
        if msg.header.frame_id!='livox_frame':self.result.setText('点群のframe_idがlivox_frameと異なります');return
        try:
            points=decode_cloud(msg,200000);points=points[::max(1,len(points)//5000)]
            self.model.update('cloud',points);self.cloud.add_frame(points)
        except (ValueError,TypeError):self.result.setText('点群形式を読み取れません')
    def call(self,service):
        c=self.clients[service]
        if not c.service_is_ready():self.result.setText('サービス未接続: '+service);return
        if any(s==service for s,f in self.futures):return
        self.futures.append((service,c.call_async(Trigger.Request())));self.result.setText('要求中: '+service)
    def open_rviz(self):
        if self.rviz and self.rviz.poll() is None:return
        cfg=Path(get_package_share_directory('geniac_visualizer'))/'config/geniac.rviz'
        try:self.rviz=subprocess.Popen(['rviz2','-d',str(cfg),'--ros-args','-r','/livox/lidar:='+self.cloud_topic])
        except OSError:self.result.setText('rviz2が見つかりません')
    def draw_tree(self):
        tree=self.model.tree
        number=tree.get('story',{}).get('sequence')
        self.graph_panel.setTitle(f'現在のシナリオツリー No.{number:04d}' if isinstance(number,int) else '現在のシナリオツリー No.—')
        if not tree.get('nodes'):return
        key=json.dumps(tree,sort_keys=True)
        if key!=self.last_tree_key:self.last_tree_key=key;self.graph.set_tree(tree)
        scenario=self.model.scenario
        self.graph.update_state(scenario.get('node'),bool(scenario.get('paused')),scenario.get('transitions',[]))
        if scenario.get('reason')=='repeat_interval' and scenario.get('node') in self.graph.nodes:
            self.graph.nodes[scenario['node']].set_caption('次の衝撃音を待機')
        if scenario.get('paused') and scenario.get('node') in self.graph.nodes:
            self.graph.nodes[scenario['node']].set_caption('復旧待ち（自動再開）')
        if scenario.get('reason')=='awaiting_behavior' and scenario.get('node') in self.graph.nodes:
            item=self.graph.nodes[scenario['node']];item.set_caption('行動の確定待ち（自動）')
    def tick(self):
        if self.lidar_webrtc and self.lidar_webrtc.frame:
            data,width,height,received=self.lidar_webrtc.frame
            if received>self.cloud.received:
                self.cloud.image=QtGui.QImage(data,width,height,width*3,QtGui.QImage.Format_RGB888).copy()
                self.cloud.received=received;self.cloud.update()
        if self.webrtc and self.webrtc.frame:
            data,width,height,received=self.webrtc.frame
            if received>self.camera.received:
                self.camera.image=QtGui.QImage(data,width,height,width*3,QtGui.QImage.Format_RGB888).copy()
                self.camera.received=received;self.camera.update()
        self.spin();self.stock_panel.show_status(getattr(self.model,'stock',{}),self.model.fresh('stock',timeout=5.));self.model.expire();self.cloud.update();self.camera.update();self.position.update();self.draw_tree()
        for service,future in list(self.futures):
            if future.done():
                try:
                    response=future.result();self.result.setText(('成功: ' if response.success else '失敗: ')+response.message)
                except Exception:self.result.setText('サービス呼び出し失敗')
                self.futures.remove((service,future))
        scenario=self.model.scenario;behavior=self.model.behavior;story=scenario.get('story',{})
        pending=sum(t.get('present') is False and t.get('label')=='observing' for t in behavior.get('targets',[]))
        number=story.get('sequence');title=f"No.{number:04d} " if isinstance(number,int) else ''
        state=NAMES.get(behavior.get('state'),'判定待ち')
        playing='再生中' if scenario.get('running') else ('2秒停止を待っています' if scenario.get('armed') else '停止中')
        if scenario.get('reason')=='awaiting_behavior':playing='音声終了・行動確定待ち'
        if scenario.get('reason')=='repeat_interval':playing=f"次の衝撃音まで {scenario.get('repeat_remaining_seconds',0.):.3f}秒"
        if scenario.get('waiting')=='story_stock':playing='ストーリー補充待ち'
        if scenario.get('waiting')=='recording_start':playing='録画開始待ち（音声待機中）'
        errors={'input_stale':'行動データの更新途絶で停止','input_invalid':'行動データが無効のため停止',
                'audio_playback_error':'音声再生エラーで停止','audio_start_error':'音声開始エラーで停止','input_unknown':'行動判定の確定待ち'}
        if scenario.get('reason') in errors:playing=errors[scenario['reason']]
        if scenario.get('paused'):playing=playing.replace('で停止','で一時停止')+'（復旧後に自動再開）'
        self.status.setText(f"鹿 {len(self.model.tracks)}頭 / 退避確認待ち {pending}頭 / {state} ｜ {title}{story.get('title','シナリオ待機')} ｜ {playing}")
        green=behavior.get('state')=='escaped' and behavior.get('valid') is True
        self.centralWidget().setStyleSheet('QWidget#centralPanel {border:3px solid '+('#22c55e' if green else '#64748b')+';}')
        self.centralWidget().setObjectName('centralPanel')
        current=self.model.tree.get('nodes',{}).get(scenario.get('node'),{})
        variation=story.get('variation',{})
        text=title+story.get('title','シナリオを待っています')+'\n\n'+story.get('premise','')
        text+='\n\n現在の場面：'+current.get('title','—')+'\n'+current.get('narrative','')
        text+='\n\n前回からの改善・変更\n'+story.get('change','未設定')
        text+='\n\n人数：'+str(variation.get('actor_count','—'))+' ／ '+ '・'.join(variation.get('roles',[]))
        text+='\n車両：'+variation.get('vehicle','—')+' ／ 武器：'+variation.get('weapon','—')
        text+='\n音の配置：'+variation.get('sound_arrangement','—')
        outline=story.get('outline',[])
        if outline:text+='\n\nストーリーの流れ\n'+' → '.join(n.get('title','') for n in outline if n.get('narrative'))
        text+='\n\n進行：'+('模擬入力による統合テスト（実地の評価には含めません）' if self.interactive else 'センサー入力')
        if self.details.toPlainText()!=text:self.details.setPlainText(text)
        if self.microphone:
            self.mic_status.setText((self.webrtc.status+' / ' if self.webrtc else '')+('マイク受信中' if time.monotonic()-self.microphone.last_received<2 else 'マイク未受信')+('・'+self.microphone.error if self.microphone.error else ''))
        if self.screen_capture:
            self.screen_capture.update(scenario,self.model.fresh('scenario'),self.capture_frame)
            status='録画中' if self.screen_capture.active else ('保存中' if self.screen_capture.finishing else '待受')
            if self.screen_capture.error:status='エラー: '+self.screen_capture.error
            self.screen_status.setText('画面録画：'+status+'（MP4・現地マイク音声は公開時に合成）')
    def capture_frame(self):
        source=self.grab().toImage()
        frame=QtGui.QImage(VideoWriter.width,VideoWriter.height,QtGui.QImage.Format_RGB888)
        frame.fill(QtCore.Qt.black)
        scaled=source.scaled(frame.size(),QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation)
        painter=QtGui.QPainter(frame);painter.drawImage((frame.width()-scaled.width())//2,(frame.height()-scaled.height())//2,scaled);painter.end()
        bits=frame.bits();bits.setsize(frame.byteCount());return bytes(bits)
    def closeEvent(self,event):
        self.timer.stop()
        if self.lidar_webrtc:self.lidar_webrtc.close()
        if self.webrtc:self.webrtc.close()
        if self.microphone:self.microphone.close()
        if self.screen_capture:self.screen_capture.close()
        event.accept()


def main(args=None):
    rclpy.init(args=args);app=QtWidgets.QApplication(sys.argv[:1]);node=Node('geniac_dashboard')
    window=Dashboard(node);window.show()
    signal.signal(signal.SIGINT,lambda *_:app.quit())
    signal.signal(signal.SIGTERM,lambda *_:app.quit())
    try:app.exec_()
    finally:
        window.timer.stop()
        if window.lidar_webrtc:window.lidar_webrtc.close()
        if window.webrtc:window.webrtc.close()
        if window.microphone:window.microphone.close()
        if window.screen_capture:window.screen_capture.close()
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
