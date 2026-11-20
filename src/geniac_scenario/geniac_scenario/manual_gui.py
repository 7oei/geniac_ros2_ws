"""Graph-based playback test: only reaction checkpoints ask for manual input."""
import argparse
import json
from pathlib import Path
import sys
import time
import yaml
from PyQt5 import QtCore,QtWidgets
from .tree import load_tree
from .stock import Stock,DEFAULT_STOCK
from .history import History
from .billing import state as billing_state, approve as approve_billing
from .audio import Player
from .manual_session import CheckpointSession,LABELS
from .story_graph import StoryGraph


class ManualWindow(QtWidgets.QWidget):
    def __init__(self,tree_path):
        super().__init__();self.tree_path=str(tree_path);self.tree=load_tree(tree_path)
        self.stock=Stock(DEFAULT_STOCK);self.stock.index=1
        self.player=Player(volume=80,dry_run=True);self.history=History(DEFAULT_STOCK)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.advance)
        self.setWindowTitle('GENIAC ストーリー再生・分岐テスト');self.resize(1280,900)
        self.setStyleSheet('QWidget {font-size:14px;} QPushButton {padding:8px 12px;} QGroupBox {font-weight:bold; margin-top:12px; padding-top:12px;} QProgressBar {min-height:18px;}')
        layout=QtWidgets.QVBoxLayout(self)
        self.title=QtWidgets.QLabel();self.title.setStyleSheet('font-size:21px; font-weight:bold;');layout.addWidget(self.title)
        toolbar=QtWidgets.QHBoxLayout();layout.addLayout(toolbar)
        def button(text,callback):
            b=QtWidgets.QPushButton(text);b.clicked.connect(callback);toolbar.addWidget(b);return b
        self.start_button=button('▶ 再生開始',self.start)
        self.start_button.setStyleSheet('background:#2865ba;color:white;font-weight:bold;')
        self.stop_button=button('■ 停止',self.stop)
        self.sound=QtWidgets.QCheckBox('音声を再生');toolbar.addWidget(self.sound)
        toolbar.addWidget(QtWidgets.QLabel('鹿の頭数'))
        self.count=QtWidgets.QSpinBox();self.count.setRange(1,3);toolbar.addWidget(self.count)
        toolbar.addStretch()
        self.next_button=button('次の物語',self.next_story)
        self.load_button=button('読込',self.load)
        button('結果保存',self.save)
        self.weather=QtWidgets.QLabel();self.weather.setWordWrap(True);layout.addWidget(self.weather)
        self.billing_notice=QtWidgets.QLabel();self.billing_notice.setWordWrap(True);layout.addWidget(self.billing_notice)
        self.billing_button=QtWidgets.QPushButton('追加課金を伴うAPI利用の再開を許可');self.billing_button.clicked.connect(self.allow_paid_api);layout.addWidget(self.billing_button)
        self.stock_status=QtWidgets.QLabel();self.stock_status.setWordWrap(True);layout.addWidget(self.stock_status)
        self.refill_progress=QtWidgets.QProgressBar();self.refill_progress.setRange(0,1);self.refill_progress.setValue(0);layout.addWidget(self.refill_progress)
        self.status=QtWidgets.QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress=QtWidgets.QProgressBar();self.progress.setRange(0,1000);layout.addWidget(self.progress)
        split=QtWidgets.QSplitter();layout.addWidget(split,1)
        graph_panel=QtWidgets.QWidget();graph_layout=QtWidgets.QVBoxLayout(graph_panel);graph_layout.setContentsMargins(0,0,0,0)
        nav=QtWidgets.QHBoxLayout();graph_layout.addLayout(nav)
        nav.addWidget(QtWidgets.QLabel('青：再生中　黄：回答待ち　緑：通過済み'))
        nav.addStretch()
        self.graph=StoryGraph();self.graph.selected.connect(self.inspect_node)
        for title,callback in [('全体表示',self.graph.fit_all),('現在地を拡大',self.graph.focus_current)]:
            b=QtWidgets.QPushButton(title);b.clicked.connect(callback);nav.addWidget(b)
        graph_layout.addWidget(self.graph,1)
        graph_layout.addWidget(QtWidgets.QLabel('ホイールで拡大・縮小、ドラッグで移動。場面をクリックすると右に内容を表示します。'))
        split.addWidget(graph_panel)
        side=QtWidgets.QWidget();side.setMinimumWidth(320);side.setMaximumWidth(430)
        side_layout=QtWidgets.QVBoxLayout(side)
        self.details=QtWidgets.QLabel();self.details.setWordWrap(True);self.details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        side_layout.addWidget(self.details)
        self.answer_box=QtWidgets.QGroupBox('ここで鹿の反応を入力');answers=QtWidgets.QVBoxLayout(self.answer_box)
        self.prompt=QtWidgets.QLabel('場面の再生が終わると入力できます。');self.prompt.setWordWrap(True);answers.addWidget(self.prompt)
        self.single=QtWidgets.QWidget();single_layout=QtWidgets.QVBoxLayout(self.single);single_layout.setContentsMargins(0,0,0,0)
        self.answer_buttons={}
        for label,text in LABELS.items():
            b=QtWidgets.QPushButton(text);b.clicked.connect(lambda checked=False,key=label:self.answer([key]));single_layout.addWidget(b);self.answer_buttons[label]=b
        answers.addWidget(self.single)
        self.multiple=QtWidgets.QWidget();multi_layout=QtWidgets.QVBoxLayout(self.multiple);multi_layout.setContentsMargins(0,0,0,0)
        self.inputs=[]
        for i in range(3):
            row=QtWidgets.QWidget();row_layout=QtWidgets.QHBoxLayout(row);row_layout.setContentsMargins(0,0,0,0)
            row_layout.addWidget(QtWidgets.QLabel(f'鹿 {i+1}'))
            combo=QtWidgets.QComboBox();combo.addItem('状態を選択',None)
            for key,name in LABELS.items():combo.addItem(name,key)
            combo.currentIndexChanged.connect(self.update_submit);row_layout.addWidget(combo);multi_layout.addWidget(row);self.inputs.append((row,combo))
        self.submit=QtWidgets.QPushButton('この反応で次へ');self.submit.clicked.connect(self.submit_multiple);multi_layout.addWidget(self.submit)
        answers.addWidget(self.multiple);side_layout.addWidget(self.answer_box)
        self.evaluation=QtWidgets.QLabel();self.evaluation.setWordWrap(True);side_layout.addWidget(self.evaluation)
        side_layout.addWidget(QtWidgets.QLabel('選んだ経路'))
        self.log=QtWidgets.QListWidget();self.log.setMaximumHeight(160);side_layout.addWidget(self.log)
        side_layout.addStretch();split.addWidget(side);split.setStretchFactor(0,1);split.setSizes([850,350])
        self.reset()
        self.stock_timer=QtCore.QTimer(self);self.stock_timer.timeout.connect(self.refresh_stock)
        self.stock_timer.start(2000);self.refresh_stock()
        QtCore.QTimer.singleShot(0,self.graph.fit_all)

    @property
    def engine(self):return self.session.core
    @property
    def campaign(self):return self.session.campaign
    @property
    def now(self):return self.session.now

    def allow_paid_api(self):
        approve_billing(self.history.root);self.refresh_stock()

    def refresh_stock(self):
        billing=billing_state(self.history.root);blocked=billing.get('blocked',False)
        self.billing_button.setVisible(blocked);self.billing_notice.setVisible(blocked)
        self.billing_notice.setStyleSheet('color:#b42318;font-weight:bold;')
        self.billing_notice.setText(str(billing.get('provider','API'))+'：追加の課金・残高確認が必要です。許可待ちの間は既存素材のみで補充します。\nこのボタンはAPI利用の再開許可です。入金・プラン購入は実行しません。')
        stock=Stock(self.history.root)
        ready=len(stock.ready());reserve=len(stock.ready(status='used'))
        try:data=json.loads((self.history.root/'status.json').read_text())
        except (OSError,ValueError):data={}
        target=data.get('target_count',3);state=data.get('status')
        stages={'local_unavailable':'既存素材では構成できません（天気条件・素材を確認）','local_composing':'既存素材を組み合わせ中（有料API停止）','local_ready':'既存素材モード（追加課金の許可待ち）','designing':'ストーリー生成中','acquiring':'音源の検索・検証中','compiling':'音声合成中',
                'preparation_failed':'生成失敗・再試行へ','refill_failed':'補充失敗・再試行へ'}
        detail=stages.get(state,'補充待ち' if ready<target else '準備完了')
        text=f'{detail} ｜ 未使用 {ready}/{target}件 ｜ 再使用可能 {reserve}件'
        current=self.tree.get('story',{}).get('id')
        rows=self.history.rows()
        if any(r['id']==current and r['status']=='used' for r in rows):
            text+=' ｜ 表示中：テスト済み（再使用）'
        if not ready and reserve:text+=' ｜ 新作の補充待ち・予備で再生できます'
        elif not ready and not reserve:text+=' ｜ 再生できる物語はまだありません'
        if state in ('designing','acquiring','compiling','local_composing'):
            sequence=data.get('sequence')
            if isinstance(sequence,int):text+=f'\n補充中：No.{sequence:04d}'
            done=data.get('completed',0);total=data.get('total',0)
            if isinstance(total,int) and total>0:
                self.refill_progress.setRange(0,total);self.refill_progress.setValue(done)
                unit='素材' if state=='acquiring' else '場面'
                self.refill_progress.setFormat(f'{unit} {done}/{total} 完了（%p%）')
            else:
                self.refill_progress.setRange(0,0);self.refill_progress.setFormat('生成・検証中')
            if data.get('item'):text+=' ｜ '+str(data['item'])[:100]
            elapsed=max(0,int(time.time()-data.get('stage_started',time.time())))
            text+=f' ｜ この工程の経過 {elapsed//60}分{elapsed%60:02d}秒'
        else:
            self.refill_progress.setRange(0,max(1,target));self.refill_progress.setValue(ready)
            self.refill_progress.setFormat('未使用ストック %v/%m 件')
        self.stock_status.setText(text)
        self.stock_status.setStyleSheet('color:#9a6500;' if ready<target else 'color:#238636;')

    def record_manual_result(self,result):
        self.history.record(result)
        self.history.consume_manual(result['story_id'])

    def consume_current(self):
        sid=self.tree.get('story',{}).get('id')
        if sid and self.history.consume_manual(sid):
            self.log.addItem('この物語をテスト済みにしました。新しい物語を補充します。')

    def reset(self):
        self.timer.stop();self.player.stop()
        if hasattr(self,'session'):self.session.stop('reset')
        self.session=CheckpointSession(self.tree,sink=self.record_manual_result)
        self.tree=self.session.tree
        self.selected=None;self.log.clear();self.graph.set_tree(self.tree);self._graph_state=None;self.refresh()

    def start(self):
        self.player.stop();self.session.start(self.count.value());self.log.clear()
        if self.session.campaign.trial:self.history.begin_playback(self.tree.get('story',{}).get('id'),self.session.campaign.trial.trial_id)
        self.log.addItem('開始：鹿が2秒停止した状態を模擬')
        self.begin_scene()

    def begin_scene(self):
        self.selected=self.engine.node_id
        if self.session.phase=='playing':
            node=self.tree['nodes'][self.engine.node_id];self.player.dry_run=not self.sound.isChecked()
            try:
                audio=node.get('audio');self.player.play(Path(self.tree_path).parent/audio if audio else None,self.session.boundary)
            except (OSError,ValueError):
                self.session.stop('audio_unavailable');self.log.addItem('音源がありません。「音声を再生」を外すか、生成済みの物語を選んでください。')
            else:self.last_wall=time.monotonic();self.timer.start()
        else:self.timer.stop();self.player.stop()
        self.refresh()

    def advance(self):
        if self.session.phase!='playing':return
        if self.player.failed():self.stop();self.log.addItem('音声再生に失敗しました。');return
        now=time.monotonic();elapsed=now-self.last_wall;self.last_wall=now
        self.advance_seconds(elapsed)

    def advance_seconds(self,seconds):
        if self.session.elapse(seconds):
            self.timer.stop();self.player.stop()
            node=self.tree['nodes'][self.engine.node_id]
            if self.tree['nodes'][node['branches']['no_escape']].get('terminal'):
                self.consume_current()
            for _,combo in self.inputs:combo.setCurrentIndex(0)
        self.refresh()

    def answer(self,labels):
        if self.session.phase!='checkpoint':return
        before=self.engine.node_id;self.session.answer(labels)
        after=self.engine.node_id
        text=' / '.join(LABELS[label] for label in labels)
        self.log.addItem(f'{self.now:.1f}秒　{self.tree["nodes"][before].get("title",before)}\n{text} → {self.tree["nodes"][after].get("title",after)}')
        self.log.scrollToBottom();self.begin_scene()

    def submit_multiple(self):
        labels=[combo.currentData() for _,combo in self.inputs[:self.session.count]]
        if all(labels):self.answer(labels)

    def update_submit(self):
        if hasattr(self,'submit') and hasattr(self,'session'):
            self.submit.setEnabled(self.session.phase=='checkpoint' and all(combo.currentData() for _,combo in self.inputs[:self.session.count]))

    def stop(self):
        self.timer.stop();self.player.stop();self.session.stop();self.refresh()

    def inspect_node(self,key):self.selected=key;self.refresh_details()

    def refresh_details(self):
        key=self.selected or self.engine.node_id or self.tree['root'];node=self.tree['nodes'][key]
        self.details.setText(node.get('title',key)+'\n\n'+node.get('narrative','物語の終了地点です。'))

    def refresh(self):
        phase=self.session.phase;active=phase in ('playing','checkpoint');waiting=phase=='checkpoint'
        story=self.tree.get('story',{});weather=story.get('weather',{})
        number=story.get('sequence')
        prefix=f'シナリオ No.{number:04d}　' if isinstance(number,int) else 'サンプル　'
        self.title.setText(prefix+story.get('title','ストーリーの分岐テスト'))
        variation=story.get('variation',{})
        self.title.setToolTip('人数：'+str(variation.get('actor_count','未指定'))+'\n役割：'+' / '.join(variation.get('roles',[]))+'\n変更点：'+story.get('change','')+'\n車両：'+variation.get('vehicle','未指定')+'\n武器：'+variation.get('weapon','未指定')+'\n音の配置：'+variation.get('sound_arrangement',''))
        foot={'grass':'草を歩く音','snow':'雪を踏む音','rain':'水たまりの足音'}.get(weather.get('surface'),'未指定')
        fetched=weather.get('fetched_at','').replace('T',' ')[:19] or '例示データ'
        self.weather.setText(f"{weather.get('location','天気設定なし')}　足音：{foot}　天気取得：{fetched}")
        self.weather.setToolTip(weather.get('source','')+'\n'+self.tree_path)
        name=self.tree['nodes'].get(self.engine.node_id,{}).get('title','')
        elapsed=max(0,self.now-self.engine.entered)
        if phase=='playing':status=f'▶ {name} を再生中　次の反応確認まで {max(0,self.session.boundary-elapsed):.1f}秒'
        elif waiting:status=f'⏸ {name} の反応確認です。音声を停止しました。右で鹿の状態を選んでください。'
        elif phase=='finished':status='物語が終了しました。「再生開始」で再試行できます。'
        else:status='「再生開始」を押すと自動で進み、反応を確認する場面だけ停止します。開始条件の「2秒停止」は模擬入力済みとして扱います。'
        self.status.setText(status)
        self.progress.setValue(round(1000*min(1.,elapsed/self.session.boundary)) if active else 0)
        self.start_button.setEnabled(not active);self.stop_button.setEnabled(active)
        for widget in (self.sound,self.count,self.next_button,self.load_button):widget.setEnabled(not active)
        self.answer_box.setEnabled(waiting)
        self.prompt.setText('回答中は時間も止まります。選ぶと次の場面を自動再生します。' if waiting else '再生中の入力は不要です。反応確認までお待ちください。')
        self.single.setVisible(self.session.count==1);self.multiple.setVisible(self.session.count>1)
        for i,(row,combo) in enumerate(self.inputs):row.setVisible(i<self.session.count)
        self.update_submit()
        state=(self.engine.node_id,waiting,tuple(t['node'] for t in self.engine.transitions))
        if state!=self._graph_state:
            self.graph.update_state(self.engine.node_id,waiting,self.engine.transitions);self._graph_state=state
        self.refresh_details()
        result=self.campaign.last_result
        self.evaluation.setText(f"模擬評価：{result['elapsed_seconds']:.1f}秒 / 刺激指標 {result['stimulus_dose']} / スコア {result['score']}\n回答を考えた時間は含みません。" if result else '手動入力の結果は模擬評価として保存し、現場の実績には混ぜません。')

    def next_story(self):
        if self.session.events:self.consume_current()
        self.stock.index=0
        path=self.stock.next()
        if path is None:self.status.setText('生成済みの物語を準備中です。');return
        self.tree_path=str(path);self.tree=load_tree(path);self.reset()

    def load(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'ストーリーを読込',str(Path(self.tree_path).parent),'YAML / JSON (*.yaml *.yml *.json)')
        if not path:return
        try:tree=load_tree(path)
        except (OSError,ValueError,KeyError,TypeError,yaml.YAMLError) as error:
            QtWidgets.QMessageBox.warning(self,'読み込み失敗',str(error));return
        self.tree_path=path;self.tree=tree;self.reset()

    def save(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'結果保存',str(Path.home()/'geniac_scenario_case.json'),'JSON (*.json)')
        if not path:return
        try:Path(path).write_text(json.dumps({'version':2,'tree':self.tree,'events':self.session.events},ensure_ascii=False,indent=2))
        except OSError as error:QtWidgets.QMessageBox.warning(self,'保存失敗',str(error))

    def closeEvent(self,event):self.stock_timer.stop();self.timer.stop();self.player.stop();self.session.stop('window_closed');event.accept()


