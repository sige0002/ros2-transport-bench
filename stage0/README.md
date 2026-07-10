# Stage-0 計測セル — kairos Option C 裁定(deployment_topology.md §5.5)のゲート実測

kairos の配置トポロジ裁定(§5「Option C(審査済み・条件付き)」)が定義した
**Stage-0 ラボ特性評価**を、そのまま実行可能なセル群に落としたもの。
一次基準は「rosbag 記録中に、周囲の機能の影響で記録トピック周波数が落ちないこと」。

## 測るもの(裁定のゲートとの対応)

| ゲート | セル | 合格条件 |
|---|---|---|
| G1: F(T) ≥ 0.99(独立分母) | `*_base_*` / `*_through_*` | F = 受信数/(R_pub×窓)。**分母 R_pub は pub 側 driver 統計**(`pub.json` の `achieved_rate`)。co-located best_effort 購読者を分母にしない(偽 PASS 回避) |
| G2: source-integrity guard | `rel_guard_base` vs `rel_guard_bridged_shaped` | reliable writer + ブリッジ購読 + 帯域制限(200Mbit)下でも **R_pub が低下しない**こと。低下 = 共有 writer 結合が実在 → 当該構成 NO-GO |
| G3: 境界 1 セッション + loopback 固定 | 全セルの `eth0_tx_MBps` / `boundary_copies` | baseline で ≈0(DDS が境界に漏れていない)、ブリッジ稼働で ≈1×payload(単一コピー) |
| G4: native peer 互換性 | `natcompat_*` | rmw_zenoh 購読者が zenoh-bridge-ros2dds セッションを直接消費できるか(**どちらの結果でも Stage-0 の成果**。不可なら「PC 側は第 2 ブリッジ or 再パブリッシュが必要」が確定) |

ペイロードプロファイルは 2 点: `cam_comp`(120KB@30Hz ≈ 実機の圧縮 depth 相当)と
`cam_uncomp`(10MB@30Hz = 300MB/s、運用者提示の非圧縮想定点)。
非圧縮セルは**既定カーネルバッファでの失敗をまず記録**し(runbook の根拠)、
その後 rmem/wmem=64MiB(実験後復元)で本計測する。

## 実行モード

### netns モード(既定・単一ホスト)

```bash
bash stage0/run_stage0.sh   # -> results/stage0/stage0.jsonl, stage0.log
```

docker ブリッジネットワーク上に robot / pc の 2 ネームスペースを立て、
メンバーコンテナ(`pub`/`recorder-sub`/`egress bridge` = robot ns、
`ingress bridge`/`pc sub` = pc ns)を `--network container:` で各 ns に同居させる。
DDS は両 ns とも 127.0.0.1 whitelist(`configs/fastdds_lo.xml` /
`configs/cyclonedds_lo.xml`)で ns 内 loopback に封じ、**eth0(veth)を通るのは
ブリッジの zenoh TCP セッションだけ**にする — これが G3 のバイト会計の前提。

> **重要: netns モードは Stage-0 の GO 判定に使えない。** 裁定は「実 NIC・実スイッチ
> 越し」を要求している。netns はハーネスの検証と上限値(メモリ速度リンク)取りが目的。
> `tc`(NET_ADMIN 付与済み)で 1GbE/10GbE をエミュレートした参考値は取れる。

### 2 ホストモード(GO 判定用)

ロボット側ホストで robot ns 相当(pub は実カメラに置換可、recorder-sub、egress bridge)を
`network_mode: host` で起動し、PC 側で `STAGE0_ROBOT_IP=<ロボットの LAN IP>` を
セットして ingress/pc-sub セルを回す。プロトコル・集計・ゲートは netns モードと同一。

## 出力

- `results/stage0/stage0.jsonl` — セルごとの生レコード
  (`R_pub`/`F_rec`/`F_through`/`eth0_tx_MBps`/`boundary_copies`/レイテンシ)
- `results/stage0/stage0.log` — 進行ログ

## 判定の読み方(裁定 §5.5 対応)

- `comp_base` の F_rec < 0.99 → ハーネス不良を疑う(圧縮域は全構成ロス 0 が実測済み)
- `uncomp_base_defaultbuf` の F_rec ≪ 1 → 期待どおり(既定カーネルでは A 配置でも落ちる
  = 源側ノブ必須の実証)。`uncomp_base_rmem64` で F_rec ≥ 0.99 に回復すること
- `rel_guard_bridged_shaped` で R_pub が `rel_guard_base` より低下 → **reliable ingress の
  writer 結合が実証** = 本番では reliable ingress 禁止 assertion が必須(裁定どおり)
- `natcompat` は結果自体が知見(COMPATIBLE なら PC 側 native ピア終着形が直結可能、
  INCOMPATIBLE ならブリッジペア or 再パブリッシュ経由が必要)
