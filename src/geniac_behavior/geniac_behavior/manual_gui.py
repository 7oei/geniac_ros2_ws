"""Click-to-frame manual unit-test UI. No ROS graph, audio, or network operations."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
from PyQt5 import QtCore, QtGui, QtWidgets
from .core import Settings
from .manual_session import ManualSession

NAMES = {'escaped': '完全退避', 'retreated_nearby': '移動・視界内',
         'no_escape': '動かなかった', 'observing': '観測中', 'unknown': '判定不明'}
COLORS = {'escaped': '#319d69', 'retreated_nearby': '#d5aa3c', 'no_escape': '#ed785e',
          'observing': '#58b1d5', 'unknown': '#9eabb6'}


class PositionCanvas(QtWidgets.QWidget):
    position_clicked = QtCore.pyqtSignal(float, float)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setMinimumSize(540, 420)
        self.setMouseTracking(True)
        self.hover = None

    def geometry_values(self):
        scale = min((self.width()-90)/60, (self.height()-80)/50)
        return scale, QtCore.QPointF(self.width()/2, self.height()-45)

    def to_screen(self, x, y):
        scale, origin = self.geometry_values()
        return QtCore.QPointF(origin.x()-y*scale, origin.y()-x*scale)

    def from_screen(self, point):
        scale, origin = self.geometry_values()
        x, y = (origin.y()-point.y())/scale, (origin.x()-point.x())/scale
        return (x, y) if 0 <= x <= 50 and -30 <= y <= 30 else None

    def mousePressEvent(self, event):
        pos = self.from_screen(event.localPos())
        if event.button() == QtCore.Qt.LeftButton and pos:
            self.position_clicked.emit(*pos)

    def mouseMoveEvent(self, event):
        self.hover = self.from_screen(event.localPos())
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor('#111f2a'))
        scale, origin = self.geometry_values()
        for x in range(0, 51, 5):
            p.setPen(QtGui.QPen(QtGui.QColor('#2c414e'), 1))
            p.drawLine(self.to_screen(x, -30), self.to_screen(x, 30))
            p.setPen(QtGui.QColor('#a1b6c5'))
            p.drawText(self.to_screen(x, 30)+QtCore.QPointF(-34, 4), str(x))
        for y in range(-30, 31, 5):
            p.setPen(QtGui.QPen(QtGui.QColor('#2c414e'), 1))
            p.drawLine(self.to_screen(0, y), self.to_screen(50, y))
            p.setPen(QtGui.QColor('#a1b6c5'))
            p.drawText(self.to_screen(0, y)+QtCore.QPointF(-9, 18), str(y))
        p.save()
        p.setClipRect(QtCore.QRectF(self.to_screen(50, 30), self.to_screen(0, -30)))
        visible = self.window.selected + 1
        frames = self.window.session.frames[:visible]
        positions = [f['position'] for f in frames if f['position'] is not None]
        if positions:
            base = positions[0]
            p.setPen(QtGui.QPen(QtGui.QColor('#b6a5df'), 1, QtCore.Qt.DashLine))
            p.drawEllipse(self.to_screen(*base), self.window.session.settings.stationary_radius*scale,
                          self.window.session.settings.stationary_radius*scale)
        previous = None
        for i, frame in enumerate(frames):
            if frame['position'] is None:
                previous = None
                continue
            point = self.to_screen(*frame['position'])
            p.setPen(QtGui.QPen(QtGui.QColor('#6f9cac'), 2))
            if previous is not None:
                p.drawLine(previous, point)
            p.setBrush(QtGui.QColor(COLORS[self.window.session.results[i]['label']]))
            p.drawEllipse(point, 3, 3)
            previous = point
        if positions:
            p.setPen(QtGui.QColor('#ffffff'))
            p.drawText(self.to_screen(*positions[0])+QtCore.QPointF(9, 17), '開始位置')
        if frames and frames[-1]['position'] is not None:
            point = self.to_screen(*frames[-1]['position'])
            p.setPen(QtGui.QPen(QtGui.QColor('#ffffff'), 2));p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(point, 8, 8)
            p.drawText(point+QtCore.QPointF(12, -9), f'フレーム {visible}')
        p.restore()
        p.setPen(QtGui.QColor('#d8e5ec'));p.setBrush(QtGui.QColor('#d8e5ec'))
        p.drawEllipse(origin, 5, 5)
        p.drawText(origin+QtCore.QPointF(8, -9), 'LiDAR / スピーカー')
        p.drawText(12, 20, 'クリック = 鹿1頭の位置を1フレーム追加（単位 m）')
        p.drawText(12, 40, '上: x前方 / 左: y正方向。線の切れ目は未検出フレーム。')
        if self.hover:
            p.drawText(12, self.height()-9, f'x={self.hover[0]:.2f}m  y={self.hover[1]:.2f}m')


class ManualWindow(QtWidgets.QMainWindow):
    def __init__(self, session=None):
        super().__init__()
        self.session = session or ManualSession()
        self.selected = len(self.session.frames)-1
        self.setWindowTitle('GENIAC 行動分析 — クリック入力の手動単体テスト')
        self.resize(1320, 860)
        root = QtWidgets.QWidget();self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        note = QtWidgets.QLabel('1クリックで1フレーム進みます。クリックを待つ実時間は判定に影響しません。実際のClassifierを使用します。')
        layout.addWidget(note)
        controls = QtWidgets.QHBoxLayout();layout.addLayout(controls)
        controls.addWidget(QtWidgets.QLabel('1フレーム'))
        self.interval = QtWidgets.QDoubleSpinBox();self.interval.setRange(.05, 5);self.interval.setSingleStep(.05)
        self.interval.setSuffix(' 秒');self.interval.setValue(self.session.interval)
        self.interval.valueChanged.connect(self.interval_changed);controls.addWidget(self.interval)
        controls.addWidget(QtWidgets.QLabel('次に入力するフレームの期待判定'))
        self.expected = QtWidgets.QComboBox();self.expected.addItem('指定しない', None)
        for label, name in NAMES.items():self.expected.addItem(name, label)
        controls.addWidget(self.expected);controls.addStretch()
        self.button(controls, 'シナリオ開始（次のフレームで基準更新）', self.begin_scenario)
        actions = QtWidgets.QHBoxLayout();layout.addLayout(actions)
        self.repeat_button = self.button(actions, '同じ位置で1フレーム', self.repeat)
        self.repeat_count = QtWidgets.QSpinBox();self.repeat_count.setRange(1, 200);self.repeat_count.setValue(8)
        actions.addWidget(self.repeat_count)
        self.hold_button = self.button(actions, '同じ位置で指定フレーム追加', self.hold)
        self.button(actions, '未検出を1フレーム', lambda:self.add_position(None))
        self.undo_button = self.button(actions, '1フレーム戻す', self.undo)
        self.button(actions, 'リセット', self.reset)
        self.button(actions, 'JSON保存', self.save_case)
        self.button(actions, 'JSON読込・再評価', self.load_case)
        split = QtWidgets.QSplitter();layout.addWidget(split, 1)
        self.canvas = PositionCanvas(self);split.addWidget(self.canvas)
        self.canvas.position_clicked.connect(lambda x,y:self.add_position([x,y]))
        side = QtWidgets.QWidget();right = QtWidgets.QVBoxLayout(side);split.addWidget(side)
        self.result = QtWidgets.QLabel();self.result.setWordWrap(True);self.result.setMinimumHeight(65)
        right.addWidget(self.result)
        self.metrics = QtWidgets.QLabel();self.metrics.setWordWrap(True);right.addWidget(self.metrics)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['frame','時間[s]','x / y [m]','判定','期待','結果'])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self.select_row)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        right.addWidget(self.table, 1)
        self.summary = QtWidgets.QLabel();right.addWidget(self.summary)
        help_text = QtWidgets.QLabel('例: 初期・未検出が続く → 完全退避\n10mで4秒停止 → 動かなかった\n位置を0.75m超変更 → 移動・視界内\n観測後に未検出 → 観測中（退避確認待ち）\n未検出が5秒連続 → 完全退避\n同じ位置を繰り返し入力して停止時間を作れます。\n期待判定を指定するとPASS/FAILが記録されます。')
        help_text.setWordWrap(True);right.addWidget(help_text)
        split.setSizes([680, 620])
        self.thresholds = QtWidgets.QLabel();self.thresholds.setWordWrap(True);layout.addWidget(self.thresholds)
        self.statusBar().showMessage('初期位置をクリックしてください。ROS・音声・Discordへの接続は行いません。')
        self.refresh()

    @staticmethod
    def button(row, title, callback):
        button = QtWidgets.QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        return button

    def interval_changed(self, value):
        if not self.session.frames:
            self.session = ManualSession(value, self.session.settings)
            self.refresh()

    def add_position(self, position):
        try:self.session.append(position, self.expected.currentData())
        except ValueError as exc:
            self.statusBar().showMessage(str(exc));return
        self.refresh()

    def begin_scenario(self):
        self.session.pending_baseline = True
        self.statusBar().showMessage('次の入力時刻をシナリオ開始として、直前に見えていた位置を基準に再評価します。')

    def repeat(self):
        if self.session.last_position is not None:self.add_position(self.session.last_position)

    def hold(self):
        pos = self.session.last_position
        if pos is None:return
        try:
            for _ in range(self.repeat_count.value()):self.session.append(pos, self.expected.currentData())
        except ValueError as exc:self.statusBar().showMessage(str(exc))
        self.refresh()

    def undo(self):
        self.session.undo();self.refresh()

    def reset(self):
        if self.session.frames and QtWidgets.QMessageBox.question(self, 'リセット', '未保存の入力を消して最初から始めますか？') != QtWidgets.QMessageBox.Yes:return
        self.session = ManualSession(self.interval.value(), self.session.settings);self.refresh()

    def refresh(self):
        self.interval.blockSignals(True);self.interval.setValue(self.session.interval);self.interval.blockSignals(False)
        self.interval.setEnabled(not self.session.frames)
        self.repeat_button.setEnabled(self.session.last_position is not None)
        self.hold_button.setEnabled(self.session.last_position is not None)
        self.undo_button.setEnabled(bool(self.session.frames))
        self.table.blockSignals(True);self.table.setRowCount(len(self.session.frames))
        for i,(frame,result) in enumerate(zip(self.session.frames,self.session.results)):
            pos = frame['position'];passed = result['passed']
            values = [str(i+1), f"{result['elapsed']:.2f}", '未検出' if pos is None else f'{pos[0]:.2f} / {pos[1]:.2f}',
                      NAMES[result['label']], NAMES.get(result['expected'],'—'), '—' if passed is None else ('PASS' if passed else 'FAIL')]
            for col,value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if col==5 and passed is not None:item.setForeground(QtGui.QColor('#23864b' if passed else '#c93434'))
                self.table.setItem(i,col,item)
        self.selected = len(self.session.frames)-1
        if self.selected>=0:self.table.selectRow(self.selected);self.table.scrollToBottom()
        self.table.blockSignals(False)
        totals = self.session.summary()
        self.summary.setText(f"{totals['frames']}フレーム / 期待値あり {totals['checked']} / PASS {totals['passed']} / FAIL {totals['failed']}")
        s = self.session.settings
        self.thresholds.setText(f'判定設定: 未検出が{s.missing_seconds:g}秒連続→完全退避 / 移動 {s.stationary_radius:g}m超→移動・視界内 / '
            f'動かなかった: 観測 {s.observation_seconds:g}秒、停止維持 {s.settle_seconds:g}秒、速度 {s.stop_speed:g}m/s以下 / 通信途絶 {s.stale_seconds:g}秒')
        self.show_result()

    def select_row(self):
        self.selected = self.table.currentRow();self.show_result()

    def show_result(self):
        self.canvas.update()
        if self.selected<0:
            self.result.setText('完全退避（入力待ち）');self.metrics.setText('最初のクリック位置が判定の基準位置になります。');return
        r = self.session.results[self.selected];m = r['metrics']
        self.result.setText(f"フレーム {r['frame']} / 経過 {r['elapsed']:.2f}秒\n{NAMES[r['label']]} ({r['label']})")
        self.result.setStyleSheet(f"font-size:20px; font-weight:bold; color:{COLORS[r['label']]}")
        def value(key):return f'{m[key]:.2f}' if key in m else '—'
        self.metrics.setText(f"LiDARからの距離: {value('range_m')} m\n開始時より遠ざかった距離: {value('radial_gain_m')} m\n"
            f"連続未検出: {value('missing_elapsed_seconds')} 秒\n"
            f"開始位置からの変位: {value('displacement_m')} m\n停止判定に用いた速度: {value('speed_mps')} m/s\n"
            '未検出時の距離は直近観測値。未検出確認中は観測中、5秒連続で完全退避です。')

    def save_case(self):
        path,_ = QtWidgets.QFileDialog.getSaveFileName(self, 'テスト入力と結果を保存', str(Path.home()/'geniac_behavior_case.json'), 'JSON (*.json)')
        if not path:return
        try:self.session.save(path);self.statusBar().showMessage('保存しました: '+path)
        except OSError as exc:QtWidgets.QMessageBox.warning(self,'保存失敗',str(exc))

    def load_case(self):
        path,_ = QtWidgets.QFileDialog.getOpenFileName(self, '保存した入力を再評価', str(Path.home()), 'JSON (*.json)')
        if not path:return
        try:session = ManualSession.load(path)
        except (ValueError,TypeError,KeyError,OSError) as exc:
            QtWidgets.QMessageBox.warning(self,'読み込み失敗',str(exc));return
        if self.session.frames and QtWidgets.QMessageBox.question(self, '入力の置換', '現在の未保存入力を置き換えますか？') != QtWidgets.QMessageBox.Yes:return
        self.session = session;self.refresh();self.statusBar().showMessage('現在の分類器で再評価しました: '+path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', help='保存済み手動入力JSONを開く')
    parser.add_argument('--config', help='behavior.yamlで判定閾値を指定（新規入力時）')
    args = parser.parse_args(argv)
    if args.case and args.config:parser.error('--caseと--configは同時指定できません')
    settings = Settings()
    if args.config:
        import yaml
        config = yaml.safe_load(Path(args.config).read_text())
        params = dict(config['geniac_behavior']['ros__parameters'])
        for key in ('escape_radius', 'escape_gain', 'retreat_gain'):params.pop(key, None)
        settings = Settings(**params)
    session = ManualSession.load(args.case) if args.case else ManualSession(settings=settings)
    app = QtWidgets.QApplication(sys.argv[:1]);window = ManualWindow(session);window.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
