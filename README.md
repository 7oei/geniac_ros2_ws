# geniac_ros2_ws

設置型LiDAR（Livox HAP）とスピーカーで、鹿候補の検知・追跡、反応分類、音声シナリオの切替を行うROS 2 Humbleワークスペースです。開発はマザーPCで行い、最終的にk5から取り出したPCとLiDARへ配置します。足回り、オドメトリ、IMU、自己移動補正を使いません。

## 4パッケージ

| パッケージ | 実装 |
|---|---|
| `geniac_detector` | 地面除去・クラスタ抽出・既存Random Forestモデル・複数候補の短期ID追跡。固定LiDAR座標のJSON、TF、RVizマーカー、診断を出力 |
| `geniac_behavior` | 初期・未検出を含む完全退避・移動して視界内・動かなかったを分類。反応の基準はシナリオごとに更新 |
| `geniac_scenario` | 事前定義DAGツリー、ローカル録音素材の事前ミックス、任意のLLM事前設計、Freesound素材取得、再生中の反応分岐・停止 |
| `geniac_visualizer` | マザー用PyQt GUI（点群・軌跡・認識結果・現在のツリー）、RViz設定、センサーPCでのrosbag録画サービス、任意のDiscord入視通知 |

出典と変更点は [REFERENCES.md](REFERENCES.md)、通信仕様は [docs/interfaces.md](docs/interfaces.md) を参照してください。分類器の出力は**鹿候補**です。実際の鹿の識別精度、退避判定閾値、音源の忌避効果は現場データで調整する必要があります。

## ビルド・単体テスト

Ubuntu 22.04 / ROS 2 Humble、`colcon`、NumPy、SciPy、PyYAML、requests、PyQt5、ffmpeg/ffplayを使用します。ROSパッケージ依存は各 `package.xml` に記載しています。

このPCの通常の `.bashrc` は既存の `armadillo_ros2_ws` を読み込むため、独立したシェルを使います。

```bash
env -i HOME="$HOME" USER="$USER" TERM="${TERM:-xterm}" LANG=C.UTF-8 \
  PATH=/usr/local/bin:/usr/bin:/bin DISPLAY="${DISPLAY:-:0}" \
  XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" \
  XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" bash --noprofile --norc
source /opt/ros/humble/setup.bash
cd ~/geniac_ros2_ws
# 別PCでは依存解決を先に実行：
# rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/local_setup.bash
colcon test --event-handlers console_direct+
colcon test-result --verbose
python3 -m pytest -q
```

実機・Discord・有料APIを使わない追加のROS結合／GUI描画テスト：

```bash
ROS_DOMAIN_ID=171 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  QT_QPA_PLATFORM=offscreen GENIAC_ROS_TESTS=1 \
  python3 -m pytest tests/test_ros_pipeline.py -q
```

GUIテスト画像は `artifacts/dashboard-test.png` に出力します（Git対象外）。

## 開発PCだけで起動

同一シェルの環境を各ターミナルで設定してください。ここでは他のロボットと分離するためdomain 171を使用します。

```bash
export ROS_DOMAIN_ID=171 ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
# 検知→分類→シナリオ。既定は音声を出さないdry-run、待受ON。別プロセスで当日の音声ストックを準備。
ros2 launch geniac_scenario sensor.launch.py
# 別ターミナル：
ros2 launch geniac_visualizer mother.launch.py
```

HAPドライバーはこの4パッケージに含みません。既存ドライバーまたはrosbagから `/livox/lidar`（PointCloud2、`livox_frame`、x/y/z/intensity）を入力します。録画再生時は両launchに `use_sim_time:=true` を渡し、`ros2 bag play BAG --clock` を使用してください。録画に含まれる既存の検知・行動・シナリオトピックが混ざらないよう、再解析時は `--topics /livox/lidar` で入力を限定します。

初期は待受ON（`auto_arm:=false`でOFF）。視界内の鹿が2秒停止し、準備済みストックがあれば再生します。開始後は完全退避までストーリーを先頭から繰り返します。GUIの「シナリオ開始（待受）」で停止後に再度待受をONにできます。「音声停止」で待受もOFFになります。GUIを閉じるだけではセンサーPCの録画・シナリオは停止しません。

## 行動分類

判定基準はプログラム起動時ではありません。シナリオ再生前は入視時の位置、再生中は**各シナリオノードの開始時刻と、その直前に見えていた位置**です。開始時に見えていなかった鹿は、その後に初めて観測した位置を基準にします。

| ラベル | 判定 |
|---|---|
| `escaped`（完全退避） | 初期状態、および観測した鹿の未検出が正常な入力で5秒連続した後。確認中は観測中、再検出で待ち時間をリセット。距離・方向は不問 |
| `retreated_nearby`（移動・視界内） | 基準位置から0.75mを超えて動いたことがあり、今も視界にいる。停止・遠ざかり・4秒待ちは不要。横移動・接近・元の位置へ戻る動きも含む |
| `no_escape`（動かなかった） | 基準から4秒以上経過、基準位置から0.75m以内、直近約2秒の停止条件（速度0.35m/s以下、各位置が現在位置から0.75m以内）を満たす |
| `observing` | 入視直後など、まだ移動も無動作も判定できない |
| `unknown` | 無効な入力・通信断など。正常な点群での未検出とは分ける |

「完全退避」は今回の運用定義であり、実際の視野外への移動、遮蔽、検出漏れを区別しません。点群通信そのものの途絶は完全退避にしません。0.75mは微小な位置揺れを動作に数えないための既存許容範囲です。設定は `geniac_behavior/config/behavior.yaml` にあります。

現在の場面状態は `state` に、シナリオ分岐用の各対象の退避結果は `targets` に保持します。5秒の未検出確認後は `state=escaped` を維持し、低頻度のシナリオ処理も退避結果を読み取れます。初期状態は対象IDが空のため、この表示だけでシナリオが始まることはありません。複数頭では残っている鹿も評価し、1頭が消えただけで全体を完全退避にしません。退避済みの鹿で新しいシナリオを開始しません。

## クリック入力による行動分析の手動テスト

実際の `geniac_behavior.core.Classifier` に、画面で入力した鹿1頭の位置をフレームごとに渡します。ROS通信・LiDAR・音声・Discordは使用しないため、実機とは独立して試せます。

```bash
source /opt/ros/humble/setup.bash
source ~/geniac_ros2_ws/install/local_setup.bash
ros2 run geniac_behavior manual_test
```

