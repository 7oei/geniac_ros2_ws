"""Timestamped 16 kHz mono PCM transport and bounded mother-side monitoring."""
import base64
import json
import os
import queue
import subprocess
import threading
import time

RATE=16000
CHUNK=1280  # 40 ms, 16-bit mono
TOPIC='/camera/audio/pcm'


def decode_packet(text,now):
    d=json.loads(text)
    if d.get('rate')!=RATE or d.get('channels')!=1 or d.get('format')!='s16le':raise ValueError('Unsupported audio')
    if not -2<=now-float(d['stamp'])<=2:raise ValueError('Stale audio')
    pcm=base64.b64decode(d['pcm'],validate=True)
    if len(pcm)!=CHUNK:raise ValueError('Invalid audio chunk')
    return pcm


class MicrophoneMonitor:
    def __init__(self):
        self.enabled=False;self.volume=50;self.last_received=0.;self.error=''
        self.jobs=queue.Queue(maxsize=5);self.closed=threading.Event();self.process=None
        self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start()
    def receive(self,text,now):
        try:pcm=decode_packet(text,now)
        except (ValueError,KeyError,TypeError):return
        self.last_received=time.monotonic()
        if not self.enabled:return
        try:self.jobs.put_nowait(pcm)
        except queue.Full:
            try:self.jobs.get_nowait()
            except queue.Empty:pass
            try:self.jobs.put_nowait(pcm)
            except queue.Full:pass
    def stop_player(self):
        p=self.process;self.process=None
        if p:
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=.5)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=.5)
            if p.stdin:p.stdin.close()
    def work(self):
        previous_volume=None
        while not self.closed.is_set():
            if not self.enabled:
                self.stop_player()
                try:self.jobs.get(timeout=.1)
                except queue.Empty:pass
                continue
            try:pcm=self.jobs.get(timeout=.1)
            except queue.Empty:
                if time.monotonic()-self.last_received>2:self.stop_player()
                continue
            try:
                if self.process is None or self.process.poll() is not None or previous_volume!=self.volume:
                    self.stop_player()
                    self.process=subprocess.Popen(['paplay','--raw','--format=s16le','--rate=16000','--channels=1',
                        '--latency-msec=100','--volume='+str(round(self.volume/100*65536))],
                        stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,bufsize=0)
                    previous_volume=self.volume
                self.process.stdin.write(pcm);self.error=''
            except (OSError,subprocess.SubprocessError) as exc:
                self.error=type(exc).__name__;self.stop_player();self.closed.wait(.5)
        self.stop_player()
    def close(self):
        self.closed.set()
        if self.process and self.process.poll() is None:self.process.terminate()
        self.thread.join(timeout=2)


def main(args=None):
    import signal
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import String
    rclpy.init(args=args);node=Node('geniac_microphone')
    source=node.declare_parameter('source','geniac_microphone').value
    pub=node.create_publisher(String,TOPIC,qos_profile_sensor_data)
    closed=threading.Event();holder=[]
    def capture():
        while not closed.is_set():
            p=None
            try:
                p=subprocess.Popen(['ffmpeg','-v','error','-nostdin','-f','pulse','-fragment_size','7680','-sample_rate','48000','-channels','2',
                    '-analyzeduration','0','-probesize','32','-i',source,'-ac','1','-ar',str(RATE),'-f','s16le','-flush_packets','1','pipe:1'],
                    stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
                holder[:]=[p]
                deadline=time.monotonic()
                while not closed.is_set():
                    pcm=p.stdout.read(CHUNK)
                    if len(pcm)!=CHUNK:raise RuntimeError('Microphone input ended')
                    # Pulse/FFmpeg may deliver several chunks in one read burst.
                    # Pace ROS publication so small DDS queues do not drop them.
                    deadline=max(deadline,time.monotonic())
                    if closed.wait(max(0,deadline-time.monotonic())):break
                    deadline+=CHUNK/(RATE*2)
                    pub.publish(String(data=json.dumps({'stamp':node.get_clock().now().nanoseconds/1e9,
                        'rate':RATE,'channels':1,'format':'s16le','pcm':base64.b64encode(pcm).decode()})))
            except (OSError,RuntimeError) as exc:node.get_logger().warning(str(exc)+'; retrying in 2s')
            finally:
                if p:
                    if p.poll() is None:p.terminate()
                    try:p.wait(timeout=2)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
                    if p.stdout:p.stdout.close()
            closed.wait(2)
    worker=threading.Thread(target=capture,daemon=True);worker.start()
    signal.signal(signal.SIGTERM,lambda *_:closed.set())
    signal.signal(signal.SIGINT,lambda *_:closed.set())
    try:
        while rclpy.ok() and not closed.is_set():rclpy.spin_once(node,timeout_sec=.2)
    finally:
        closed.set()
        if holder and holder[0].poll() is None:holder[0].terminate()
        worker.join(timeout=3);node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
