from types import SimpleNamespace as NS
from geniac_scenario.node import ScenarioNode


def test_playback_claims_exact_preview_not_another_stock_entry():
    calls=[];published=[]
    history=NS(claim=lambda sid,**kw:calls.append((sid,kw)) or True)
    tree={'story':{'id':'displayed','sequence':42},'nodes':{}}
    n=NS(preview=(tree,{'a':'audio.wav'}),history=history,dry_run=False,test_mode=False,
         tree_pub=NS(publish=published.append))
    assert ScenarioNode.select_stock(n) is tree
    assert calls==[('displayed',{})] and n.preview is None
    assert n.paths=={'a':'audio.wav'} and len(published)==1


def test_unavailable_preview_does_not_silently_play_another_story():
    n=NS(preview=({'story':{'id':'removed'}},{}),history=NS(claim=lambda *a,**kw:False),dry_run=False,test_mode=False)
    assert ScenarioNode.select_stock(n) is None
    assert n.preview is None


def test_pending_preview_is_published_without_claiming():
    tree={'story':{'sequence':42}};published=[]
    n=NS(stock=True,campaign=NS(active=False,paused=False),core=NS(running=False),prepared_tree=None,
         preview=None,preview_future=NS(done=lambda:True,result=lambda:(tree,{})),
         tree_pub=NS(publish=published.append))
    ScenarioNode.refresh_preview(n)
    assert n.preview[0] is tree and n.preview_future is None and len(published)==1
