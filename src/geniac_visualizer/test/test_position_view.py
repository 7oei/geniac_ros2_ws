from PyQt5 import QtCore,QtWidgets,QtTest
from geniac_visualizer.position_view import PositionView
from geniac_visualizer.view_model import ViewModel


def test_drag_follows_cursor_and_release_holds_position():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    view=PositionView(ViewModel(),interactive=True);view.resize(500,500);view.show();app.processEvents()
    try:
        start=view.to_screen(15,0).toPoint();target=view.to_screen(22,8).toPoint()
        QtTest.QTest.mousePress(view,QtCore.Qt.LeftButton,pos=start)
        QtTest.QTest.mouseMove(view,target)
        QtTest.QTest.mouseRelease(view,QtCore.Qt.LeftButton,pos=target)
        actual=list(view.positions[1]);assert abs(actual[0]-22)<.2 and abs(actual[1]-8)<.2
        QtTest.QTest.mouseMove(view,view.to_screen(30,-10).toPoint())
        assert view.positions[1]==actual and view.dragging is None
        assert view.tracks()[0]['center'][:2]==actual
        view.positions[1]=[45,0];assert view.tracks()==[]
        view.count=2;assert [t['track_id'] for t in view.tracks()]==[2]
    finally:view.close()


def test_lidar_sector_matches_120_degrees_and_40m_range():
    import math
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    view=PositionView(ViewModel(),interactive=True)
    assert view.detected([40,0]) and not view.detected([40.01,0])
    assert view.detected([25,25])  # outside the old rectangle but inside the sector
    for sign in (-1,1):
        assert view.detected([20,sign*20*math.sqrt(3)])
        assert view.detected([10,sign*17])
        assert not view.detected([10,sign*18])
    assert not view.detected([-1,0])
    assert not view.detected([30,30])
    view.enabled=False;assert not view.detected([10,0])
    view.close()