- 画面の上方向がLiDARの前方x、左方向がyの正方向です。単位はmです。
- 1クリック＝1フレームです。既定は0.25秒間隔。クリックを考える実時間は判定に影響しません。
- 最初の位置が基準位置になります。間隔は入力開始前に変更できます。「シナリオ開始（次のフレームで基準更新）」を押すと、次の入力時刻と直前の位置で評価基準を更新します。
- 「同じ位置で1フレーム」「同じ位置で指定フレーム追加」で停止時間を入力します。既定の8フレーム追加は2秒分です。
- 「未検出を1フレーム」で見失いを試せます。「1フレーム戻す」は入力を取り消し、残りを再評価します。
- 次のフレームの「期待判定」を選ぶとPASS/FAILを記録します。一括追加では全追加フレームに同じ期待判定を適用します。
- 履歴の行を選ぶと、そのフレームまでの軌跡と判定を表示します。新しいクリックは常に末尾へ追加されます。

試し方：未入力では完全退避。x=10mをクリックして同じ位置を16フレーム追加すると経過4秒で「動かなかった」。次に13mをクリックすれば「移動・視界内」。未検出を1フレーム追加すると「観測中」。0.25秒間隔ではさらに20フレーム未検出を追加すると5秒経過して「完全退避」になり、以後維持します。5秒以内に再検出されると確認待ちを取り消します。通信断・無効入力は確認時間に数えません。再入視時は新しい基準位置で評価します。

「JSON保存」は入力・設定・期待判定・結果を保存します。「JSON読込・再評価」は保存された結果を信用せず、現在の分類器で再計算します。期待値付きの保存ケースはGUIなしでも再テストできます。

```bash
ros2 run geniac_behavior replay_test ~/geniac_behavior_case.json
# 期待値との不一致があれば終了コード1、一致または期待値なしなら0
ros2 run geniac_behavior manual_test --case ~/geniac_behavior_case.json
# カスタム閾値で新規テストする場合
ros2 run geniac_behavior manual_test --config ~/my_behavior.yaml
```

`--config` は `geniac_behavior: ros__parameters:` 形式のYAMLです。未指定では分類器の標準閾値を使います。保存ケースには使用した閾値を含めます。旧ファイルの期待判定 `absent` は読込時に `escaped` へ移行します。

## 天気に合わせたストーリーと音声ストック

LLMが、鹿にとって脅威になり得る出来事を、全分岐を含む物語として一括生成します。猟師・熊に限定せず、動物・人間・機械・意外な出来事の組み合わせを探索します。次は従来の例示ツリーであり、生成される筋書きをこの形へ固定しません。

```text
森へ入る → 気配を探す → 忍び寄る → 狩りの準備 → 単発の発砲
    ├ 完全退避 → 追跡をやめ、足音が遠ざかる → 終了
    └ 移動・視界内 → 足を止めて様子を見る
                       ├ 動かなかった → 狩りの準備
                       └ 移動・完全退避 → 追跡をやめる
物語終了後も鹿が残る → 次の未使用ストーリーを先頭から再生
```

各場面の最後に最新の鹿の反応で分岐します。完全退避は場面の途中でも追跡中止へ切り替えます。未検出5秒の確認中・判定不明では発砲へ進まず確認待ちへ。複数頭は逃げていない鹿を優先します。すべて退避すると繰り返しを終了し、次の鹿の2秒停止を待ちます。入力通信断・再生エラーでは停止し待受を解除します。

開始条件用の `stationary_seconds` は、既存の「動かなかった＝4秒」と別です。直近2秒の停止条件が成立した時点で開始できます。シナリオ開始後は、同じ鹿がまだ残る限り開始条件の再成立を待ちません。

天気は標津町崎無異（43.828328, 145.090059）のOpen-Meteo現在値をオンライン取得します。雪→雪を踏む音、雨→水たまりの足音、晴れ→草を歩く音。曇り・霧で降水なしも草を既定とします。モデルの天気から選択するもので、現地の積雪や地面を直接観測したものではありません。日付・取得時刻・参照元をストーリーへ保存し、前日や不正な時刻のデータを当日の天気として使いません。

```bash
# 一括準備。天気取得→必要な録音素材の取得→全枝のWAV化→3本を公開
ros2 run geniac_scenario story_stock --env "$HOME/geniac_ros2_ws/.env" --count 3
# 常時維持。在庫を5秒ごとに確認し、終了評価を受けて不足分を生成
ros2 run geniac_scenario story_stock --env "$HOME/geniac_ros2_ws/.env" --watch
# センサーと一緒に起動（stock workerも起動）。音声を有効化する場合
ros2 launch geniac_scenario sensor.launch.py dry_run:=false
```

ストックは `~/.local/share/geniac/story_stock`、在庫と履歴は `history.sqlite3` に保存します。実再生ではストーリーを1回だけ取得し、使用済みは再利用しません。準備済み＋再生中を既定3本維持します。再生中は1枠を占有し、終了評価が記録されると通常5秒以内に不足分の生成を開始します。生成・素材取得・WAV化には別途時間が必要です。在庫が尽きたら音を出さずに待ちます。手動/音声なしテストは在庫を消費しません。プロセス異常で残った取得済み枠は10分後に中断扱いとなります。

通常の在庫監視では天気を30分キャッシュしますが、新しい物語をLLMへ生成させる直前には必ず天気APIを再取得します。日付または地面音条件が変わると未使用の古い木は使いません。ブラウザ画面を操作する方式ではなく、Open-Meteoから構造化データをオンライン取得する方式です。物語は既存素材一覧を渡さず先にLLMで設計し、その後必要な音をFreesoundで検索・ダウンロードします。同一検索条件のキャッシュは再利用しますが、キャッシュにある音へ物語を制限しません。取得が3回失敗した案は実現困難として残し、次の案へ進みます。検証失敗は理由を返して最大3回修正、通信等の失敗時は60秒待って再試行します。全枝の録音が完成するまで公開しません。音の作者・ライセンス・出典は保存します。音源選定はメタデータによるもので試聴済みではありません。

通常は過去の高評価案または直前の良い案を少数の変更で改良します。生成番号の5、10、15…は異なる方向性の探索枠です。探索の結果が歴代の良い結果より悪ければ、次の通常生成は歴代の良かった方向性へ戻します。現場評価がまだなければ直前の未評価案を改良し、実績があるとは扱いません。保存されている最良結果は古くても参照します。既に準備済みの木を作り直さないため、直前の結果の反映は補充で新規生成する木からになります。

