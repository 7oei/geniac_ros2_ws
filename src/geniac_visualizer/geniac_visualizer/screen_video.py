"""Nonblocking widget capture, monotonic 10 fps encoding, durable completed videos."""
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path


def atomic_json(path,data):
    temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(data,ensure_ascii=False))
    with temp.open('rb') as f:os.fsync(f.fileno())
    temp.replace(path)


def video_info(path):
    result=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                           'stream=codec_name,width,height:format=duration','-of','json',str(path)],
                          check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
    info=json.loads(result.stdout);streams=info.get('streams',[])
    if not streams or streams[0]['codec_name']!='h264' or float(info['format']['duration'])<=0:
        raise ValueError('Invalid H.264 video')
    return info


class VideoWriter:
    width=1500;height=960;fps=10
    def __init__(self,root,state,first_frame):
        self.root=Path(root).expanduser();self.root.mkdir(parents=True,exist_ok=True)
        self.name='screen_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex
        self.latest=first_frame;self.lock=threading.Lock();self.closed=threading.Event();self.error='';self.frames=0
        self.outcome='visualizer_closed';self.started=time.time();self.state=dict(state)
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def offer(self,frame):
        if len(frame)!=self.width*self.height*3:raise ValueError('Unexpected video frame size')
        with self.lock:self.latest=frame
    def stop(self,reason):self.outcome=reason;self.closed.set()
    def run(self):
        pending=self.root/(self.name+'.partial.mp4');target=self.root/(self.name+'.mp4')
        process=None
        try:
            with (self.root/(self.name+'.log')).open('wb') as log:
                process=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo',
                    '-pixel_format','rgb24','-video_size',f'{self.width}x{self.height}','-framerate',str(self.fps),
                    '-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','23','-threads','2',
                    '-pix_fmt','yuv420p','-movflags','+faststart',str(pending)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
                started=time.monotonic()
                while True:
                    with self.lock:frame=self.latest
                    process.stdin.write(frame);self.frames+=1
                    if self.closed.is_set():break
                    self.closed.wait(max(0,started+self.frames/self.fps-time.monotonic()))
                # Include the final rendered escape/stop frame even when stop raced a write.
                with self.lock:frame=self.latest
                process.stdin.write(frame);self.frames+=1
                process.stdin.close()
                if process.wait(timeout=30)!=0:raise RuntimeError('Video encoder failed')
            info=video_info(pending)
            with pending.open('rb') as f:os.fsync(f.fileno())
            pending.replace(target)
            atomic_json(self.root/(self.name+'.json'),{'id':self.name,'created':self.started,
                'episode':self.state.get('epoch','').split(':')[0],'story':self.state.get('story',{}),
                'outcome':self.outcome,'duration':float(info['format']['duration']),
                'frames':self.frames,'status':'ready','filename':target.name})
        except Exception as exc:
            self.error=type(exc).__name__
            if process and process.poll() is None:
                process.kill();process.wait()
            atomic_json(self.root/(self.name+'.error.json'),{'error':self.error,'outcome':self.outcome})


class ScreenCapture:
    def __init__(self,root,writer=VideoWriter):
        self.root=root;self.writer=writer;self.active=None;self.finishing=[];self.last_capture=0.;self.error='';self.retry_at=0.
    def update(self,state,fresh,grab):
        episode=state.get('epoch','').split(':')[0]
        if self.active and self.active.error:
            self.error=self.active.error;self.finish('encoder_error');self.retry_at=time.monotonic()+3
        if self.active and fresh and episode and episode!=self.active.state.get('epoch','').split(':')[0]:
            self.finish('episode_replaced')
        if fresh and state.get('running') and episode and self.active is None and time.monotonic()>=self.retry_at:
            self.error='';self.active=self.writer(self.root,state,grab());self.last_capture=time.monotonic()
        if self.active:
            ending=fresh and not state.get('running') and not state.get('paused') and (state.get('reason')=='escaped' or state.get('armed') is False)
            if ending or time.monotonic()-self.last_capture>=.1:
                self.active.offer(grab());self.last_capture=time.monotonic()
            if ending:self.finish(state.get('reason','operator_stop'))
        for writer in list(self.finishing):
            if not writer.thread.is_alive():
                self.error=writer.error or self.error;self.finishing.remove(writer)
    def finish(self,reason):
        if self.active:
            self.active.stop(reason);self.finishing.append(self.active);self.active=None
    def close(self):
        self.finish('visualizer_closed')
        for writer in self.finishing:writer.thread.join(timeout=35)
