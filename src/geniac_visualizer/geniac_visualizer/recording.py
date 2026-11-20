"""Own one local rosbag process. Run this component on the sensor PC (k5)."""
from datetime import datetime, timezone
from pathlib import Path
import os
import signal
import subprocess
import uuid

TOPICS = ['/livox/lidar','/livox/imu','/geniac_detector/tracks','/geniac_detector/markers',
          '/geniac_detector/diagnostics','/geniac/behavior','/geniac/scenario/state',
          '/geniac/scenario/tree','/geniac/scenario/events','/tf','/tf_static']

class Recorder:
    def __init__(self,root,spawn=subprocess.Popen,send_signal=os.killpg):
        self.root=Path(root).expanduser().resolve();self.spawn=spawn;self.send_signal=send_signal
        self.process=None;self.output=None;self.log=None;self.error=''

    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        if self.running():return False,'Already recording'
        self.root.mkdir(parents=True,exist_ok=True)
        name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
        self.output=self.root/name;self.error=''
        if self.log:self.log.close()
        self.log=(self.root/(name+'.log')).open('w')
        try:
            self.process=self.spawn(['ros2','bag','record','-o',str(self.output),*TOPICS],
                stdin=subprocess.DEVNULL,stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True)
        except OSError:
            self.log.close();self.log=None;self.error='Failed to start ros2 bag';return False,self.error
        return True,str(self.output)

    def stop(self):
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
        return {'recording':self.running(),'output':str(self.output or ''),'error':self.error}
