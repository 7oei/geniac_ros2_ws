"""Authenticated LAN WebRTC gateway consuming only loopback ROS media."""
import asyncio
import base64
from fractions import Fraction
import json
import os
from pathlib import Path
import secrets
import socket
import threading
import time
import av
import cv2
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection,RTCSessionDescription,RTCConfiguration,MediaStreamTrack,RTCRtpSender
from aiortc.contrib.media import MediaRelay
from .local_network import configure_local


def notify(message):
    address=os.environ.get('NOTIFY_SOCKET')
    if address:
        if address.startswith('@'):address='\0'+address[1:]
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as s:s.sendto(message.encode(),address)

class Media:
    def __init__(self,loop):
        self.loop=loop;self.image=None;self.image_event=asyncio.Event();self.audio=asyncio.Queue(maxsize=5)
        self.start=time.monotonic();self.video_received=0.;self.audio_received=0.
    def video(self,msg):
        self.image=bytes(msg.data);self.video_received=time.monotonic();self.image_event.set()
    def raw_video(self,msg):
        channels={'mono8':1,'rgb8':3,'bgr8':3}.get(msg.encoding)
        if not channels or msg.width<=0 or msg.height<=0 or msg.step<msg.width*channels or len(msg.data)!=msg.step*msg.height:return
        rows=np.frombuffer(msg.data,np.uint8).reshape(msg.height,msg.step)[:,:msg.width*channels]
        image=rows.reshape(msg.height,msg.width,channels)
        if channels==1:image=cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
        elif msg.encoding=='rgb8':image=cv2.cvtColor(image,cv2.COLOR_RGB2BGR)
        self.image=image.copy();self.video_received=time.monotonic();self.image_event.set()
    def sound(self,msg):
        try:
            d=json.loads(msg.data)
            if d['rate']!=16000 or d['channels']!=1 or d['format']!='s16le':return
            pcm=base64.b64decode(d['pcm'],validate=True)
            if len(pcm)!=1280:return
        except (ValueError,KeyError,TypeError):return
        if self.audio.full():self.audio.get_nowait()
        self.audio.put_nowait(pcm);self.audio_received=time.monotonic()

class Video(MediaStreamTrack):
    kind='video'
    def __init__(self,media):super().__init__();self.media=media
    async def recv(self):
        await self.media.image_event.wait();self.media.image_event.clear()
        image=self.media.image if isinstance(self.media.image,np.ndarray) else cv2.imdecode(np.frombuffer(self.media.image,np.uint8),cv2.IMREAD_COLOR)
        frame=av.VideoFrame.from_ndarray(image,format='bgr24')
        frame.pts=int((time.monotonic()-self.media.start)*90000);frame.time_base=Fraction(1,90000)
        return frame

class Audio(MediaStreamTrack):
    kind='audio'
    def __init__(self,media):super().__init__();self.media=media;self.pts=None;self.process=None;self.deadline=None
    async def recv(self):
        if self.process is None or self.process.returncode is not None:
            env=dict(os.environ,PULSE_SERVER='unix:/run/user/'+str(os.getuid())+'/geniac-scenario-audio/native')
            self.process=await asyncio.create_subprocess_exec('ffmpeg','-v','error','-nostdin','-f','pulse',
                '-fragment_size','3840','-sample_rate','48000','-channels','2','-analyzeduration','0','-probesize','32',
                '-i','geniac_microphone','-ac','1','-ar','48000','-f','s16le','-flush_packets','1','pipe:1',
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=env)
        pcm=await self.process.stdout.readexactly(1920)
        now=time.monotonic()
        if self.deadline is None or now-self.deadline>.1:self.deadline=now
        await asyncio.sleep(max(0,self.deadline-now));self.deadline+=.02
        frame=av.AudioFrame.from_ndarray(np.frombuffer(pcm,np.int16).reshape(1,-1),format='s16',layout='mono')
        if self.pts is None:self.pts=int((time.monotonic()-self.media.start)*48000)
        frame.sample_rate=48000;frame.time_base=Fraction(1,48000);frame.pts=self.pts;self.pts+=frame.samples
        return frame
    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:await asyncio.wait_for(self.process.wait(),2)
            except asyncio.TimeoutError:self.process.kill();await self.process.wait()


