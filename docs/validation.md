# Development validation

Environment: development/mother PC, Ubuntu 22.04, ROS 2 Humble, Python 3.10. No k5 deployment or live audio/Discord/API call is performed by these tests.

## Unit tests

`colcon test` discovers the tests in each of the four packages. `python3 -m pytest -q` runs the same source tests plus the opt-in integration tests (skipped without `GENIAC_ROS_TESTS=1`).

Covered behavior:

- Detector: real reference point-cloud fixture, temporal confirmation, stable moving-track IDs, expiration and ID nonreuse, no ego/odometry option, PointCloud2 endian/row padding, malformed fields, bounded latest-cloud mailbox, timestamp/frame discontinuities, serializable candidate output.
- Behavior: three response classes, tangential motion, observation duration, missing targets and stale/invalid input, gaps, clock/stream reset, episode baselines, multi-target aggregation.
- Scenario: every response branch during playback, minimum dwell, old-epoch rejection, unknown timeout, stop, graph/path validation, bounded local playback ownership, mixing and gain/timeline limits, prepared WAVs and attribution, environment loading, mocked offline design and Freesound acquisition.
- Visualizer/control: recording process ownership and arguments, duplicate recording request, startup failure, opt-in Discord entry/cooldown behavior with mocked HTTP, stale GUI data and detector restart.

## ROS integration / UI / recorder

`GENIAC_ROS_TESTS=1 ... python3 -m pytest tests/test_ros_pipeline.py -q` runs on localhost domain 171 with a different domain from the live robot network.

1. Publish the reference PointCloud2 fixture → actual detector outputs → behavior classifier → dry-run scenario start service → no_escape transition to strong → cloud interruption → stop/disarm. No odometry publisher is created.
2. Offscreen PyQt dashboard render with synthetic display data and the sample scenario tree. Preview: `artifacts/dashboard-test.png` (untracked).
3. Start a real local rosbag2 process under a temporary directory, publish a test message, stop with SIGINT, verify metadata and recorded rows in SQLite.

Integration result: 3 passed. Unit result: 62 passed (including Discord transport migration tests). Neither synthetic test reactions nor the reference fixture establish field detection accuracy or deterrence effectiveness.

A separate localhost-only launch smoke check starts the packaged `sensor.launch.py` with dry_run=true and no LiDAR publisher. It verifies package discovery, parameter/launch loading and clean shutdown of all four launched processes. The application starts disarmed.

## Deferred field checks

- Sensor mounting pose and measured detection/false-positive performance.
- Field calibration of escape radius, displacement and stopping thresholds; track continuity in deer groups.
- k5 deployment, networking/DDS bandwidth and time synchronization under actual load.
- Physical speaker output, chosen recorded assets and environmental effect.
- Actual API generation/download and Discord delivery using configured credentials.

Discord migration: request payload, disabled mentions, confirmed delivery, HTTP/network failures, invalid URLs and content bounds are tested with mocked HTTP. No Discord message was sent.

## Manual behavior test tool

The `manual_test` desktop tool feeds click positions directly into the production Classifier using simulated frame timestamps. It does not publish ROS topics or connect to the sensor/audio/notification stack. Each frame can carry an expected label; saved cases are recomputed by `replay_test` and return exit code 1 on mismatches.

Behavior package: 23 tests passed after adding 13 manual-session/UI cases. Added coverage includes the three response trajectories, missing-frame handling, deterministic undo, baseline reset, JSON round-trip with result recomputation, expected-label CLI exit codes, invalid inputs, large frame gaps, and actual offscreen mouse clicks/repeat/history selection. The package built successfully; the example saved case replayed with 1 assertion passed.

## Presence-based response policy (2026-11-20)

The previous 25m / 5m / 2m radial gates are removed. New coverage verifies initial absence, appearance, observed disappearance, subsequent absence, reentry baseline reset, sideways/approaching motion, motion without stopping, scenario-start baseline at the latest visible position, preserved presence across scenario changes, invalid input/outage distinction, partial group departures and new visible IDs. Retained departure outcomes are tested through the scenario engine after the scene has returned to absent. Manual expected-label cases include absence and scenario baseline resets, and survive JSON replay/undo.

Unit tests: 83 passed. Existing integration tests are run separately on localhost.

## Merge empty scene into escaped (2026-11-20)

Initial state and all valid empty detection frames now report `state=escaped`; `absent` is no longer an output label or GUI option. Empty initial scenes contain no target IDs and cannot start scenarios. Invalid/stale sensor data remains unknown. Old manual JSON cases migrate expected `absent` labels to `escaped` during replay. The lifecycle, GUI options, no-target scenario guard and migration are covered by the unit suite: 85 passed; the 3 opt-in ROS integration tests were not rerun for this label merge.

### 2026-11-20: 連続未検出5秒の確認