画面の「次の生成済み物語」で新作を切り替えて確認できます。

評価は各ストーリーの開始から完全退避確認までの時間、実際に通った場面・音イベントの時間、刺激度、衝撃音回数を記録します。未再生の枝は加算しません。刺激度は0..3の設計指標で、動物のストレスや現場音圧の測定値ではありません。退避確認の5秒も所要時間に含みます。基準スコアは成功時 `100 × (0.6 × exp(-退避秒数/60) + 0.4 × exp(-(刺激量+3×衝撃音回数)/30))`、退避なしは0点、通信断・手動停止・判定不明は評価対象外です。刺激量は音イベントの実行秒数×(刺激度/3)^2の合計です。手動入力やdry-runは別区分で保存し、実績による生成へ混ぜません。因果効果を証明するスコアではなく比較用の観測結果です。

継続生成はLLM APIとFreesoundのキーを使用し、LLM API料金が発生します。無限に作り溜めるのではなく、在庫上限を保ちながら利用に応じて新作を生成し続けます。再生プロセスは完成済みのローカル木を選ぶだけで、APIには接続しません。旧 `story_tree.yaml` / `demo_tree.yaml` は固定例・回帰テストとして残します。

特定の完成済み木だけを使う場合：

```bash
ros2 launch geniac_scenario sensor.launch.py stock_enabled:=false \
  tree_path:=/absolute/path/to/tree.yaml dry_run:=false
```

音量はffplayの30%で、OS音量は変更しません。音声なしの検証には `dry_run:=true` を使います。外部取得も行わないテストは `stock_enabled:=false dry_run:=true` です。

## マザー／k5の分離と録画

配置段階では、k5側でHAPドライバーと `sensor.launch.py`、マザー側で `mother.launch.py` を起動します。同じ `ROS_DOMAIN_ID`、`ROS_LOCALHOST_ONLY=0` と通信可能なDDS設定が必要です。既存のk5 HAPがdomain 105で動いている場合は、接続する開発プロセスも105へ合わせます。k5の有線とWi-Fiが同一サブネットなので、マザーへのWi-Fi経路を確認してください。

このプロジェクトはLiDARが固定設置されている前提です。設置姿勢が変わったら追跡・反応評価を再起動してください。マザーへ送るPointCloud2はWi-Fi上で欠落しやすいため、表示・検知の購読はReliableです。

「センサーPCで録画開始」は `/geniac/recording/start` を呼びます。**録画先は録画サービスを起動したホスト**です。開発PCでsensor.launchを起動すれば開発PCに保存されます。GUI上にホスト名・保存先・稼働状態が表示されます。k5で使うにはk5へ本パッケージを配置し、録画サービスを起動する必要があります。既定保存先は `~/geniac_bags`、`record_dir:=/path` で変更できます。

## Discordと認証情報

`.env.example` が設定例です。実際の `.env` はGit対象外にして権限600で管理します。今回見つかったダウンロード内の `env` はローカル `.env` に配置しています。OpenAIとFreesoundのキーは設定されていますが、Discord webhookは別途設定してください。

Discordの「サーバー設定 → 連携サービス（Integrations）→ ウェブフック」でWebhookを作成し、通知先のテキストチャンネルを選んでURLをコピーします（Webhook管理権限が必要です）。[Discord公式手順](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks)

ローカル `.env` の次の行へ設定します。URLは秘密情報なのでGitやチャットへ貼らないでください。

```dotenv
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/WEBHOOK_ID/WEBHOOK_TOKEN
```

設定後、明示的に有効化します。

```bash
ros2 launch geniac_scenario sensor.launch.py \
  discord_enabled:=true env_file:="$PWD/.env"
```

鹿候補が入視したときに通知し、連続検知・短期IDの変化による連投を抑制します。通知の最小間隔は60秒、既定OFFです。`wait=true` でDiscord側の保存確認を待ち、全体メンションは発生させません。テストは送信をモックしており、実際のDiscord送信は行っていません。

## 現段階

開発PC上の実装・テスト段階です。k5への配置、実鹿での精度評価、現場での音源・音量調整、Discord実送信、LLM生成・素材取得の実動確認は実施済みです。既存のHAPドライバーや `armadillo_ros2_ws` のファイルは変更していません。

## シナリオの手動単体テスト

```bash
source /opt/ros/humble/setup.bash
source ~/geniac_ros2_ws/install/local_setup.bash
ros2 run geniac_scenario manual_test
```

画面中央にストーリーのグラフを表示します。青が現在再生中の場面、黄が反応入力待ち、緑が通過済みで、実際に選んだ枝は太線になります。ホイールで拡大・縮小、ドラッグで移動、「全体表示」「現在地を拡大」で視点を切り替えられます。場面をクリックすると右側に内容を表示します。

1. 必要なら「音声を再生」をONにし、鹿の頭数（1〜3頭）を指定します。
2. 「再生開始」で、鹿が2秒停止した状態を模擬して先頭から再生します。
3. 各場面の終わりの反応確認地点で、音声と仮想時間を止めます。それまでは状態入力できません。
4. 右側で鹿の状態を選ぶと、該当する枝へ進んで次の場面を再生します。複数頭では全個体を選んで「この反応で次へ」を押します。

回答を考えている時間は所要時間・刺激指標に加算しません。完全退避は5秒確認済みの状態を直接入力します。「未検出の確認待ち」「判定できない」の枝は判定不明として終了します。鹿が残る通常の終端では同じ木を先頭から再試行します。この手動テストは本番の連続センサ入力とは異なり、途中の退避割込ではなく確認地点での分岐を試すものです。本番は従来どおり完全退避を随時反映します。

「次の物語」で生成済みの別案を選べます。「結果保存」はツリーと分岐履歴をJSON保存します。評価は模擬として保存し、現場の実績へ混ぜません。ROS通信・外部通知は行いません。音声OFFでも場面の時間は自動で進みます。

### 敵対者の移動と行動の整合性

新規生成の必須情報は、敵対者・出発点・目的地・移動手段・移動理由・行動目的・到着までの手順です。各場面にも場所、行動、直前との因果関係を持たせます。人間は通常「車で接近→停車/エンジン停止→ドア/降車→徒歩で接近」を基本にし、徒歩で来るなら近くの拠点や経路を説明します。動物も生息場所や通り道から来る筋書きと動機を持たせます。探索回でも瞬間移動や根拠のない効果音の羅列にはしません。

