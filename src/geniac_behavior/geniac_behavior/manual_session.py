"""Replayable manual inputs evaluated by the production Classifier, without ROS."""
from dataclasses import asdict
import json
import math
from pathlib import Path
from .core import Classifier, Settings, LABELS

MAX_FRAMES = 10000


class ManualSession:
    def __init__(self, interval=.25, settings=None):
        if not isinstance(interval, (int, float)) or not math.isfinite(interval) or not .05 <= interval <= 5:
            raise ValueError('フレーム間隔は0.05〜5秒で指定してください')
        self.interval = float(interval)
        self.settings = settings or Settings()
        self.frames = []
        self.results = []
        self.pending_baseline = False
        self._reset_classifier()

    def _reset_classifier(self):
        self.classifier = Classifier(self.settings)
        self.classifier.begin('manual:1', 1.)

    def _evaluate(self, frame, index):
        stamp = 1. + index * self.interval
        if frame.get('baseline_reset'):
            self.classifier.begin('manual:' + str(index+2), stamp)
        position = frame['position']
        self.classifier.update({
            'version': 1, 'stamp': stamp, 'frame_id': 'livox_frame',
            'stream_id': 'manual', 'valid': True,
            'tracks': [] if position is None else [{'track_id': 1, 'center': [*position, 0.]}],
        })
        report = self.classifier.report(stamp)
        target = next(iter(report['targets']), {})
        label = report['state']
        expected = frame['expected']
        return {'frame': index + 1, 'elapsed': index * self.interval,
                'label': label, 'expected': expected,
                'passed': None if expected is None else expected == label,
                'metrics': target}

    def append(self, position, expected=None, baseline_reset=False):
        if len(self.frames) >= MAX_FRAMES:
            raise ValueError('最大10000フレームです。保存してリセットしてください')
        if expected is not None and expected not in LABELS:
            raise ValueError('未知の期待ラベルです')
        if position is not None:
            if not isinstance(position, (list, tuple)) or len(position) != 2:
                raise ValueError('位置は[x, y]で指定してください')
            if not all(type(v) in (int, float) and math.isfinite(v) for v in position):
                raise ValueError('座標は有限の数値で指定してください')
            x, y = map(float, position)
            if not 0 <= x <= 50 or not -30 <= y <= 30:
                raise ValueError('座標はx=0〜50m、y=-30〜30mの範囲です')
            position = [x, y]
        frame = {'position': position, 'expected': expected, 'baseline_reset': bool(baseline_reset or self.pending_baseline)}
        result = self._evaluate(frame, len(self.frames))
        self.pending_baseline = False
        self.frames.append(frame)
        self.results.append(result)
        return result

    @property
    def last_position(self):
        return next((f['position'] for f in reversed(self.frames) if f['position'] is not None), None)

    def undo(self):
        if not self.frames:
            return
        frames = self.frames[:-1]
        self.frames = []
        self.results = []
        self.pending_baseline = False
        self._reset_classifier()
        for frame in frames:
            self.append(frame['position'], frame['expected'], frame.get('baseline_reset', False))

    def summary(self):
        checked = [r for r in self.results if r['passed'] is not None]
        return {'frames': len(self.frames), 'checked': len(checked),
                'passed': sum(r['passed'] for r in checked),
                'failed': sum(not r['passed'] for r in checked)}

    def save(self, path):
        payload = {'format': 'geniac_behavior_manual', 'version': 1,
                   'interval': self.interval, 'settings': asdict(self.settings),
                   'frames': self.frames, 'results': self.results, 'summary': self.summary()}
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('テストファイルが大きすぎます')
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get('format') != 'geniac_behavior_manual' or data.get('version') != 1:
            raise ValueError('未対応の手動テストファイルです')
        frames = data.get('frames')
        if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
            raise ValueError('フレーム一覧が不正です')
        settings = dict(data['settings'])
        # Legacy saved cases keep their inputs; obsolete distance gates no longer apply.
        for key in ('escape_radius', 'escape_gain', 'retreat_gain'):settings.pop(key, None)
        session = cls(data['interval'], Settings(**settings))
        for frame in frames:
            expected = frame.get('expected')
            if expected == 'absent':expected = 'escaped'  # migrate saved pre-merge cases
            session.append(frame['position'], expected, frame.get('baseline_reset', False))
        # Stored results are informational: always recompute with the current classifier.
        return session


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='保存済みクリック入力を行動分類器で再評価する')
    parser.add_argument('case', help='手動テストGUIで保存したJSON')
    args = parser.parse_args(argv)
    session = ManualSession.load(args.case)
    print(json.dumps(session.summary(), ensure_ascii=False))
    return 1 if session.summary()['failed'] else 0
