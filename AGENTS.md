# ros2-transport-bench

ROS 2 Jazzy の RMW / SHM 構成を比較するベンチマーク。

- 再現手順は [README.md](README.md)、測定条件と結論は [REPORT.md](REPORT.md)、独立監査と修正は [REVIEW.md](REVIEW.md)。関連する資料だけ読む。
- `bench/` は pub/sub、`configs/` は transport 設定、`driver*.py` は実行制御、`aggregate*.py` は集計。既存 `results/` は測定証拠として保持する。
- vendor default と調整済みの条件を分けて報告する。負荷・QoS・カーネル設定の違いを transport 自体の優劣と断定しない。
- ベンチは host network / IPC と `ROS_DOMAIN_ID=88` を使う。稼働中の ROS グラフ、ホスト資源、sysctl に影響する実験は実行範囲の依頼があるときだけ行う。
- 集計の変更は保存済みの代表入力と期待する指標を照合し、元の結果を書き換えず検証する。文書修正を理由に全マトリクスを再実行しない。
