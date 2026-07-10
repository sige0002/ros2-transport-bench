# Stage-0 計測結果(netns モード・予備実測)— 2026-07-10

単一ホスト・docker netns 疑似 LAN(veth、帯域無制限 ≈ メモリ速度)での実測。
**Stage-0 の GO 判定には使えない**(裁定は実 NIC・実スイッチ越しを要求)。
ハーネスの成立検証と上限値取りが目的。分母 R_pub はすべて pub 側 driver 統計。

## G1 — F(T) ≥ 0.99(独立分母)

| セル | R_pub | F_rec(ロボット上) | F_through(ブリッジ経由 PC) | 境界コピー |
|---|---|---|---|---|
| comp_base t0/t1(120KB@30Hz) | 30.0 | 0.999 / 1.000 | — | 0.0x |
| comp_through t0/t1 | 30.0 | 1.000 / 1.001 | **1.000 / 1.001** | 1.002x |
| uncomp_base 既定バッファ(10MB@30Hz) | 30.0 | **0.168(FAIL)** | — | 0.0x |
| uncomp_base rmem64 t0/t1 | 30.0 | 1.000 / 1.000 | — | 0.0x |
| uncomp_through rmem64 t0/t1 | 30.0 | 1.000 / 1.000 | **1.000 / 1.000** | 1.001x |

- 圧縮相当・非圧縮(300MB/s)とも、rmem64 の下で **through-bridge チェーン
  (DDS→egress→TCP→ingress→DDS 再パブリッシュ)が F=1.000 でフルレート通過**(netns 上限値)。
- 既定カーネルでは**ロボット上 1 ホップの recorder ですら F=0.168** — 「非圧縮域では
  A 配置でも源側ノブ(rmem)必須」という裁定の注記をそのまま実証。

## G2 — source-integrity guard(reliable writer × ブリッジ × 200Mbit 制限)

| セル | R_pub | F_rec | F_through |
|---|---|---|---|
| rel_guard_base(reliable、ブリッジ無し) | 30.006 | 0.9999 | — |
| rel_guard_bridged_shaped(+ブリッジ、200Mbit) | **30.006(低下なし)** | 0.9987 | 0.075 |

- 200Mbit に絞られたブリッジ経路は F_through=0.075 まで崩壊したが、**共有 writer は
  絞られず(R_pub 不変)、ロボット上 recorder も F=0.9987 を維持**。
- 限定: 本セルの writer は KEEP_LAST depth10。裁定が警告した結合は KEEP_ALL /
  `max_blocking_time>0` の writer で生じる形態であり、**その変種は未測**。実カメラドライバの
  HISTORY 設定確認は 2 ホスト Stage-0 の必須項目のまま。

## G3 — 境界単一セッション + loopback 固定

- 全 baseline セルで robot ns eth0 ≈ 0.0MB/s(DDS は whitelist で ns 内 loopback に封止)。
- 全 through セルで eth0 ≈ 1.001〜1.002 × payload(**境界を渡るのは zenoh セッション
  1 コピーのみ**、300MB/s 時も 314.97MB/s ≈ ヘッダ込み 1.0x)。

## G4 — native peer 互換性プローブ

- **INCOMPATIBLE**: rmw_zenoh_cpp(0.2.9)購読者を zenoh-bridge-ros2dds(v1.9.0)の
  セッションに直結(connect 成功・ノード正常起動・stderr なし)しても**受信 0**。
  キー表現/リブネス方式の不一致とみられる。
- 含意(kairos 裁定への反映事項): DDS ロボットの終着形として裁定が置いた
  「ゲートウェイ + PC 側 native rmw_zenoh ピア(DDS-42 全廃)」は**現行バージョン組では
  直結不能**。PC 側の消費は当面「第 2 ブリッジ(ingress 再パブリッシュ)」経由が唯一形態
  (= DDS-42 相当は撤去可能なシムではなく、bridge↔rmw_zenoh 互換が上流で入るまで
  構造的に必要)。バージョン更新時に本セルを再走させること。

## 総括

- ハーネスは全ゲートを計測可能(G1〜G4 とも判定が出る)。2 ホストモードの手順は README 参照。
- netns 上限値としては「ブリッジチェーンは 300MB/s をフルレートで通し、源を絞らず、
  境界 1 コピーを守る」。実 NIC・実スイッチでの再測定が Stage-0 GO の必要条件。