車で来る人間の木では、接近の音、停車と降車の音、降車前に歩いていないこと、どの枝からも降車を飛ばして鹿へ接近しないことを検証します。設定上の林道・拠点等は仮定として明記し、取得済み天気や現地観測の事実とは区別します。生成形式はversion 2とし、以前の未使用案は削除せずobsoleteとして保管、新方式で補充します。

### このPCでの常時補充プロセス

現在 `geniac-story-stock.service` をユーザーサービスとして起動しています。停止は `systemctl --user stop geniac-story-stock.service`、稼働確認は `systemctl --user status geniac-story-stock.service`。これは一時サービスでOS起動時の自動起動は未設定です。通常の `sensor.launch.py` にも補充プロセスが含まれ、同じ在庫に対する生成はファイルロックで直列化します。

音源・生成ツリー検証（設計バージョン3）: 検索語の末尾を切り捨てず、Freesoundの名前・説明・タグを要求音と意味照合し、曖昧な候補は採用しません。車両等の移動音はキュー全長以上の素材を必須とします。照合証跡は素材キャッシュのverificationに保存します。この検証はメタデータによるもので、聴取による音響検証ではありません。旧キャッシュと旧生成ストックは再利用しません。継続的なno_escape経路には、no_escapeからだけ進入できる最終attack音（強度3）を必須とし、退避・判定不明では回避します。準備済みストックがない場合、標準GUIは準備待ちを表示して自動読込します。

補充失敗時の継続動作: 新作が検証に失敗しても正常なreadyストックは保持します。未使用の正常ストーリーがなくなった場合は、同日・現在の路面条件に一致し、現行検証を通る使用済みストーリーを再使用します。使用中の二重取得は防止し、再使用の評価も試行ごとに記録します。不正な1件で全ストックを非表示にせず、その1件を隔離して補充枠を空けます。補充失敗の状態には再生可能件数・予備件数・待機なしの再試行を記録します。正常な素材が一度も準備されていない場合や、天気条件の変更で全候補が不適合になった場合は待機します。

最終場面の反復: 最後の場面終了時に `no_escape` が確認された場合は、冒頭へ戻らず同じ場面を再生します。GUIでは毎回、再生完了時に停止して回答を待ちます。反復ごとに判定epochを更新し、古い回答では反復を開始しません。完全退避・移動したが視界内・判定不明は既存の対応分岐へ進みます。撤退場面は反復対象外です。反復は同じ試行として経過時間・刺激量に加算されます。

物語の多様性: 新規生成では敵対者の人数（1～6）、各人の役割、接近方式、会話方式、音の配置を `story.variation` に保存します。時間・音量・題名だけの変更は新作として採用しません。会話を設定した場合は実際のvoice素材と再生キューが必須で、無線クリックだけでは代用できません。GUIの物語タイトルにマウスを合わせると人数・役割・変更点・配置を確認できます。既存の正常ストックは補充完了まで保持します。

手動GUIもストックを消費します。最終場面を初めて再生し終えた時点、またはテストを終了した時点でreadyをusedへ変更し、バックグラウンド補充を開始します。最終場面の反復は継続できます。結果のmodeはmanualのままで実地学習には含めません。未再生の物語を閲覧するだけでは消費しません。

追加課金の許可待ち: OpenAI等が残高・クォータ不足や支払い要求を返した場合、`billing.json` に停止状態を保存し、有料APIへの再試行を止めます。単なるレート制限は課金要求と区別します。GUIに課金確認の案内と「追加課金を伴うAPI利用の再開を許可」ボタンを表示します。このボタンはAPI再開の許可のみで、入金・プラン購入は行いません。残高不足が解消されていなければ再度停止します。

許可待ちは、検証済みの既存物語・同じ用途の既存音源・背景音や声の組み合わせでストックを補充します。有料の生成・素材照合や新規ダウンロードは行いません。天気取得は従来の公開APIを利用します。素材の種類と物語の骨格は保有済みの範囲に限られ、組み合わせは再使用される場合があります。現在の天気に合う素材がなければその旨を表示し、不適合な音を代用しません。通常のAPI利用料金や請求額を事前推計する機能ではなく、プロバイダーが返す残高・課金エラーを検出する機能です。

視界内の最終反応: `no_escape` だけでなく `retreated_nearby` も最終攻撃音へ進み、最終場面で視界内なら再生と反応確認を繰り返します。完全退避と判定不明は攻撃へ進みません。人の会話・無線応答は `speech_required: true` とし、スケルチ・静電気のみの素材は代用不可です。複数人の物語では主経路に発話を必須とします。音声素材は短い発話を選び、先頭だけを切り出して発話を欠落させないよう全長を使用します。既存素材モードでも必須発話を省略しません。

## ドラッグ位置入力による統合テスト

```bash
source /opt/ros/humble/setup.bash
source /home/air-water/geniac_ros2_ws/install/local_setup.bash
ros2 run geniac_scenario integration_test
```

「統合テスト開始」を押すと模擬トラッカーが20Hzで位置を送信し、実際の `BehaviorNode` → `ScenarioNode` → ビジュアライザーのROSトピック連携を実行します。実機と混線しないよう既定ではlocalhost限定のROS_DOMAIN_ID=172を使います。検知ノードは起動せず、その出力である追跡位置だけを模擬します。録画・Discord通知は起動しません。

右上の鹿アイコンをドラッグして移動し、放すとその位置に固定します。既存の静止判定の許容範囲内で2秒停止するとストーリーが自動開始し、その後の位置に応じて自動分岐します。破線の検知範囲から外へ動かすか「鹿を検出する」を外すと未検出となり、5秒継続で完全退避です。動かない判定は赤、移動・視界内は橙、完全退避は緑枠で表示します。頭数は1～3頭。「センサー途絶を模擬」は無効入力を送り再生を停止させます。再開はチェックを外し「統合テスト開始」を押します。

音声は開始ボタンを押すまで鳴りません。画面の「音声を再生」で切り替えられ、最初から無音で起動する場合は `--mute` を指定します。音声を出してもテスト結果はsimulation扱いで実地の評価に混ぜません。ストックを消費し、通常の補充サービスと連携します。