未検出開始から5秒未満は観測中、5秒で完全退避。再検出時のキャンセル・元の移動基準保持、無効入力/通信断での待ち時間リセット、複数頭、シナリオ分岐、手動入力の保存再生を検証。`python3 -m pytest -q`: 86 passed, 3 skipped（ROS統合テストは今回未実行）。

### 2026-11-20: 他パッケージとの整合

シナリオ途中参加の個体をエピソード対象に保持し、未検出5秒の確認中に対象から落ちないよう修正。可視化に退避確認待ち頭数を追加。シナリオ/可視化テスト49件成功。ROS localhost結合テスト3件成功（検知→行動→シナリオと入力途絶停止、offscreen画面の確認待ち表示、実rosbag記録・停止）。音声はdry-run、外部通知なし。行動パッケージの単体テストは今回は再実行していません。

### 2026-11-20: 天気対応の狩りのストーリー

参照プログラムの「物語→必要な録音→編集」に沿って猟師/熊の物語を全枝一括構成。崎無異の当日天気から足音を選択し、別プロセスでWAV化してストック。2秒停止の開始証拠を追加、場面末の分岐、完全退避の割込、退避まで先頭からの周回、確認待ちから発砲しないこと、日付不一致の在庫拒否を検証。

全体の自動テスト117 passed, 3 skipped。別途ROS結合3 passed（検知→行動→arrival/search、入力断停止、dashboard、実rosbag）。実オンライン天気取得成功: 2026-11-20 01:15 JST / code 0 / 雨0 / 雪0 → grass。Freesound録音4種を取得し、3本・21場面のWAVを生成。全WAVのレート24000Hz・場面長・有限波形・ピーク上限を検証。生成済み木でoffscreen GUI描画確認。実スピーカー再生と現場評価は未実施。素材選定はメタデータのみ。LLM APIの有料要求なし。

### 2026-11-20: 使用結果に基づく継続生成

固定3本の再利用から、LLMによる全分岐の新規生成→不足録音検索/取得→全枝レンダリング→一度限りの実使用→評価保存→補充へ変更。生成前に素材一覧を渡さず、5回ごとの探索、改善、低評価探索後の歴代上位方向への復帰を検証。SQLiteの取得競合、再使用防止、評価後の補充、全期間の最良履歴参照、模擬/中断の除外、未再生音を加算しない評価をテスト。

全体135 passed, 3 skipped。ROS結合3 passed。実APIで新作3本（生成番号1..3）の構想と全分岐を作成し、29場面のWAVを準備。全WAVのレート・長さ・有限値・ピークを検証。LLMのJSON形式差はID配列の正規化で吸収し、unknownは必ず停止する枝に固定して到達不能部分を除去。未実現案・検証失敗はそのまま公開しない。長すぎる素材検索語は音源と動作を保って短縮。実際の現場評価は0件、探索/復帰の学習判断はモック履歴で検証し、実鹿への効果や刺激度は未検証。GUI描画確認、音声は未再生。

稼働中のユーザーサービス: geniac-story-stock（5秒在庫チェック、天気30分キャッシュ、エラー時60秒待機）、geniac-scenario-manual（新作選択・模擬評価表示）。systemd-runの一時サービスで、OS再起動時の自動起動設定はしていません。

### 2026-11-20: グラフ型GUIと反応確認時の一時停止

手動GUIをグラフ＋反応入力パネルへ再構成。開始から自動再生、場面末で音声/仮想時間停止、回答後に分岐再開。再生中の入力を無効化し、複数頭は全個体の回答を要求。Graphvizの経路描画と依存不在時の代替レイアウト、現在位置/通過経路、回答を考える時間の評価除外を検証。

全体141 passed, 3 skipped。別途、更新後のscenarioテストも実施。新規ストーリー直前には30分キャッシュを使わず天気APIを再取得することをモックで確認。生成形式を厳密なJSON Schemaへ変更し、出発点/移動手段/到着手順と各場面の場所/行動/原因を必須化。車で来る人間の降車省略や降車前の徒歩を拒否。場面の刺激度は含まれる音の最大値以上に補正し、過少評価を防止。

実生成した「草縁に止まる点検車」は車両進入→停車/降車→徒歩点検という経路を持ち、全枝WAVを準備。生成時天気取得は2026-11-20 02:19:37 JST。offscreenの実ストーリーグラフと回答待ち画面を確認（artifacts/arrival-story-graph.png）。実スピーカー再生は未実施。新GUIを起動し、残りの新方式在庫も補充。

到着経路検証付きの新方式在庫3本・計29場面の音源準備完了。全3本に対してvalidate_design(require_arrival=True)とローカル音源存在チェックを再実施し成功。題名: 草縁に止まる点検車 / 低空で回る配線ドローン / 草原の夜間保守ランナー。グラフGUIと常時補充サービスはいずれもactive。