async def run():
    from aiortc.codecs import h264
    h264.MAX_BITRATE=1500000
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import CompressedImage,Image
    from std_msgs.msg import String
    configure_local();rclpy.init();node=Node('geniac_webrtc_media')
    loop=asyncio.get_running_loop();media=Media(loop);peers=set();relay=MediaRelay();video=Video(media);audio=Audio(media)
    video_topic=os.environ.get('GENIAC_WEBRTC_VIDEO_TOPIC','/camera/image_raw/compressed')
    compressed=video_topic.endswith('/compressed')
    callback=media.video if compressed else media.raw_video
    subs=[node.create_subscription(CompressedImage if compressed else Image,video_topic,lambda m:loop.call_soon_threadsafe(callback,m),qos_profile_sensor_data),
          node.create_subscription(String,'/camera/audio/pcm',lambda m:loop.call_soon_threadsafe(media.sound,m),qos_profile_sensor_data)]
    thread=threading.Thread(target=lambda:rclpy.spin(node),daemon=True);thread.start()
    token=Path(os.environ.get('GENIAC_MEDIA_TOKEN_FILE',str(Path.home()/'geniac_ros2_ws/.media-token'))).read_text().strip()
    if len(token)<32:raise ValueError('Missing media authentication token')
    @web.middleware
    async def auth(request,handler):
        if not secrets.compare_digest(request.headers.get('Authorization',''),'Bearer '+token):raise web.HTTPUnauthorized()
        return await handler(request)
    async def offer(request):
        if len(peers)>=3:raise web.HTTPServiceUnavailable(text='Too many viewers')
        data=await request.json()
        pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));peers.add(pc);pc._geniac_started=time.monotonic()
        @pc.on('connectionstatechange')
        async def state():
            if pc.connectionState in ('failed','closed'):
                await pc.close();peers.discard(pc)
        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=data['sdp'],type=data['type']))
            pc.addTrack(relay.subscribe(video,buffered=False));pc.addTrack(relay.subscribe(audio,buffered=False))
            for t in pc.getTransceivers():
                if t.kind=='video':
                    codecs=[c for c in RTCRtpSender.getCapabilities('video').codecs if c.mimeType=='video/H264']
                    if codecs:t.setCodecPreferences(codecs)
            await pc.setLocalDescription(await pc.createAnswer())
            return web.json_response({'sdp':pc.localDescription.sdp,'type':pc.localDescription.type})
        except Exception:
            await pc.close();peers.discard(pc);raise
    async def health(request):
        now=time.monotonic()
        return web.json_response({'video_topic':video_topic,'viewers':len(peers),'video_age':now-media.video_received,'audio_age':now-media.audio_received})
    app=web.Application(middlewares=[auth],client_max_size=65536);app.router.add_post('/offer',offer);app.router.add_get('/health',health)
    runner=web.AppRunner(app);await runner.setup()
    await web.TCPSite(runner,os.environ.get('GENIAC_MEDIA_BIND','192.168.1.64'),8766).start();notify('READY=1')
    try:
        while True:
            notify('WATCHDOG=1')
            for pc in tuple(peers):
                if pc.connectionState in ('failed','closed','disconnected') or (pc.connectionState!='connected' and time.monotonic()-pc._geniac_started>20):
                    await pc.close();peers.discard(pc)
            await asyncio.sleep(5)
    finally:
        await asyncio.gather(*(pc.close() for pc in peers));await audio.close();await runner.cleanup();rclpy.shutdown();thread.join(timeout=2)

def main():asyncio.run(run())
