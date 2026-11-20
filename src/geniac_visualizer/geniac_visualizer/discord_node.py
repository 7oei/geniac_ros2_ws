import signal
import json
import os
from pathlib import Path
import queue
import shlex
import threading
import time
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String
from .notifications import EntryGate, send, validate_webhook

class DiscordNode(Node):
    def __init__(self):
        super().__init__('geniac_discord')
        self.enabled=self.declare_parameter('enabled',False).value
        path=self.declare_parameter('env_file','').value
        self.webhook=os.getenv('DISCORD_WEBHOOK_URL','')
        if path and not self.webhook:
            for line in Path(path).read_text().splitlines():
                k,sep,v=line.strip().removeprefix('export ').partition('=')
                if sep and k=='DISCORD_WEBHOOK_URL':
                    parts=shlex.split(v,comments=True);self.webhook=parts[0] if parts else ''
        if self.enabled and not self.webhook:raise ValueError('DISCORD_WEBHOOK_URL is required when enabled')
        if self.enabled:validate_webhook(self.webhook)
        self.gate=EntryGate();self.jobs=queue.Queue(maxsize=1);self.closed=threading.Event()
        self.worker=threading.Thread(target=self.work,daemon=True);self.worker.start()
        self.create_subscription(String,'/geniac_detector/tracks',self.receive,1)
    def receive(self,msg):
        try:
            p=json.loads(msg.data);age=self.get_clock().now().nanoseconds/1e9-p['stamp']
            if self.enabled and self.gate.update(p['tracks'],time.monotonic(),p.get('valid') is True and 0<=age<1):
                text=f"GENIAC: 視界に鹿候補 {len(p['tracks'])} 頭を検出（分類器による候補、要確認）。"
                try:self.jobs.put_nowait(text)
                except queue.Full:pass
        except (ValueError,KeyError,TypeError):pass
    def work(self):
        while not self.closed.is_set():
            try:text=self.jobs.get(timeout=.2)
            except queue.Empty:continue
            try:
                if not send(self.webhook,text):self.get_logger().warning('Discord delivery failed; no automatic resend')
            except ValueError:self.get_logger().warning('Discord webhook configuration invalid')
    def destroy_node(self):
        self.closed.set();self.worker.join(timeout=6);return super().destroy_node()

def main(args=None):
    rclpy.init(args=args);node=DiscordNode()
    try:rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
