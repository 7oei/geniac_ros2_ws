"""ROS-provided stock status; never reads another host's local cache."""
import time
from PyQt5 import QtWidgets

STAGES={'checking':'補充確認中','designing':'ストーリー生成中','acquiring':'音素材の検索・検証中',
        'compiling':'音声合成中','ready':'準備完了','preparing':'補充待ち',
        'refill_failed':'補充失敗・再試行中','preparation_failed':'準備失敗・再試行中',
        'local_composing':'既存素材で構成中','local_ready':'既存素材モード',
        'local_unavailable':'使える既存素材が不足','disabled':'個別ファイルを再生（補充対象外）'}
ACTIVE={'designing','acquiring','compiling','local_composing'}

class StockPanel(QtWidgets.QGroupBox):
    def __init__(self):
        super().__init__('シナリオの補充状況')
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(10,5,10,7)
        self.summary=QtWidgets.QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.progress=QtWidgets.QProgressBar();self.progress.setMaximumHeight(19);row.addWidget(self.progress,1)
        self.detail=QtWidgets.QLabel();row.addWidget(self.detail,2)
        self.show_status({},False)
    def show_status(self,data,fresh):
        if not fresh:
            self.summary.setText('補充状況の通信待ち／更新が途絶えています')
            self.progress.setRange(0,1);self.progress.setValue(0);self.progress.setFormat('状態不明')
            self.detail.clear();return
        state=data.get('status');ready=data.get('ready_count',0);reserve=data.get('reserve_count',0);target=data.get('target_count',3)
        label=STAGES.get(state,'補充状況を確認中')
        if state=='ready' and ready<target:label='補充待ち'
        text=f'{label} ｜ 未使用 {ready}/{target}件 ｜ 再使用可能 {reserve}件'
        if ready==0 and reserve:text+=' ｜ 新作待ち・予備で再生可能'
        if data.get('billing_blocked'):text+=' ｜ 追加課金の許可待ち（有料API停止）'
        if data.get('source_host'):text+=' ｜ '+str(data['source_host'])
        self.summary.setText(text)
        self.summary.setStyleSheet('color:#b45309;' if ready<target or data.get('billing_blocked') else 'color:#15803d;')
        number=data.get('sequence');prefix=f'No.{number:04d}　' if isinstance(number,int) else ''
        if state in ACTIVE:
            done=data.get('completed',0);total=data.get('total',0)
            if isinstance(total,int) and total>0:
                self.progress.setRange(0,total);self.progress.setValue(done)
                unit='素材' if state=='acquiring' else '場面'
                self.progress.setFormat(f'{unit} {done}/{total} 完了（%p%）')
            else:self.progress.setRange(0,0);self.progress.setFormat('生成中')
            elapsed=max(0,int(time.time()-data.get('stage_started',time.time())))
            self.detail.setText(prefix+str(data.get('item',''))[:65]+f'　経過 {elapsed//60}分{elapsed%60:02d}秒')
        else:
            self.progress.setRange(0,max(1,target));self.progress.setValue(ready);self.progress.setFormat('未使用 %v/%m 件')
            self.detail.setText(str(data.get('item',''))[:90])
