"""Heartbeat deadlines with restart backoff, independent of the ROS executor."""
class Health:
    def __init__(self,now,timeout=30,cooldown=120):
        self.timeout=timeout;self.cooldown=cooldown;self.started=now;self.last={};self.retry=now+timeout
    def seen(self,name,now):self.last[name]=now
    def due(self,names,now):
        if now<self.retry:return []
        missing=[n for n in names if now-self.last.get(n,self.started)>self.timeout]
        if missing:self.retry=now+self.cooldown
        return missing
