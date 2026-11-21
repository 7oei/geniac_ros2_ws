"""Reconnecting native WebRTC receiver; no camera/audio DDS subscriptions."""
import asyncio
import base64
import json
from pathlib import Path
import threading
import time
import av
import aiohttp
from aiortc import RTCPeerConnection,RTCSessionDescription,RTCConfiguration

class WebRTCClient:
    def __init__(self,url,token_file,monitor):
        self.url=url.rstrip('/');self.token=Path(token_file).read_text().strip();self.monitor=monitor
        self.closed=threading.Event();self.frame=None;self.status='WebRTC接続待機';self.video_frames=0;self.audio_frames=0
        self.source_label=''
        self.thread=threading.Thread(target=lambda:asyncio.run(self.run()),daemon=True);self.thread.start()
    async def run(self):
        while not self.closed.is_set():
            pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));tasks=set();last=[time.monotonic()]
            async def receive(track):
                resampler=av.AudioResampler(format='s16',layout='mono',rate=16000) if track.kind=='audio' else None
                pending=bytearray()
                while not self.closed.is_set():
                    frame=await track.recv();last[0]=time.monotonic()
                    if track.kind=='video':
                        a=frame.to_ndarray(format='rgb24');self.frame=(a.tobytes(),a.shape[1],a.shape[0],time.monotonic());self.video_frames+=1
                    else:
                        for f in resampler.resample(frame):
                            pending.extend(f.to_ndarray().tobytes())
                        while len(pending)>=1280:
                            pcm=bytes(pending[:1280]);del pending[:1280]
                            self.monitor.receive(json.dumps({'stamp':time.time(),'rate':16000,'channels':1,'format':'s16le','pcm':base64.b64encode(pcm).decode()}),time.time())
                            self.audio_frames+=1
            @pc.on('datachannel')
            def channel(ch):
                if ch.label!='camera_status':return
                @ch.on('message')
                def message(text):
                    try:self.source_label={'usb':'USBカメラ','ir':'D435 左IR','unavailable':'映像待機'}.get(json.loads(text).get('source'),'')
                    except (ValueError,TypeError):pass
            @pc.on('track')
            def track(t):
                task=asyncio.create_task(receive(t));tasks.add(task)
            try:
                pc.addTransceiver('video',direction='recvonly');pc.addTransceiver('audio',direction='recvonly')
                await pc.setLocalDescription(await pc.createOffer())
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    async with session.post(self.url+'/offer',headers={'Authorization':'Bearer '+self.token},json={'sdp':pc.localDescription.sdp,'type':pc.localDescription.type}) as reply:
                        reply.raise_for_status();answer=await reply.json()
                await pc.setRemoteDescription(RTCSessionDescription(**answer))
                while not self.closed.is_set():
                    self.status=('WebRTC接続中 '+self.source_label) if pc.connectionState=='connected' else 'WebRTC接続待機'
                    if pc.connectionState in ('failed','closed','disconnected') or time.monotonic()-last[0]>15:break
                    if any(t.done() for t in tasks):break
                    await asyncio.sleep(.2)
            except Exception as exc:self.status='WebRTC再接続待ち: '+type(exc).__name__
            finally:
                for t in tasks:t.cancel()
                await asyncio.gather(*tasks,return_exceptions=True);await pc.close()
            for _ in range(15):
                if self.closed.is_set():break
                await asyncio.sleep(.2)
    def close(self):self.closed.set();self.thread.join(timeout=3)