def main(args=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--tree');options=parser.parse_args(args)
    if options.tree:path=options.tree
    else:
        from ament_index_python.packages import get_package_share_directory
        path=Stock(DEFAULT_STOCK).next() or Path(get_package_share_directory('geniac_scenario'))/'config/story_tree.yaml'
    app=QtWidgets.QApplication(sys.argv[:1]);window=ManualWindow(path)
    if not options.tree and window.tree.get('story',{}).get('design_version',0)<3:
        window.start_button.setEnabled(False)
        window.start_button.setText('音源付きストーリーを準備中…')
        window.status.setText('新しい検証条件で音源付きストーリーを準備中です。準備できると自動で表示します。')
        window.stock_wait=QtCore.QTimer(window)
        def check_stock():
            ready=Stock(DEFAULT_STOCK).next()
            if ready:
                window.stock_wait.stop();window.tree_path=str(ready);window.tree=load_tree(ready)
                window.start_button.setText('▶ 再生開始');window.reset()
            else:
                window.start_button.setEnabled(False)
                try:
                    status=json.loads((DEFAULT_STOCK/'status.json').read_text())
                except (OSError,ValueError):status={}
                failed=status.get('status')=='preparation_failed'
                window.status.setText('ストーリーまたは音源の検証に失敗しました。生成側で再試行中です。まだ再生できません。' if failed else '再生可能なストーリーは0件です。ツリー生成・音源検索・検証を実行中です。準備後に自動で読み込みます。')
        window.stock_wait.timeout.connect(check_stock);window.stock_wait.start(3000)
    window.show();return app.exec_()


if __name__=='__main__':main()
