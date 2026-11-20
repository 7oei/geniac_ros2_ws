import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import pytest
from PyQt5 import QtWidgets,QtCore,QtTest
from geniac_scenario.manual_gui import ManualWindow
from geniac_scenario.manual_session import CheckpointSession
from geniac_scenario.tree import load_tree

TREE=Path(__file__).parents[1]/'config/story_tree.yaml'

@pytest.mark.parametrize('label,destination',[('escaped','escaped_end'),('retreated_nearby','watch'),('no_escape','search')])
def test_graph_plays_then_waits_for_answer(label,destination):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=ManualWindow(TREE);w.show();app.processEvents()
    try:
        w.start();w.timer.stop()
        assert w.engine.node_id=='arrival' and w.session.phase=='playing'
        assert not w.answer_box.isEnabled() and w.graph.current=='arrival'
        w.answer([label]);assert w.engine.node_id=='arrival'  # input ignored during playback
        w.advance_seconds(7.9);assert w.session.phase=='playing'
        w.advance_seconds(.1);assert w.session.phase=='checkpoint' and w.answer_box.isEnabled()
        now=w.now;w.advance_seconds(100);assert w.now==now
        QtTest.QTest.mouseClick(w.answer_buttons[label],QtCore.Qt.LeftButton)
        w.timer.stop()
        assert w.engine.node_id==destination and w.graph.current==destination
        assert w.session.phase==('finished' if label=='escaped' else 'playing') and not w.answer_box.isEnabled()
        assert set(w.graph.nodes)<=set(w.tree['nodes']) and w.graph.edges
        w.stop();assert w.session.phase=='stopped'
    finally:w.close()


def test_multiple_deer_requires_each_response():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=ManualWindow(TREE)
    try:
        w.count.setValue(2);w.start();w.timer.stop();w.advance_seconds(8)
        assert not w.submit.isEnabled()
        w.inputs[0][1].setCurrentIndex(w.inputs[0][1].findData('escaped'))
        assert not w.submit.isEnabled()
        w.inputs[1][1].setCurrentIndex(w.inputs[1][1].findData('no_escape'))
        assert w.submit.isEnabled()
        w.submit_multiple();w.timer.stop();assert w.engine.node_id=='search'
    finally:w.close()


def test_checkpoint_thinking_time_excluded_and_repeat():
    results=[];s=CheckpointSession(load_tree(TREE),results.append);s.start()
    for duration in (8,8,8,6,2):
        s.elapse(duration);before=s.now;s.elapse(600);assert s.now==before
        s.answer(['no_escape'])
    assert s.core.node_id=='attack' and s.campaign.round==1
    assert not results
    s.elapse(2);s.answer(['no_escape'])
    assert s.core.node_id=='attack' and s.phase=='playing'
    s.elapse(2);s.answer(['escaped'])
    assert results[-1]['escape_seconds']==36 and s.core.node_id=='escaped_end'
    assert s.phase=='finished' and not s.core.running


def test_graph_without_graphviz_still_works(monkeypatch):
    import geniac_scenario.story_graph as graph
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def missing(*args,**kwargs):raise FileNotFoundError()
    monkeypatch.setattr(graph.subprocess,'run',missing)
    widget=graph.StoryGraph();widget.set_tree(load_tree(TREE))
    assert widget.nodes and widget.edges
    widget.close()

def test_audio_stops_at_checkpoint_and_resumes_only_after_answer():
    from unittest.mock import Mock
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=ManualWindow(TREE)
    try:
        player=Mock();player.failed.return_value=False;w.player=player
        w.start();w.timer.stop();before=player.stop.call_count
        w.advance_seconds(7);assert player.stop.call_count==before
        w.advance_seconds(1);assert player.stop.call_count==before+1
        plays=player.play.call_count
        w.advance_seconds(20);assert player.play.call_count==plays and w.now==8
        w.answer(['no_escape']);w.timer.stop();assert player.play.call_count==plays+1
    finally:w.close()


def test_final_repeat_waits_for_each_answer_and_unknown_stops():
    s=CheckpointSession(load_tree(TREE));s.start()
    for duration in (8,8,8,6):
        s.elapse(duration);s.answer(['no_escape'])
    assert s.core.node_id=='attack'
    for _ in range(3):
        epoch=s.core.epoch;s.elapse(2)
        assert s.phase=='checkpoint'
        now=s.now;s.elapse(100)
        assert s.now==now and s.core.epoch==epoch
        s.answer(['no_escape'])
        assert s.core.node_id=='attack' and s.core.epoch!=epoch
    s.elapse(2);s.answer(['unknown'])
    assert s.phase=='finished' and not s.core.running


def test_fractional_scene_boundary_accepts_response_without_roundoff_stall():
    tree=load_tree(TREE)
    for key,node in tree['nodes'].items():
        if not node.get('terminal'):
            node['duration']=node['min_dwell']=.4 if key==tree['root'] else .1
    session=CheckpointSession(tree);session.start()
    for _ in range(25):
        session.elapse(session.boundary+1)
        assert session.phase=='checkpoint'
        session.answer(['no_escape'])
        assert session.phase=='playing'
    assert session.core.reason=='repeat_final_no_escape'
    session.elapse(session.boundary+1);session.answer(['unknown'])
    assert session.phase=='finished'


