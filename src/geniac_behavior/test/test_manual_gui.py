"""Offscreen mouse input tests; no ROS graph or display server needed."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt5 import QtCore,QtWidgets,QtTest
from geniac_behavior.manual_gui import ManualWindow


def test_click_advances_once_repeat_missing_and_history(tmp_path):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window=ManualWindow();window.show();app.processEvents()
    try:
        assert '完全退避' in window.result.text()
        assert window.expected.findData('absent') == -1
        pixel=window.canvas.to_screen(10,0).toPoint()
        QtTest.QTest.mouseClick(window.canvas,QtCore.Qt.LeftButton,pos=pixel)
        assert len(window.session.frames)==1
        assert abs(window.session.frames[0]['position'][0]-10)<.15
        assert not window.interval.isEnabled()
        for _ in range(16):window.repeat()
        assert window.session.results[-1]['label']=='no_escape'
        window.expected.setCurrentIndex(window.expected.findData('observing'))
        window.add_position(None)
        assert window.session.results[-1]['passed'] is True
        window.table.selectRow(0);app.processEvents()
        assert window.selected==0 and 'observing' in window.result.text()
        window.undo();assert window.session.results[-1]['label']=='no_escape'
        count=len(window.session.frames)
        QtTest.QTest.mouseClick(window.canvas,QtCore.Qt.LeftButton,pos=QtCore.QPoint(1,1))
        assert len(window.session.frames)==count
        window.hold();assert len(window.session.frames)==count+8
        assert window.grab().save(str(tmp_path/'manual-test.png'))
    finally:window.close();app.processEvents()