左上はカメラと点群の領域、左下を左右に二分して2D位置と物語・前回からの変更点を表示します。右列は上下全体を現在のシナリオツリーに使います。2DビューはLiDAR原点を表示し、前方を中心に左右60度（水平120度）、最大距離40mの扇形を検知範囲として描画・模擬判定します。カメラ・LiDARの入力がなければ左上は未接続表示です。通常の `dashboard` も同じ配置に変更しています。カメラは `/camera/image_raw` のRGB/BGR/mono8画像、点群は `/livox/lidar` を受信します。カメラ画像と点群は別ペインで、投影重ね合わせではありません。

短い場面終了時に行動がまだ観測中なら、センサー連携時は音声を終えたまま判定確定を待ちます。未検出確認の5秒間も同様です。明示的な不明・通信途絶では攻撃へ進みません。

ビジュアライザーの「シナリオの補充状況」は `/geniac/scenario/stock` を受信して表示します。シナリオノードが1秒ごとに未使用・予備の件数、生成中の番号、素材／場面の完了件数、工程の経過時間、追加課金の許可待ちを送信します。通常画面と統合テスト画面に共通の進捗欄があり、5秒以上受信がなければ状態不明として表示します。マザー側のファイルではなく、シナリオ実行ホスト側の状態を表示します。

完全退避が確定した場合は、再生中の音声を停止し、そのシナリオを直ちに終了します。既存ストックの退避後の場面は読み込み時に終了ノードへの直接遷移に補正し、ツリー表示にも同じ構造を使います。複数頭の場合は全頭の完全退避を待ちます。未検出5秒の確認は行動分析側で維持し、次の鹿が来た場合は改めて2秒停止してから新しい再生を開始します。

鹿が視界内に残る場合は、「動かなかった」「移動・視界内」をどの順番で選んでも最終の攻撃音に到達するよう、生成時と既存ストックの読み込み時の両方で経路を補正します。攻撃音後も視界内なら同じ最終場面を繰り返し、完全退避では即終了、判定不明では停止します。最終攻撃の素材がないストーリーは再生対象にしません。

話し声は speech_pool.json の検証済み別録音から使用履歴順で選びます。未使用の素材を優先し、同じストーリー内でも発話ごとに別の素材枠を割り当てます。音源IDとデコード後の音声ハッシュで重複を除外し、各用途に対する適合検証を保存します。課金待ちの間も、その用途で検証済みのローカル素材をローテーションします。素材の説明情報に基づく検証であり、発話の意味や話者の本人確認を保証するものではありません。

場面切り替え時は位置の基準点のみ更新し、連続した停止の観測履歴を引き継ぎます。既に2秒停止が確認できている鹿には、各場面・最終攻撃の繰り返しごとに停止確認を待ち直しません。新しい場面以降の位置更新で動いていないことを確認して判定します。移動・通信途絶・無効なセンサー入力があれば古い停止の証拠は使いません。

自動復帰：通信途絶・無効データ・判定不明・音声エラーは待受を解除せず一時停止します。同じ場面の新鮮で有効な判定が戻り、対象が視界内と確定したら、中断した音声位置から再開します。完全退避なら再生せず終了します。音声エラーは1秒間隔で再試行し、失敗した部分を飛ばしません。手動停止・テスト停止・アプリ終了は自動復帰しません。GUIには復旧待ちと停止理由を表示します。

素材の定期更新：ストーリー生成時、話し声以外の素材は音の種類（kind/event）ごとの採用回数を保存し、新素材の採用から5回使った後は、採用のたびに70％の確率で最近の音源IDを除外して別録音を検索し、30％は既存素材を使います。新素材を取得できたら回数をリセットします。用途・長さを検証した新素材だけを採用し、デコードした音声が現在の素材と同一なら差し替えません。検索失敗や追加課金の承認待ちでは使用可能な既存素材を保持します。再生中・最終場面の反復中には検索しません。

音量調整v2：発砲などattackの衝撃音は約+6dBの増幅とソフトリミッターで音の厚みを増し、ピーク0.98まで使用します。その他の衝撃音はピーク-9dBFS、通常音は従来のアクティブRMS-18dBFSとし、発砲との音量差を確保します。最終ミックスのピーク上限0.98は維持します。

音量調整v3：ユーザー指定によりソフトリミッターと最終ミックスのピーク抑制を撤去しました。発砲の約+6dB増幅は維持し、浮動小数点WAVに1.0を超える振幅もそのまま保存します。通常音のRMS調整は維持します。

音量調整v4：発砲に限らず、kind: impulse のすべての衝撃音に同じ増幅（正規化ピーク1.96、約+6dB）を適用します。リミッターと最終ミックスのピーク抑制は適用しません。通常音のRMS調整は維持します。

素材取得の段階的復旧：通常検索に失敗しても、まず同じストーリーのまま同義語・別名の検索語を最大6個追加して再探索します。それでも取得できない場合は、その素材を使う場面の説明と素材説明だけの修正案を作り、元のストーリーとの整合性を別途検証した後に探索します。分岐・場面の順序・音のevent/kind/intensity・発話必須条件は変更できません。各段階で取得素材を検証し、全段階で取得できない場合だけ実現困難として次のストーリー生成へ失敗情報を渡します。成功した部分修正は下書きに保持し、既に取得した音源キャッシュは維持します。補充状況の詳細欄に再探索・場面調整の進捗を表示します。追加課金が必要なら承認待ちに移行します。

ストーリー生成の参照整合性：生成APIでは音源を sound_01〜sound_12 の列挙IDで定義し、各cueの参照フィールドを sound_id に統一しました。人物の役割 story.variation.roles とは別の型・名前として扱います。受信後に既存ランタイムのroleへ変換し、参照先の存在を分岐ポリシー検証より先に確認します。未使用の攻撃素材を定義しただけでは通さず、発砲場面からの参照を必須とします。修正リクエストには原因となった参照と利用可能な音源IDを返します。

背景音整合性：車両の環境音は無条件に全場面へ敷きません。走行場面以外では稼働が明示されている場合だけ許可し、エンジン停止を含む経路の後は明示的な再始動がない限り削除します。生成検証時と音声合成時の両方に適用します。背景音（kind=ambience/event=ambience）は通常音より12dB下げ、衝撃音の増幅設定は維持します。

