"""ROS-independent inference, temporal confirmation, and bounded input mailbox."""
from dataclasses import dataclass
from threading import Lock
import math
import re

from .core.classifier import Forest, FEATURE_NAMES
from .core.detector import Config, candidates
from .core.tracking import Tracker


@dataclass(frozen=True)
class Settings:
    min_score: float = 0.8
    confirm_score: float = 0.8
    publish_tentative: bool = False
    min_ground_quality: float = 0.35
    max_range: float = 45.0
    tf_prefix: str = 'deer_'
    max_speed_mps: float = 10.0
    position_tolerance_m: float = 0.2

    def __post_init__(self):
        for key in ('min_score', 'confirm_score', 'min_ground_quality'):
            if not 0 <= getattr(self, key) <= 1:
                raise ValueError(key + ' must be in [0, 1]')
        if not math.isfinite(self.max_range) or not 1 < self.max_range <= 100:
            raise ValueError('max_range must be finite and in (1, 100]')
        if not math.isfinite(self.max_speed_mps) or self.max_speed_mps<=0:raise ValueError('max_speed_mps must be positive and finite')
        if not math.isfinite(self.position_tolerance_m) or self.position_tolerance_m<0:raise ValueError('position_tolerance_m must be nonnegative and finite')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_/]*', self.tf_prefix):
            raise ValueError('tf_prefix must start with a letter, without spaces or leading slash')


class Engine:
    def __init__(self, model_path, settings=None):
        self.settings = settings or Settings()
        self.model = Forest(model_path)
        if self.model.model['features'] != FEATURE_NAMES:
            raise ValueError('This runtime requires the validated base11 model')
        self.tracker = Tracker(confirm_score=self.settings.confirm_score,max_speed_mps=self.settings.max_speed_mps,position_tolerance_m=self.settings.position_tolerance_m)
        self.cfg = Config(ground='plane', max_range=self.settings.max_range,
                          eps=.3, min_height=.35, min_points=12)

    def reset(self):
        # IDs are never reused within one process, including bag loops/frame changes.
        next_id = self.tracker.next_id
        self.tracker = Tracker(confirm_score=self.settings.confirm_score,max_speed_mps=self.settings.max_speed_mps,position_tolerance_m=self.settings.position_tolerance_m)
        self.tracker.next_id = next_id

    def process(self, points, stamp_ns):
        clusters, meta = candidates(points, self.cfg)
        scores = self.model.predict([c['features'] for c in clusters])
        observations = []
        for c, score in zip(clusters, scores):
            if score >= self.settings.min_score:
                observations.append(dict(c, score=float(score)))
        tracks, motion = self.tracker.update(
            observations, points, stamp_ns / 1e9, meta['ground_quality'])
        selected = [t for t in tracks if meta['ground_quality'] >= self.settings.min_ground_quality
                    and (self.settings.publish_tentative or t['state'] == 'observed_candidate')]
        for t in selected:
            t['child_frame_id'] = self.settings.tf_prefix + str(t['track_id'])
        return selected, dict(meta, motion=motion, candidates=len(clusters),
                              scored_candidates=len(observations))


class LatestCloud:
    """One pending message; generations invalidate work across stream discontinuities."""
    def __init__(self):
        self.lock = Lock()
        self.pending = None
        self.epoch = 0
        self.last_key = None
        self.last_received = None
        self.replaced = 0

    def put(self, msg, received):
        key = (msg.header.frame_id, stamp_ns(msg.header.stamp))
        with self.lock:
            if self.last_key is not None and (key[0] != self.last_key[0] or key[1] <= self.last_key[1]):
                self.epoch += 1
            if self.pending is not None:
                self.replaced += 1
            self.last_key = key
            self.last_received = received
            self.pending = (msg, received, self.epoch)

    def take(self):
        with self.lock:
            result, self.pending = self.pending, None
            return result

    def invalidate_locked(self):
        self.pending = None
        self.epoch += 1
        self.last_key = None


def stamp_ns(stamp):
    return int(stamp.sec) * 1000000000 + int(stamp.nanosec)


def timestamp_error(stamp, now, max_age_s, max_future_s):
    if stamp <= 0 or now <= 0:
        return 'clock_not_ready_or_zero_stamp'
    age = (now - stamp) / 1e9
    if age > max_age_s:
        return 'stale_cloud'
    if age < -max_future_s:
        return 'future_cloud_check_clock_sync'
    return None
