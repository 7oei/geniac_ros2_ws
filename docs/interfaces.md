# Interfaces v1

ROS 2 Humbleの既存メッセージ型を使い、独自のIDLパッケージは追加せず4パッケージで構成します。制御・観測のJSONには `version: 1` を付けます。時刻はROS clockの秒（float）、タイマー期限はmonotonic clockです。bag再生では各ノードのuse_sim_timeを合わせます。

| Topic | Type / QoS | Publisher → consumer |
|---|---|---|
| `/livox/lidar` | sensor_msgs/PointCloud2、購読Reliable depth 1 | 外部HAPドライバー → detector / GUI / RViz |
| `/geniac_detector/tracks` | std_msgs/String JSON、Reliable depth 1 | detector → behavior / GUI / Discord |
| `/geniac_detector/markers` | visualization_msgs/MarkerArray | detector → RViz |
| `/geniac_detector/diagnostics` | diagnostic_msgs/DiagnosticArray | detector → diagnostics / bag |
| `/tf` | tf2_msgs/TFMessage | detector → RViz（LiDARから候補位置、向きはidentity） |
| `/geniac/behavior` | std_msgs/String JSON、Reliable depth 10 | behavior → scenario / GUI |
| `/geniac/scenario/state` | std_msgs/String JSON、Reliable transient-local depth 1 | scenario → behavior / GUI |
| `/geniac/scenario/tree` | std_msgs/String JSON、Reliable transient-local depth 1 | scenario → GUI |
| `/geniac/scenario/events` | std_msgs/String JSON | scenario → bag（開始・切替・停止） |
| `/geniac/recording/status` | std_msgs/String JSON | recorder → GUI |

`tracks`: `stamp, frame_id, stream_id, valid, tracks[]`。各候補は `track_id, center[3], lo[3], hi[3], score, state, child_frame_id, range_m, bearing_rad, hits, points`。bbox位置は鹿の脚の接地点でも体の正確な重心でもありません。scoreは校正済み確率ではありません。stream_idは検知ノード起動ごとのUUIDです。リセットでも同一プロセス内でtrack_idを再利用しません。

`behavior`: `stamp, epoch, frame_id, valid, state, present_ids[], targets[]`。targetは `id=stream_id:track_id, label, range_m, radial_gain_m, displacement_m, last_seen, present, baseline_stamp`（停止判定時はspeed_mpsも）。過去の位置を現在時刻の観測として延命しません。

`scenario/state`: `stamp, epoch, entered_stamp, running, armed, dry_run, node, targets, reason, transitions[]`。epochはエピソードUUIDとノード遷移番号で、behaviorの基準位置を切り替えます。過去ノードの結果による二重分岐を拒否します。GUIの状態表示には受信タイムアウトがあります。

| Service | Type | Execution |
|---|---|---|
| `/geniac/scenario/start` | std_srvs/Trigger | 待受ON、視界内で2秒停止した候補があれば開始 |
| `/geniac/scenario/stop` | std_srvs/Trigger | 待受OFF、所有する音声プロセスを停止 |
| `/geniac/recording/start` | std_srvs/Trigger | サービスを起動したホストでros2 bag record |
| `/geniac/recording/stop` | std_srvs/Trigger | 所有するrecorderプロセス群にSIGINT、終了・flush待ち |

録画プロセスは固定トピック一覧をargvで起動します。シェルコマンドをネットワーク越しに受け取りません。重複開始は拒否し、固有の保存先名を使います。停止がタイムアウトして強制終了した場合は失敗として返し、bagの確認を求めます。

## Tree v1

`version, root, nodes` を持つYAML/JSON。非終端ノードは `title, level(0..3), duration(0..60秒), min_dwell, audio, branches`、終端は `terminal: true`。枝名は `escaped, retreated_nearby, no_escape, unknown`。循環・到達不能ノード・未定義分岐・重複YAMLキーを拒否します。unknownは終端へ、escapedは同等以下のlevelへ遷移する必要があります。最大32ノード、最大経路180秒です。

事前レンダリング時は `events[]`（`asset_id, start, source_start, duration, gain_db`）を追加できます。最大32イベント、gainは-40..0dB、開始・終了時刻は素材とノード内に収めます。素材はffmpegで24kHz monoへ事前変換し、フェード・重ね合わせ・ピーク抑制を適用してWAV化します。プレイヤーには完成したWAVとツリーだけを渡します。