素材の対象物整合性：車両からの降車・ドア操作には、素材メタデータ上で車両のドアと明記された録音を必須とします。住宅・木製・家具のドア、対象不明のドア、開く動作が必要なのに閉める動作しかない素材は採用しません。生成時の検索語に車両を含め、AIによる対象物・動作・環境の照合に加えて、この条件を候補検証・キャッシュ・再利用ストック・オフライン再構成・最終合成で適用します。

センサー連動再生の最終場面反復：最終の衝撃音を再生して視界内が続いている場合、次の再生まで0〜2秒の一様乱数（小数点以下3桁）で待機します。毎回引き直し、GUIに残り時間を表示します。待機中も行動判定を継続し、完全退避なら終了、未確定なら確定を待ち、通信異常なら一時停止します。最初の衝撃音や通常場面にはこの追加待ち時間を入れません。

生成時の整合性修復：参照切れ、cue時刻、停車・降車順序、退避分岐など修正箇所を特定できるエラーは、元の下書きに対する項目単位の差分で最大2回修復します。完全なストーリーJSONを再生成させません。許可されたパス以外の変更は拒否し、修復後は全体を再検証します。修正履歴はstory.validation_repairsに保存します。構想自体の不成立など修正範囲を特定できない場合、または修復回数超過時はその案を失敗扱いにし、補充処理へ理由を返します。

素材更新の使用回数には、生成時の採用に加え、使用済みシナリオの再使用開始も含めます（実機・統合テスト・手動テスト）。同一再生IDは1回のみで、場面遷移・最終攻撃の自己ループ・音声復旧では増えません。同じ音種が複数ノードにあっても再使用1回につき1回です。再使用履歴はSQLiteへ保存し、補充側が次の素材選択で未集計分を反映します。5回以降は従来どおり70%で別素材探索・30%で既存素材を使い、既に作成済みの音声は差し替えません。導入前の再使用回数は遡って推測加算しません。

補充停止の復旧（2026-11-20）：攻撃場面の後続分岐と、過去に取得失敗した素材の検索条件も項目単位で修復します。過去と同じ説明でも検索語が変わっていれば再探索を許可し、候補の対象物・動作の照合は維持します。素材に合わせた場面修正APIでは変更可能なノードIDを構造化スキーマで固定します。車両走行音は仮の場面尺以上を要求せず、2秒以上の実録音を検証して採用し、既存の単発再生・余剰無音除去により実尺へ合わせます。物語上の目的地と録音に必要な音響条件を分離し、草地の鹿に近づく車を必ず草地走行とするなどの過剰な要件を避けます。

シナリオの方向性探索は生成番号が3の倍数（3回に1回）のときに実行します。探索の効果が低ければ、探索回以外は過去に効果の高かった方向性へ戻します。

通常の改良・効果の高い方向性への復帰では、保存済みの親シナリオがあれば全体を生成し直さず、最大8項目の差分だけを生成します。未変更の場面・素材要求は保持し、追加は1場面・1素材まで許可します。実音声の尺や再生用イベントは設計へ戻してから編集し、差分適用後も全体の整合性を検証します。変更のない素材は既存キャッシュを利用します（既存の確率的素材更新・話し声の選択は継続）。3の倍数の探索回と親の設計が存在しない場合は新規生成します。

方向転換の多様性：探索回では敵対者の大分類だけを変える方式をやめ、保存された全シナリオの登場要素を集計します。猟犬、クマ、狼、重機、草刈り機、ヘリ、スノーモービル、バギー、ドローン、チェーンソー、トラクター、バイク、馬、イノシシ、列車、伐採、空気工具、トラックの18系統から未使用を優先し、全て使用済みなら最少登場回数の候補から選びます。スノーモービルは雪条件のみです。候補外の独自要素との組み合わせも生成へ促します。選択した要素は実際に参照される音源要求に含まれることを検証し、名前だけの変更を拒否します。音の意味・移動経路・素材の一致検証は継続し、駆除効果が実証されたものとしては扱いません。

主要登場者の音：arrival.actorとvariation.rolesから主要登場者を抽出し、対応する特徴音を鹿が残る全経路に必須とします。犬は吠え声・唸り声、クマや狼は固有の発声、人は発話、対応する機械は稼働音を要求します。犬と名付けた汎用足音・草擦れ、未使用のneed、退避枝だけの配置では満たしません。欠落時は対象cueと追加素材だけの局所修復を要求します。候補・キャッシュのメタデータ照合、合成前、既存ストック選択でも検証し、不足するストックは選択しません。メタデータ検証であり、音響認識による実音の証明ではありません。

差分改良の判定：通常改良では過去全体との差別化ではなく、親の再生計画から実際に変化したかを検証します。cueの開始位置・順序・追加音・分岐・音源要求の変更を比較し、説明文・音量・長さだけの変更は部分修正へ戻します。同じ前提や大分類は維持可能です。新規探索回には従来の新規性チェックを適用します。車両・武器等の変更の整合性は、差分改良では直接の親と比較します。

改良の親選択：通常回は常に過去最高評価のシナリオを親とし、直近の探索・成功例へ自動で乗り換えません。実機の完全退避評価を優先し、実機評価がない間だけsimulation/manualの最高評価を暫定ベストとして参照します。同点は先に記録された評価を優先します。評価が全くない場合は最初の非探索シナリオを基準に固定します。3回に1回の探索は継続し、その結果が最高評価を更新した場合にのみ通常改良の親が変わります。テスト評価は実機の効果実証と区別します。

追跡の速度制限：固定センサ座標系で、最後の実測位置からの水平移動距離が max_speed_mps × 最終実測からの経過秒 ＋ position_tolerance_m を超える対応候補は割当て前に除外します。初期調整値は10m/s・0.2mで、生物学的な最高速度の断定値ではありません。予測位置からの従来の距離制限も併用します。未検出フレームを挟む場合の速度推定も最終実測時刻から計算します。超過候補は既存IDを引き継がず新規の未確定候補になるため、全ての誤検出を排除する機能ではありません。Settings/ROSパラメータで調整できます。

### 元rosbagによる統合テスト

`ros2 run geniac_scenario bag_test /path/to/bag_directory --autostart` で、元の `/livox/lidar` だけを等速再生し、現行検出器→行動分析→シナリオ音声→ダッシュボードへ接続します。未検出区間も保持します。ROSドメインは既定175（localhost）、全ノードはuse_sim_time、録音音声は等速のためbag速度も1倍に固定します。`--mute`で無音、`--output`でログ保存先を指定できます。

