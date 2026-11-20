from PyQt5 import QtWidgets
from geniac_visualizer.stock_panel import StockPanel


def test_progress_counts_billing_and_stale_display():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    p=StockPanel()
    p.show_status({'status':'acquiring','ready_count':1,'reserve_count':4,'target_count':3,
                   'sequence':32,'completed':2,'total':7,'item':'無線の話し声','source_host':'k5'},True)
    assert '未使用 1/3件' in p.summary.text() and '再使用可能 4件' in p.summary.text()
    assert 'k5' in p.summary.text() and 'No.0032' in p.detail.text()
    assert p.progress.value()==2 and p.progress.maximum()==7
    p.show_status({'status':'refill_failed','ready_count':0,'reserve_count':2,'billing_blocked':True},True)
    assert '予備で再生可能' in p.summary.text() and '課金の許可待ち' in p.summary.text()
    p.show_status({},False)
    assert '通信待ち' in p.summary.text() and p.progress.format()=='状態不明'
    p.close()
