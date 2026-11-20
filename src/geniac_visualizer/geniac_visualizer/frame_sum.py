"""Rolling additive exposure, bounded in memory and using actual distinct frames."""
from collections import deque
import cv2
import numpy as np


def luminance(image):
    return float(cv2.cvtColor(np.clip(image,0,255).astype(np.uint8),cv2.COLOR_BGR2GRAY).mean())


class FrameSum:
    def __init__(self,target=80.,max_frames=64):
        if not 0<target<255 or not 1<=max_frames<=128:raise ValueError('Invalid frame sum limits')
        self.target=target;self.max_frames=max_frames;self.reset()
    def reset(self):
        self.frames=deque();self.total=None;self.level=0.
    def apply(self,image,enabled):
        if not enabled or luminance(image)>=self.target:
            self.reset();return image
        if self.total is None or self.total.shape!=image.shape:
            self.reset();self.total=np.zeros(image.shape,dtype=np.float32)
        self.frames.append(image.copy());self.total+=image
        while len(self.frames)>self.max_frames:
            self.total-=self.frames.popleft()
        # Keep only the newest frames necessary to reach the target.
        while len(self.frames)>1:
            candidate=self.total-self.frames[0]
            if luminance(candidate)<self.target:break
            self.total=candidate;self.frames.popleft()
        # Fractional contribution prevents a whole-frame jump past the target.
        gain=1.
        if luminance(self.total)>self.target:
            low,high=0.,1.
            for _ in range(12):
                mid=(low+high)/2
                if luminance(self.total*mid)<self.target:low=mid
                else:high=mid
            gain=high
        output=np.clip(self.total*gain,0,255).astype(np.uint8)
        self.level=luminance(output)
        return output