画面に先頭から開始・一時停止・再開・停止・音声切替を用意しています。一時停止と終了時には音声も止めます。bag終端はセンサー終了として扱い、架空の完全退避を発生させません。検出が安定して停止2秒を満たさなければシナリオは開始しません。認識済み区間の切り出しbagを使うと未検出時間が失われるため、このテストには元bagを指定してください。

`events.jsonl`に検出・行動・シナリオ遷移、`outcomes.jsonl`に試行結果、`summary.json`に検出あり回数とシナリオ開始回数を保存します。結果はbag_testモードとして実機・simulation/manualの最高評価選択から除外します。シナリオストックは通常と共通で、テスト済みになった未使用ストックは使用済みへ進みます。外部通知や録画開始、録画内の制御指令の再生は行いません。

### k5実機運用（マザーとWi-Fi接続）

- k5: `scripts/geniac-sensor`。`scripts/geniac-hap` は既存の
  `~/armadillo_ros2_ws` のHAPドライバと設定を使って `/livox/lidar` を配信する。
- マザー: `scripts/geniac-mother`（ビジュアライザーのみ）。
- マザー表示用の点群は `/geniac/visualization/cloud` に最大5000点・5Hzで配信する。
  検知とrosbagには元の `/livox/lidar` の全点群を使う。
- ROS_DOMAIN_ID=105、CycloneDDS、マザー192.168.1.42 / k5 192.168.1.64。
  IP変更時は `GENIAC_PEER_IP`、NIC変更時は `GENIAC_INTERFACE` で上書きする。
  k5で有線LANとWi-Fiが同じサブネットの場合、マザー宛てのOS経路もWi-Fiにする。
- k5の `.env` に `DISCORD_WEBHOOK_URL` を配置する（Gitには含めない）。
  鹿候補が視界に入ると通知する。誤検出も通知対象となる。
- USBカメラ `/dev/video0` を1280×720、JPEG・10Hzで
  `/camera/image_raw/compressed` に配信する。キャリブレーションは未実施。
- シナリオ開始前にk5でrosbagの起動完了を確認し、完全退避後に保存する。
  保存先は `~/geniac_bags/`。LiDAR、カメラ圧縮画像、追跡、行動、
  シナリオ状態とイベントを含む。入力途絶による一時停止中も録画は継続する。
  手動録画は自動終了せず、GUIの停止ボタンで終了する。
- 自動録画無効時のみ `auto_record:=false` を指定できる。
  `recording_service:=false` を使う際は別途録画ノードを起動するか、自動録画も無効にする。
- 常駐: `scripts/deploy/geniac-{hap,sensor}.service` を `~/.config/systemd/user/` に配置し、
  `systemctl --user enable --now geniac-hap geniac-sensor`。ログは
  `journalctl --user -u geniac-sensor -f`。セッション外での起動にはlinger設定が必要。

### 圧縮ROSBAGのオンライン取得

k5の `geniac-archive.service` が録画後の処理を担当する。シナリオ再生開始時に
Discord通知を永続キューへ保存し、正常に閉じたbagを別プロセスで `.tar.zst` に圧縮する。
圧縮の検証、元ファイルの変更有無、公開HTTPSのHEAD応答とサイズ・ETagを確認してから
未圧縮bagを削除し、ダウンロードURLをDiscordへ通知する。中断録画は終了理由を明示する。
通信失敗時は元bagを残して再試行する。再起動しても処理キューと通知キューは残る。
Discordが受信した直後に接続が切れた場合は、再試行で同じ記録IDの通知が重複する可能性がある。

- 圧縮版: `~/geniac_bags/archives/`
- キュー: `~/geniac_bags/.archive/queue.sqlite3`
- 保持上限: 100GB（100,000,000,000バイト）。完了済み圧縮版を記録日時の古い順に削除する。
  削除されたファイルのURLは無効になる。未完了の記録は削除対象にしない。
- k5の `.env`: `GENIAC_ARCHIVE_BASE_URL=https://<k5の公開ホスト>`、
  `GENIAC_ARCHIVE_DELETE_RAW=true`、必要なら `GENIAC_ARCHIVE_MAX_BYTES`。
- `scripts/deploy/geniac-archive.service` をユーザーサービスとして有効にする。
  サーバーは `127.0.0.1:8765` のみに待受け、Tailscale FunnelからHTTPS中継する。
  `tailscale funnel --bg http://127.0.0.1:8765`。閲覧端末にTailscaleは不要。
- ファイルごとにランダムな専用URLを発行する。URLを知る人が取得できる。
  一覧表示や任意のパス指定には対応しない。大きなファイルの再開用にHTTP Rangeをサポートする。
- シナリオに紐づいた新しい録画のみ自動処理する。過去のbagや手動録画だけのbagは自動削除しない。
- 公開ダウンロードはk5がオンラインの間だけ利用できる。

### マザーのビジュアライザー画面録画

`scripts/geniac-mother` はシナリオ再生開始を受信すると、ビジュアライザー自身の画面を
1500×960・10fpsのH.264 MP4として録画する。k5の再生出力を別途録音し、
同じシナリオIDと時刻で同期して、k5への転送後にAAC音声を合成する。分岐・攻撃音の繰り返し・
入力待ちの一時停止では録画を分割せず、完全退避を受信して終了する。ウィンドウが
別アプリに隠れていても取得できる。GUIを閉じた場合は中断として保存する。
GUIの起動前の場面は録画できない。録画無効で起動する場合は `screen_record:=false`。

- このPCの保存先: `~/geniac_screen_recordings/`。
- このPCで `scripts/deploy/geniac-screen-upload.service` をユーザーサービスとして有効にする。
  GUIを閉じた後も転送の再試行は継続する。
- 完成動画をSSHでk5へ転送し、SHA-256と動画形式を検証後に公開する。
  インターネット側からの取得を確認してから、動画専用のURLをDiscordへ通知する。
  ブラウザー再生・途中再開用のHTTP Rangeにも対応する。
- k5の公開済みROSBAGと動画は合計100GBまで、古い順に削除する。
  このPCにも動画を保持し、合計100GBを超えた場合はk5転送済みの古い動画から削除する。
  未転送動画は失敗時も保持する。