Presence policy: `state` starts at escaped → observing/no_escape/retreated_nearby while visible → escaped while no deer is visible. The former absent label is merged into escaped. After a previously visible target disappears, continuous valid missing frames for `missing_seconds` (default 5.0) confirm escape. Pending targets have `label=observing`, `present=false`, `missing_since`, and `missing_elapsed_seconds`. Reappearance cancels the timer; invalid input or a stale gap resets it. No wall-clock timeout alone confirms escape; invalid/stale sensor input is unknown. Departed target outcomes (`present=false`, `departure_stamp`) remain available for up to 180 seconds and across scenario-node baseline resets, so a slower scenario consumer can branch on the outcome. New scenarios only start from currently present targets.

Scenario cohort: currently visible targets in valid reports for the active epoch are added to the episode cohort and retained across node transitions. Late arrivals remain included while missing detection is being confirmed. Pending/unknown cohort members prevent a reaction branch; the existing node deadline still takes the unknown/finish branch. The dashboard shows the number of pending departures separately from visible candidates.

## Story campaign (2026-11-20)

Behavior targets additionally publish `stationary_seconds` (0 or the confirmed stop-window length; default 2). This is independent of `no_escape`'s four-second response window. A visible target with at least two confirmed seconds starts an armed campaign. Each story is an acyclic whole prepared offline; ordinary branches occur at scene boundaries (`min_dwell=duration`), while a confirmed group escape may interrupt a scene and take the withdrawal branch. The withdrawal scene itself runs to its boundary. No attack branch is entered from unknown/pending observations.

The campaign repeats at the root without the old 30-second cooldown while deer remain. Previously escaped IDs are removed at repeat boundaries to avoid indefinite dependence on expired history. Pending disappearances wait for resolution. Full escape ends the campaign, leaving it armed for a future stationary deer. Stale/invalid input and audio errors disarm. State adds `campaign_active`, `round`, `waiting` (stationary_deer/story_stock/playing/reaction_confirmation/error). Operator stop disarms.

`story_stock --watch` is a separate process. It fetches Sakimui weather every 30 minutes, caches recording assets and atomically publishes `ready.json` only after all branch audio exists. Player reads local ready trees dated today, picks the next between episodes, and never performs remote generation during playback. `story.weather` includes coordinates, date, retrieval and observation times, provider, and ground-sound selection.

## Evolving stock and outcome learning

`history.sqlite3` holds generated concepts and statuses draft/ready/in_use/used/obsolete/unrealizable/interrupted. Field acquisition uses an atomic ready→in_use transition; previews do not consume. A field outcome completes the slot. The worker polls every 5 seconds and counts ready+in_use+draft toward capacity; replacement therefore sees the just-completed result. Monitoring weather remains cached for 30 minutes; each new concept refreshes it before generation. Completed tree/audio files remain immutable and auditable.

Each complete generated DAG includes story title/premise/direction/change/parent_id/strategy/sequence/weather, a sound-needs catalog with kind/intensity/queries, and per-scene cues. No existing recording inventory is sent to the initial concept generator. Every fifth persisted generation is explore; otherwise improve or recover based on all-time field results. Every branch is rendered before queue publication.

`last_evaluation` on scenario state contains outcome, elapsed_seconds, escape_seconds, stimulus_dose, impulse_count, score, actual path, mode, volume, and target IDs. Field successful/not_escaped results drive context; manual, simulation and censored outcomes do not. Time is stopped at the first valid full-group escape confirmation, before any withdrawal tail. Previous prepared stories are not retroactively regenerated.

## Checkpoint GUI and arrival continuity (design version 2)

The manual test uses CheckpointSession around the production Campaign/Engine. Starting simulates the already-confirmed two-second stop. Each scene plays automatically to its end; audio and scenario time then pause. Only then are response controls enabled. User think time is excluded from elapsed/dose. Answers enter the corresponding branch and resume playback. This differs deliberately from live sensor playback, which still accepts escape interrupts mid-scene. Unknown/missing-at-checkpoint follows the terminal unknown branch. Manual results remain separate from field learning.

Graph nodes and routed arrows show branch labels, current playback, waiting and traversal history; Graphviz supplies layout with a built-in fallback. The rendering does not affect scenario policy.

Every new generation performs a fresh online weather request immediately before the LLM call, even if the 30-minute monitoring cache is warm. Each generated story includes arrival actor/origin/destination/travel_mode/reason/purpose/steps/assumptions, and scenes include stage/location/action/cause. Human-vehicle stories require vehicle approach audio at root, stopping and door/exit cues before any approach or interaction on every path, and walking after exit. Site/road assumptions are not treated as observed facts. Version-1 ready/draft stories are retained as obsolete and replaced.
