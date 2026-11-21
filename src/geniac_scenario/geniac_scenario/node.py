import signal
import json
from pathlib import Path
import time
import socket
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import QoSProfile, DurabilityPolicy
from rclpy.clock import Clock, ClockType
from std_msgs.msg import String
from std_srvs.srv import Trigger
from ament_index_python.packages import get_package_share_directory
from .tree import load_tree, audio_paths, runtime_tree
from .audio import Player
from .campaign import Campaign
from .stock import Stock, DEFAULT_STOCK
from .history import History
from .billing import state as billing_state

class ScenarioNode(Node):
    def __init__(self,**kwargs):
        super().__init__('geniac_scenario',**kwargs)
        default=str(Path(get_package_share_directory('geniac_scenario'))/'config/story_tree.yaml')
        path=Path(self.declare_parameter('tree_path',default).value)
        self.dry_run=self.declare_parameter('dry_run',True).value
        self.test_mode=self.declare_parameter('test_mode',False).value
        self.auto_arm=self.declare_parameter('auto_arm',True).value
        stock_dir=self.declare_parameter('stock_dir','').value
        self.stock=Stock(stock_dir) if self.declare_parameter('use_stock',bool(stock_dir)).value and stock_dir else None
        self.history=History(stock_dir or DEFAULT_STOCK)
        self.counted_trial=None
        volume=self.declare_parameter('volume',80).value
        self.campaign=Campaign(load_tree(path),armed=self.auto_arm,sink=self.record_result,
                               mode='simulation' if self.dry_run or self.test_mode else 'field',volume=volume)
        self.core.tree['wait_for_observation']=True
        self.core.tree['repeat_gap_max_seconds']=2.0
        self.paths=audio_paths(self.core.tree,path.parent,require=not self.dry_run and self.stock is None)
        self.player=Player(volume,self.dry_run)
        self.auto_record=self.declare_parameter('auto_record',False).value
        self.record_client=self.create_client(Trigger,'/geniac/recording/auto_start')
        self.record_future=None;self.prepared_tree=None;self.record_retry_at=0.
        self.report=None;self.received=None;self.playback_offset=0.
        qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub=self.create_publisher(String,'/geniac/scenario/state',qos)
        self.tree_pub=self.create_publisher(String,'/geniac/scenario/tree',qos)
        self.stock_pub=self.create_publisher(String,'/geniac/scenario/stock',qos)
        self.create_timer(1.,self.publish_stock,clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.events=self.create_publisher(String,'/geniac/scenario/events',10)
        self.create_subscription(String,'/geniac/behavior',self.receive,10)
        self.create_service(Trigger,'/geniac/scenario/start',self.start)
        self.create_service(Trigger,'/geniac/scenario/stop',self.stop)
        self.create_timer(.1,self.tick,clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.tree_pub.publish(String(data=json.dumps(self.core.tree)))

    def publish_stock(self):
        try:
            if self.stock:
                try:data=json.loads((self.history.root/'status.json').read_text())
                except (OSError,ValueError):data={'status':'checking'}
                # Validation belongs to the stock worker, never the sensor executor.
                # Its atomic status snapshot is sufficient for progress display.
            else:data={'status':'disabled','ready_count':0,'reserve_count':0,'target_count':0}
            fields=('latest_sequence','status','ready_count','reserve_count','target_count','sequence','completed','total','item','stage_started','updated_at','retry_seconds','error_type')
            packet={key:data[key] for key in fields if key in data}
            packet.update(source_host=socket.gethostname(),billing_blocked=bool(billing_state(self.history.root).get('blocked')))
            self.stock_pub.publish(String(data=json.dumps(packet,ensure_ascii=False)))
        except (OSError,ValueError,TypeError):
            self.stock_pub.publish(String(data=json.dumps({'status':'unavailable','source_host':socket.gethostname()})))

    def record_result(self,result):
        self.history.record(result)
        if self.test_mode:self.history.consume_manual(result['story_id'])

    @property
    def core(self):return self.campaign.core

    def select_stock(self):
        path=self.stock.next(consume=not self.dry_run and not self.test_mode)
        if path is None:return None
        tree=runtime_tree(load_tree(path));tree['wait_for_observation']=True;tree['repeat_gap_max_seconds']=2.0
        self.paths=audio_paths(tree,path.parent,require=not self.dry_run)
        self.tree_pub.publish(String(data=json.dumps(tree)))
        return tree

    def prepare_episode(self):
        if not self.auto_record:return self.select_stock() if self.stock else self.core.tree
        if self.prepared_tree is None:
            self.prepared_tree=self.select_stock() if self.stock else self.core.tree
        if self.prepared_tree is None:return None
        if time.monotonic()<self.record_retry_at:return None
        if self.record_future is None:
            if self.record_client.service_is_ready():self.record_future=self.record_client.call_async(Trigger.Request())
            return None
        if not self.record_future.done():return None
        try:response=self.record_future.result();success=response.success
        except Exception:success=False
        self.record_future=None
        if not success:
            self.record_retry_at=time.monotonic()+3
            self.get_logger().error('Automatic recording unavailable; scenario audio held')
            return None
        tree=self.prepared_tree;self.prepared_tree=None;return tree

    def receive(self,msg):
        try:
            data=json.loads(msg.data)
            if not isinstance(data.get('targets'),list) or not isinstance(data.get('stamp'),(int,float)):
                raise ValueError('Bad report')
            self.report=data;self.received=time.monotonic()
        except (ValueError,TypeError):
            self.report=None

    def start(self,request,response):
        self.campaign.armed=True;response.success=True;response.message='Armed; waiting for a visible deer to stop for 2 seconds'
        return response

    def stop(self,request,response):
        self.campaign.stop();self.player.stop()
        self.events.publish(String(data=json.dumps(self.core.state())))
        response.success=True;response.message='Stopped and disarmed';return response

    def tick(self):
        now=time.monotonic();stamp=self.get_clock().now().nanoseconds/1e9
        fresh=(self.report is not None and self.received is not None and now-self.received<1.
               and self.report.get('valid') is True and 0<=stamp-self.report['stamp']<1.)
        eligible=(self.campaign.armed and fresh and any(t.get('present') is True and t.get('stationary_seconds',0)>=2.
                  and t.get('label') not in ('unknown','escaped') for t in (self.report or {}).get('targets',[])))
        if self.auto_record and not self.core.running and not self.campaign.paused and not eligible:
            self.record_future=None
        if self.player.failed():
            changed=self.campaign.pause('audio_playback_error',now)
            if changed:self.campaign.pause_elapsed=self.playback_offset
            self.player.stop()
        else:
            changed=self.campaign.tick(now,stamp,self.report or {},fresh,
                                       self.prepare_episode if self.stock or self.auto_record else None,
                                       input_reason='input_invalid' if self.report is not None and self.report.get('valid') is not True else 'input_stale')
        if self.auto_record and eligible and self.prepared_tree is not None and not self.core.running:
            self.campaign.waiting='recording_start'
        trial=self.campaign.trial
        if trial and trial.trial_id!=self.counted_trial:
            if self.test_mode or self.dry_run:
                self.history.begin_playback(trial.story.get('id'),trial.trial_id)
            self.counted_trial=trial.trial_id
        if self.test_mode and self.core.running:
            n=self.core.tree['nodes'][self.core.node_id]
            if now-self.core.entered>=n['duration'] and self.core.tree['nodes'][n['branches']['no_escape']].get('terminal'):
                self.history.consume_manual(self.core.tree.get('story',{}).get('id'))
        if changed:
            try:
                if self.core.reason=='repeat_interval':
                    self.player.stop()
                elif self.core.running:
                    n=self.core.tree['nodes'][self.core.node_id]
                    offset=self.campaign.pause_elapsed if self.core.reason=='resumed' else 0.
                    self.playback_offset=offset
                    if n['duration']>offset:self.player.play(self.paths.get(self.core.node_id),n['duration']-offset,offset=offset)
                    else:self.player.stop()
                else:
                    self.player.stop()
            except (OSError,ValueError) as exc:
                self.player.last_error=f'{type(exc).__name__}: {exc}'
                self.player.stop();self.campaign.pause('audio_start_error',now)
                self.campaign.pause_elapsed=self.playback_offset
            if self.core.reason in ('input_stale','input_invalid','audio_playback_error','audio_start_error'):
                age=None if self.received is None else round(now-self.received,3)
                report_age=None if not self.report else round(stamp-self.report['stamp'],3)
                self.get_logger().error(f'Scenario stopped: {self.core.reason}; receive_age={age}s; report_age={report_age}s; valid={self.report.get("valid") if self.report else None}; audio={self.player.last_error}')
            self.events.publish(String(data=json.dumps(self.core.state())))
        d=self.core.state();d.update(armed=self.campaign.armed,dry_run=self.dry_run,stamp=stamp,
            recording_pending=bool(self.auto_record and eligible and self.prepared_tree is not None),
            campaign_active=self.campaign.active,round=self.campaign.round,waiting=self.campaign.waiting,paused=self.campaign.paused,
            story=self.core.tree.get('story',{}),last_evaluation=self.campaign.last_result)
        self.pub.publish(String(data=json.dumps(d,allow_nan=False)))

    def destroy_node(self):
        self.campaign.stop('shutdown');self.player.stop();return super().destroy_node()


def main(args=None):
    rclpy.init(args=args);node=ScenarioNode()
    try:rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
