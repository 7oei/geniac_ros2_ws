"""Own one local rosbag process. Run this component on the sensor PC (k5)."""
from datetime import datetime, timezone
from pathlib import Path
import os
import fcntl
import signal
import subprocess
import uuid
import time
from .scenario_audio import PlaybackCapture

TOPICS = ['/camera/audio/pcm','/livox/lidar','/livox/imu','/d435/camera/color/image_raw/compressed','/d435/camera/infra1/image_rect_raw','/d435/camera/color/camera_info','/d435/camera/infra1/camera_info','/geniac_detector/tracks','/geniac_detector/markers',
          '/geniac_detector/diagnostics','/geniac/behavior','/geniac/scenario/state',
          '/geniac/scenario/tree','/geniac/scenario/events','/tf','/tf_static']

class Recorder:
    def __init__(self,root,spawn=subprocess.Popen,send_signal=os.killpg,capture_audio=False):
        self.root=Path(root).expanduser().resolve();self.spawn=spawn;self.send_signal=send_signal
        self.process=None;self.output=None;self.log=None;self.error='';self.recording_lock=None
        self.audio=PlaybackCapture(self.root) if capture_audio else None

    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        if self.running():return False,'Already recording'
        self.root.mkdir(parents=True,exist_ok=True)
        name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
        self.output=self.root/name;self.error=''
        (self.root/'.archive').mkdir(exist_ok=True)
        self.recording_lock=(self.root/'.archive'/(name+'.recording.lock')).open('a')
        fcntl.flock(self.recording_lock,fcntl.LOCK_EX)
        if self.audio:self.audio.start(name)
        if self.log:self.log.close()
        self.log=(self.root/(name+'.log')).open('w')
        try:
            self.process=self.spawn(['ros2','bag','record','-o',str(self.output),*TOPICS],
                stdin=subprocess.DEVNULL,stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True)
        except OSError:
            if self.recording_lock:self.recording_lock.close();self.recording_lock=None
            if self.audio:self.audio.stop(self.output)
            self.log.close();self.log=None;self.error='Failed to start ros2 bag';return False,self.error
        return True,str(self.output)

    def wait_ready(self,timeout=8.):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if not self.running():return False,'Recorder exited before becoming ready'
            try:
                text=Path(self.log.name).read_text(errors='replace')
                if 'Recording...' in text or 'Recording started' in text:
                    # Allow subscription discovery before the first scenario/audio frame.
                    time.sleep(.5)
                    return self.running(),'Recording ready: '+str(self.output)
            except OSError:pass
            time.sleep(.1)
        self.stop();return False,'Recording readiness timed out; audio has not started'

    def stop(self):
        try:return self._stop()
        finally:
            if self.recording_lock:self.recording_lock.close();self.recording_lock=None

    def _stop(self):
        if self.audio and self.audio.output:self.audio.stop(self.output)
        if not self.running():
            if self.log:self.log.close();self.log=None
            return False,'Recorder is not running'
        forced=False
        try:
            self.send_signal(self.process.pid,signal.SIGINT)
            try:self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                forced=True;self.send_signal(self.process.pid,signal.SIGTERM)
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.send_signal(self.process.pid,signal.SIGKILL);self.process.wait(timeout=3)
        except ProcessLookupError:pass
        finally:
            if self.log:self.log.close();self.log=None
        if forced:
            self.error='Forced stop; check bag metadata before use';return False,self.error
        if self.process.poll() != 0:
            self.error='Recorder exited with an error; check its log and bag metadata'
            return False,self.error
        return True,'Recording stopped: '+str(self.output)

    def status(self):
        if self.process is not None and self.process.poll() not in (None,0) and not self.error:
            self.error='Recorder exited; inspect its local log'
        return {'recording':self.running(),'output':str(self.output or ''),'error':self.error,'audio_error':self.audio.error if self.audio else ''}
