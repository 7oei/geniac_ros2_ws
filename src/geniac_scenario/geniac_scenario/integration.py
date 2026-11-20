"""Real ROS behavior/player/dashboard integration with a draggable simulated tracker."""
import argparse
import json
import os
from pathlib import Path
import sys
import signal
import time
import uuid
from PyQt5 import QtCore,QtWidgets
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.executors import SingleThreadedExecutor
from ament_index_python.packages import get_package_share_directory
from std_msgs.msg import String
from geniac_behavior.node import BehaviorNode
from geniac_scenario.node import ScenarioNode
from geniac_scenario.stock import DEFAULT_STOCK
from geniac_scenario.billing import state as billing_state,approve as approve_billing
from geniac_visualizer.dashboard import Dashboard


class SimulatedTracker(Node):
    def __init__(self):
        super().__init__('geniac_simulated_tracker');self.view=None;self.active=False;self.valid=True
        self.stream=uuid.uuid4().hex
        self.publisher=self.create_publisher(String,'/geniac_detector/tracks',1)
        self.create_timer(.05,self.publish)
    def publish(self):
        tracks=self.view.tracks() if self.view and self.active else []
        packet={'version':1,'stamp':self.get_clock().now().nanoseconds/1e9,'frame_id':'livox_frame',
                'stream_id':self.stream,'valid':self.valid,'tracks':tracks if self.valid else []}
        self.publisher.publish(String(data=json.dumps(packet)))


class IntegrationWindow(Dashboard):
    def __init__(self,node,tracker,scenario,executor):
        def spin():
            if not rclpy.ok():
                QtWidgets.QApplication.instance().quit();return
            deadline=time.monotonic()+.008
            for _ in range(40):
                executor.spin_once(timeout_sec=0)
                if time.monotonic()>deadline:break
        super().__init__(node,interactive=True,spin=spin)
        self.tracker=tracker;self.scenario_node=scenario;tracker.view=self.position
        self.start_test=QtWidgets.QPushButton('▶ 統合テスト開始');self.start_test.clicked.connect(self.begin)
        self.stop_test=QtWidgets.QPushButton('■ 停止');self.stop_test.clicked.connect(self.end)
        self.toolbar.addWidget(self.start_test);self.toolbar.addWidget(self.stop_test)
        self.sound=QtWidgets.QCheckBox('音声を再生');self.sound.setChecked(not scenario.dry_run)
        self.sound.toggled.connect(self.set_audio);self.toolbar.addWidget(self.sound)
        self.toolbar.addWidget(QtWidgets.QLabel('鹿の頭数'))
        self.count=QtWidgets.QSpinBox();self.count.setRange(1,3);self.count.valueChanged.connect(self.set_count);self.toolbar.addWidget(self.count)
        self.present=QtWidgets.QCheckBox('鹿を検出する');self.present.setChecked(True)
        self.present.toggled.connect(self.set_present);self.toolbar.addWidget(self.present)
        self.outage=QtWidgets.QCheckBox('センサー途絶を模擬');self.outage.toggled.connect(self.set_outage);self.toolbar.addWidget(self.outage)
        self.billing_button=QtWidgets.QPushButton('追加課金を伴うAPI利用の再開を許可')
        self.billing_button.clicked.connect(self.allow_billing);self.centralWidget().layout().insertWidget(4,self.billing_button)
        self.refill_timer=QtCore.QTimer(self);self.refill_timer.timeout.connect(self.refresh_refill);self.refill_timer.start(2000);self.refresh_refill()
        self.toolbar.addStretch();self.toolbar.addWidget(QtWidgets.QLabel('赤：動かない　橙：移動・視界内　緑枠：完全退避'))
    def allow_billing(self):approve_billing(self.scenario_node.history.root);self.refresh_refill()
    def refresh_refill(self):
        root=self.scenario_node.history.root;billing=billing_state(root);blocked=billing.get('blocked',False)
        self.billing_button.setVisible(blocked)
    def set_count(self,count):self.position.count=count;self.position.update()
    def set_present(self,present):self.position.enabled=present;self.position.update()
    def set_outage(self,outage):self.tracker.valid=not outage
    def set_audio(self,enabled):
        self.scenario_node.dry_run=not enabled;self.scenario_node.player.dry_run=not enabled
        if not enabled:self.scenario_node.player.stop()
    def begin(self):
        self.scenario_node.campaign.stop('test_restart');self.scenario_node.player.stop()
        self.tracker.stream=uuid.uuid4().hex;self.tracker.active=True
        self.scenario_node.campaign.armed=True
        self.result.setText('位置を20Hzで送信中。2秒停止すると自動開始します。以後の分岐は位置から自動判定します。')
    def end(self):
        self.tracker.active=False;self.scenario_node.campaign.stop('operator_stop');self.scenario_node.player.stop()
        self.result.setText('統合テストを停止しました。')
    def closeEvent(self,event):self.refill_timer.stop();self.end();super().closeEvent(event)


def main(args=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain-id',type=int,default=172)
    parser.add_argument('--mute',action='store_true')
    parser.add_argument('--tree');parser.add_argument('--stock-dir',default=str(DEFAULT_STOCK))
    options=parser.parse_args(args)
    if not 0<=options.domain_id<=232:parser.error('domain-id must be 0..232')
    os.environ['ROS_DOMAIN_ID']=str(options.domain_id);os.environ['ROS_LOCALHOST_ONLY']='1'
    rclpy.init(args=[]);app=QtWidgets.QApplication(sys.argv[:1]);executor=SingleThreadedExecutor();nodes=[]
    signal.signal(signal.SIGTERM,lambda *_:app.quit())
    signal.signal(signal.SIGINT,lambda *_:app.quit())
    try:
        tracker=SimulatedTracker();nodes.append(tracker)
        behavior=BehaviorNode();nodes.append(behavior)
        tree=options.tree or str(Path(get_package_share_directory('geniac_scenario'))/'config/story_tree.yaml')
        scenario=ScenarioNode(parameter_overrides=[Parameter('test_mode',value=True),Parameter('auto_arm',value=False),
            Parameter('dry_run',value=options.mute),Parameter('tree_path',value=tree),
            Parameter('stock_dir',value=options.stock_dir),Parameter('use_stock',value=not bool(options.tree))]);nodes.append(scenario)
        node=Node('geniac_integration_dashboard');nodes.append(node)
        for n in nodes:executor.add_node(n)
        window=IntegrationWindow(node,tracker,scenario,executor);window.show();app.exec_()
    finally:
        if 'window' in locals():window.close()
        executor.shutdown()
        for n in reversed(nodes):n.destroy_node()
        if rclpy.ok():rclpy.shutdown()


if __name__=='__main__':main()
