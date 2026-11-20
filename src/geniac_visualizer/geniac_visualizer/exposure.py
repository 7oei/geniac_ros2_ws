"""Bounded image-feedback exposure for V4L2 cameras (100 microsecond units)."""
import re
import subprocess
import time
import cv2
import numpy as np


def next_exposure(current, luminance, minimum, maximum, target=85.):
    if abs(luminance-target)<=8:return current
    ratio=max(.65,min(1.5,target/max(1.,luminance)))
    return max(minimum,min(maximum,round(current*ratio)))


class AutoExposure:
    def __init__(self,device,maximum=1000,log=lambda message:None):
        self.device=device;self.maximum=maximum;self.log=log
        self.active=False;self.next_update=0.
    def command(self,*args):
        return subprocess.run(['v4l2-ctl','-d',self.device,*args],check=True,
                              capture_output=True,text=True,timeout=2).stdout
    def start(self):
        try:
            controls=self.command('--list-ctrls-menus')
            match=re.search(r'exposure_time_absolute\s+.*min=(\d+) max=(\d+).*value=(\d+)',controls)
            if not match or '1: Manual Mode' not in controls:raise ValueError('manual exposure unavailable')
            self.minimum=int(match[1]);self.maximum=min(self.maximum,int(match[2]))
            if self.maximum<self.minimum:raise ValueError('exposure range unavailable')
            self.current=max(self.minimum,min(self.maximum,int(match[3])))
            self.command('--set-ctrl=auto_exposure=1')
            self.command(f'--set-ctrl=exposure_time_absolute={self.current}')
            self.active=True;self.next_update=time.monotonic()+1
            self.log(f'Adaptive exposure enabled: {self.minimum}..{self.maximum} (100 us)')
        except (OSError,ValueError,subprocess.SubprocessError) as e:
            self.log(f'Adaptive exposure unavailable: {e}; using camera auto exposure')
            self.close()
    def update(self,image):
        if not self.active or time.monotonic()<self.next_update:return
        self.next_update=time.monotonic()+1
        gray=cv2.cvtColor(image[::8,::8],cv2.COLOR_BGR2GRAY)
        level=float(np.mean(gray))
        value=next_exposure(self.current,level,self.minimum,self.maximum)
        if value==self.current:return
        try:
            self.command(f'--set-ctrl=exposure_time_absolute={value}')
            self.current=value
        except (OSError,subprocess.SubprocessError) as e:
            self.log(f'Exposure control failed: {e}; restoring camera auto exposure');self.close()
    def close(self):
        self.active=False
        try:self.command('--set-ctrl=auto_exposure=3')
        except (OSError,subprocess.SubprocessError):pass