音声はマイクではなくk5の既定スピーカー出力のモニターを収録する。録画開始前から
完全退避までのFLAC音声は `~/geniac_bags/audio/` に保存し、圧縮bagにも同梱する。
共有するMP4に音声を合成し、このPCに保存した元MP4は映像のみとなる。
音声収録を導入する前の動画や収録失敗時は、無音であることをDiscord通知に明記する。
Discordには動画ファイルを添付せず、共有URLだけを送る（動画の添付容量制限に依存しない）。

### USB camera exposure

`geniac_camera` measures frame luminance once per second and adjusts V4L2
exposure time (`adaptive_exposure=true`). The default upper bound is 1000 ms (1 second)
(`max_exposure_ms`); changes are gradual with a brightness deadband. On control
failure or clean shutdown it restores hardware auto exposure. Reconnection
initializes the controller again. This requires `v4l2-ctl` from `v4l-utils`.

The default capture format remains MJPG. k5 also supports YUYV at 1280x720 /
8 fps (`capture_format=YUYV`), but testing in the current dark scene did not
produce a significant brightness improvement. ROS transport and bags still
contain JPEG images. Exposure control values do not guarantee that camera
firmware physically achieves the requested integration time.
Longer exposure may blur moving subjects; darkness without available light
cannot be corrected by exposure alone. Hardware auto exposure remains available
with `adaptive_exposure=false` (on a fresh camera or after clean shutdown).

When adaptive exposure has reached its maximum, `frame_sum_enabled=true`
adds recent frames until the clipped output mean luminance reaches
`frame_sum_target=80`. A fractional final gain avoids overshooting. The sliding
window discards older frames as soon as enough newer frames are available.
`frame_sum_max_frames=64` bounds memory/history; all-black or heavily clipped
scenes may still fail to reach the target. During warmup the partial sum is
published immediately. Motion produces trails and sensor noise also accumulates.
Exposure feedback uses the original image; published JPEG/raw images (including
those recorded in bags) use the summed image. History resets on reconnect,
when exposure drops below its maximum, or when a single frame is bright enough.

### Unattended recovery

Scenario pauses retry automatically. After five seconds of valid epoch-matched
reports, IDs no longer retained by the classifier are removed from the active
cohort (explicit unknown/missing reports still block escalation). A pause lasting
30 seconds closes the episode as `auto_recovery_reset`, preserves arming, and
waits three seconds before considering a new two-second stationary trigger.
Manual disarm remains respected; no audio is started from stale input.

Automatic bags close on that reset. Screen recording closes after 35 seconds of
stale/paused state and uses fragmented MP4 with two-second keyframes, so an
abrupt exit does not invalidate the entire file. The camera/behavior/scenario/
recording nodes respawn after process exits. `geniac-watchdog.service` monitors
six k5 data streams independently: after 30 seconds without a heartbeat it
restarts the sensor stack, and also HAP if LiDAR is missing. Retry spacing is
120 seconds. It does not restart an explicitly stopped sensor service.
Install/enable the watchdog user unit on k5. Mother uses its own persistent user
unit with restart-on-failure and graceful process-group shutdown. This recovers
software faults while powered; it cannot repair a disconnected device, loss of
power, storage exhaustion, or an unavailable external network.

### Camera microphone

k5's private PulseAudio server opens `hw:USBCamera,0` as `geniac_microphone`.
There is no loopback to the k5 speaker. The microphone node publishes 40 ms
chunks of 16 kHz mono signed-16 PCM to `/camera/audio/pcm` (`std_msgs/String`,
JSON fields `stamp`, `rate`, `channels`, `format`, base64 `pcm`). The topic is
included in ROSBAG. The mother dashboard can listen live, with a checkbox and
volume slider; these affect monitoring only, not recording. Late audio is
rejected and the playback queue is bounded to avoid growing latency.

`GENIAC_RECORDING_AUDIO_SOURCE=geniac_microphone` selects the camera microphone
for the existing lossless episode audio capture and MP4 synchronization. The
sidecar keeps its historical `scenario_audio.mka` filename; metadata identifies
the source. Published videos contain environmental audio and scenario sounds
heard by the microphone; digital playback audio is not mixed over it a second
time. The mother-local video remains silent until the k5 publication mux step.
Existing recordings are not retroactively given microphone audio. The watchdog
also monitors microphone packets and restarts the private audio server plus
sensor stack if microphone input stops for 30 seconds.

### WebRTC media / LAN isolation

Production k5 HAP, sensor, watchdog, camera, microphone and ROSBAG use ROS domain
106 with Cyclone DDS pinned to loopback (`geniac-local-network.sh`). They do not
advertise or transmit camera/audio DDS on Wi-Fi or Ethernet. `geniac-lan-bridge`
exports an explicit allowlist to LAN domain 105: tracks, markers, behavior,
scenario state/tree/stock, recording status, TF and the reduced cloud preview.
It proxies the four dashboard Trigger services back to k5. Neither `/camera/*`
nor full `/livox/lidar` is exported. Full data remains in local ROSBAG.

`geniac-webrtc.service` reads local camera JPEG and the shared PulseAudio
microphone source directly, and serves
H.264 video (target 1 Mbps, cap 1.5 Mbps) plus Opus audio over one WebRTC peer
connection. No STUN/TURN or cloud relay is configured; this is LAN-only.
Signaling listens on `192.168.1.64:8766` (override `GENIAC_MEDIA_BIND`) and requires
a random bearer token in `.media-token`, shared with the mother (mode 0600,
not committed). Signaling uses trusted-LAN HTTP; WebRTC media uses DTLS-SRTP.
The server has a 30-second systemd event-loop watchdog. Client reconnects after
failure. Native receiver feeds the existing camera widget and microphone monitor;
it subscribes to no ROS camera/audio topics in production. Long exposure/frame
accumulation still adds capture latency; media transport cannot remove that.

Install on both hosts without modifying system Python:
```
python3 -m venv --without-pip --system-site-packages .venv-media
python3 -m pip install --target .venv-media/lib/python3.10/site-packages -r scripts/media-requirements.txt
```
Install/enable k5 `geniac-lan-bridge.service` and `geniac-webrtc.service` alongside
the updated sensor unit. Restart HAP/sensor/watchdog to change domains together.
The production mother wrapper enables `webrtc_enabled`; offline ROS bag test GUIs
can continue using the ROS image subscriptions with it disabled. Video recording
still captures the rendered widget; its microphone soundtrack is recorded locally
on k5 and muxed at publication, independent of WebRTC packet loss.