def test_gui_consumes_at_final_checkpoint_while_repeat_remains_available(tmp_path):
    from geniac_scenario.history import History
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=ManualWindow(TREE);w.history=History(tmp_path)
    try:
        sid=w.history.draft(w.tree,{'date':'2026-11-20','surface':'grass'})
        w.history.publish(sid,TREE,w.tree)
        w.start();w.timer.stop()
        for _ in range(4):
            w.advance_seconds(w.session.boundary+1);w.answer(['no_escape']);w.timer.stop()
        assert w.engine.node_id=='attack'
        assert w.history.rows()[0]['status']=='ready'
        w.advance_seconds(w.session.boundary+1)
        assert w.history.rows()[0]['status']=='used'
        w.answer(['no_escape']);w.timer.stop()
        assert w.engine.node_id=='attack' and w.session.phase=='playing'
        assert w.history.context()['field_trials']==0
    finally:w.close()


def test_number_and_refill_status_are_visible(tmp_path,monkeypatch):
    import json
    import geniac_scenario.manual_gui as gui
    from geniac_scenario.history import History
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=ManualWindow(TREE)
    try:
        w.history=History(tmp_path)
        w.tree.setdefault('story',{})['sequence']=42
        w.refresh();assert 'No.0042' in w.title.text()
        class FakeStock:
            def __init__(self,root):pass
            def ready(self,status='ready'):return [] if status=='ready' else ['reserve']
        monkeypatch.setattr(gui,'Stock',FakeStock)
        (tmp_path/'status.json').write_text(json.dumps({'status':'acquiring','target_count':3,'sequence':43,'completed':2,'total':7,'item':'草を走る音'}))
        w.refresh_stock()
        assert '音源の検索・検証中' in w.stock_status.text()
        assert 'No.0043' in w.stock_status.text() and '草を走る音' in w.stock_status.text()
        assert w.refill_progress.maximum()==7 and w.refill_progress.value()==2
        assert '未使用 0/3件' in w.stock_status.text()
        assert '新作の補充待ち' in w.stock_status.text()
        (tmp_path/'status.json').write_text(json.dumps({'status':'refill_failed'}))
        w.refresh_stock();assert '補充失敗・再試行へ' in w.stock_status.text()
    finally:w.close()


def test_billing_notice_requires_explicit_button_permission(tmp_path):
    from geniac_scenario.billing import block,state,BillingRequired
    from geniac_scenario.history import History
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=ManualWindow(TREE);w.history=History(tmp_path)
    try:
        block(tmp_path,BillingRequired())
        w.refresh_stock()
        assert not w.billing_button.isHidden()
        assert '追加の課金' in w.billing_notice.text()
        assert state(tmp_path)['blocked']
        w.billing_button.click()
        assert not state(tmp_path)['blocked'] and w.billing_button.isHidden()
    finally:w.close()


def test_final_scene_repeats_for_deer_moving_but_visible():
    from geniac_scenario.evolving import route_visible_to_attack
    tree=load_tree(TREE)
    tree['needs']['attack']['event']='attack'
    tree=route_visible_to_attack(tree)
    s=CheckpointSession(tree);s.start()
    for _ in range(8):
        s.elapse(s.boundary+1);s.answer(['retreated_nearby'])
    assert s.core.node_id=='attack' and s.core.reason=='repeat_final_retreated_nearby'
    s.elapse(s.boundary+1);s.answer(['escaped'])
    assert s.core.node_id=='escaped_end'


@pytest.mark.parametrize('fallback',[False,True])
def test_final_attack_graph_shows_runtime_self_loop(monkeypatch,fallback):
    from geniac_visualizer.story_graph import StoryGraph
    from geniac_scenario.tree import Engine
    if fallback:
        import geniac_visualizer.story_graph as graph_module
        def missing(*args,**kwargs):raise FileNotFoundError()
        monkeypatch.setattr(graph_module.subprocess,'run',missing)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tree=Engine(load_tree(TREE)).tree
    graph=StoryGraph();graph.set_tree(tree)
    try:
        assert ('attack','attack') in graph.edges
        assert ('attack','retry_end') not in graph.edges
        assert 'retry_end' not in graph.nodes
        assert ('attack','escaped_end') in graph.edges
        assert ('attack','uncertain_end') in graph.edges
        graph.update_state('attack',False,[{'node':'attack'},{'node':'attack'}])
        item,_=graph.edges['attack','attack']
        assert item.pen().widthF()==4
        assert item.path().boundingRect().width()>0
        assert tree['nodes']['attack']['branches']['no_escape']=='retry_end'
    finally:graph.close()


def test_graph_reflows_to_aspect_ratio_preserving_playback_state():
    from geniac_visualizer.story_graph import StoryGraph
    from geniac_scenario.tree import Engine
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    graph=StoryGraph();graph.resize(400,1200);graph.show();app.processEvents()
    graph.set_tree(Engine(load_tree(TREE)).tree)
    graph.update_state('attack',True,[{'node':'attack'},{'node':'attack'}])
    graph.nodes['attack'].set_caption('行動の確定待ち（自動）')
    try:
        assert graph.layout_direction=='TB'
        graph.resize(1600,350)
        QtTest.QTest.qWait(300);app.processEvents()
        assert graph.layout_direction=='LR'
        assert graph.current=='attack'
        assert '行動の確定待ち（自動）' in graph.nodes['attack'].text.toPlainText()
        assert graph.edges['attack','attack'][0].pen().widthF()==4
        assert len(graph._layouts)==4
        graph.resize(400,1200)
        QtTest.QTest.qWait(300);app.processEvents()
        assert graph.layout_direction=='TB'
    finally:graph.close()
