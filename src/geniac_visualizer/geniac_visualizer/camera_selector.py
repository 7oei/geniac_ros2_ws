"""Select one outgoing camera with brightness hysteresis and freshness failover."""
import math

class CameraSelector:
    def __init__(self,dark=40.,bright=60.,dark_seconds=3.,bright_seconds=5.):
        if not 0<=dark<bright<=255:raise ValueError('Require 0 <= dark < bright <= 255')
        self.dark=dark;self.bright=bright;self.dark_seconds=dark_seconds;self.bright_seconds=bright_seconds
        self.desired='usb';self.pending=None;self.since=None;self.last=None;self.luminance=None
    def update(self,level,now):
        if not math.isfinite(level) or not 0<=level<=255:return
        if self.last is not None and now-self.last>3:self.pending=None;self.since=None
        self.last=now;self.luminance=level
        target='ir' if self.desired=='usb' and level<self.dark else 'usb' if self.desired=='ir' and level>self.bright else None
        if target is None:self.pending=None;self.since=None;return
        if self.pending!=target:self.pending=target;self.since=now
        delay=self.dark_seconds if target=='ir' else self.bright_seconds
        if now-self.since>=delay:self.desired=target;self.pending=None;self.since=None
    def choose(self,now,seen):
        if now-seen.get(self.desired,-1e9)<3:return self.desired
        other='ir' if self.desired=='usb' else 'usb'
        if now-seen.get(other,-1e9)<3:return other
        return None
