# geniac_ros2_ws

設置型LiDARとスピーカーを利用した、鹿の忌避システムを開発するためのROS 2ワークスペースです。

## 開発・実行環境

- ROS 2 Humble / Ubuntu 22.04
- 開発：マザーPC（このリポジトリを作成したPC）
- 最終的な実行先：SSH接続先のk5
- 想定機材：設置型LiDAR（Livox HAP）、スピーカー

現段階はワークスペースの初期化のみです。鹿の検出、音声制御、機材の起動・配置設定は今後実装します。
既存の `armadillo_ros2_ws` から独立して開発します。

## 構成

```text
geniac_ros2_ws/
├── README.md
└── src/                 # 今後追加するROS 2パッケージ
```

`build/`、`install/`、`log/` はビルド時に生成され、Git管理には含めません。
点群記録、音声素材、認証情報、機体固有のローカル設定も登録しません。

## ビルド

既存ワークスペースのオーバーレイを混ぜないよう、クリーンなシェルを開きます。
このPCでは通常の `.bashrc` が既存の `armadillo_ros2_ws` を読み込むため、
`bash --norc` だけではなく環境変数も初期化します。

```bash
env -i HOME="$HOME" USER="$USER" TERM="${TERM:-xterm}" LANG=C.UTF-8 \
  PATH=/usr/local/bin:/usr/bin:/bin bash --noprofile --norc
source /opt/ros/humble/setup.bash
cd ~/geniac_ros2_ws
colcon build --symlink-install
source install/local_setup.bash
```

現在 `src/` は空なので、ビルド結果は `0 packages finished` になります。
ROS 2パッケージは今後 `src/` に追加します。

## k5への配置方針

開発・検証後、k5にも本リポジトリをcloneし、依存関係の導入とビルドを行います。
今回の初期化ではk5への配置や自動起動の設定は行いません。
LiDAR接続、ネットワーク、音量・再生条件は、実装段階で設定ファイルとして整備します。
