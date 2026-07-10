# ros2-transport-bench

ROS 2 Jazzy の RMW 3 実装 × SHM 有無の 5 構成
(**Fast DDS SHM / Fast DDS no-SHM / Cyclone DDS / Zenoh no-SHM / Zenoh SHM**)を、
単一ホスト・コンテナ間通信でロス・レイテンシ・CPU・SHM 実効性の観点から比較する
ベンチマークと、その測定結果。

**結果と考察は [REPORT.md](REPORT.md)**(結論先出し)。
ひとことで: 1MB/4MB ペイロードで Zenoh はロス 0%、DDS ベストエフォートは 43〜82% シェッド。
レイテンシ最良は小ペイロードで Cyclone、大ペイロード×fanout=4 では Zenoh SHM。

## リポジトリ構成

| パス | 内容 |
|---|---|
| `Dockerfile` | 3 RMW 同居の単一ベンチイメージ(`ros:jazzy-ros-base` ベース) |
| `bench/` | pub/sub 本体(`pub.py`/`sub.py`)と追加ファミリ用(`pub_composite.py`, `sub_bag.py`, `pub_qos.py`/`sub_qos.py` ほか) |
| `configs/` | Fast DDS no-SHM プロファイル XML、zenoh ルータ/セッション設定(vendor default から最小差分) |
| `make_zenoh_configs.py` | zenoh 設定をイメージ同梱デフォルトから生成(差分はコメント参照) |
| `driver.py` | ベースマトリクス実行(5 構成 × 4 サイズ × fanout 1/4 × 3 トライアル = 120 セル) |
| `driver2.py` | 追加ファミリ: heavy(飽和域)/ composite(31 トピック模擬)/ bag(実 MCAP リプレイ)/ qos(BE vs reliable) |
| `probe_rates.py` | heavy のレート・bag の自然レートを決めるプローブ |
| `run_additions.sh` | 追加ファミリ一括実行(実測プローブ値入り) |
| `aggregate.py` / `aggregate2.py` / `analyze_spread.py` | 集計(3 トライアル中央値)・ばらつき分析 |
| `results/` | 生データ(セル単位 JSONL)・ドライバログ・集計済みサマリ |

## 再現手順

前提: Linux、Docker。ベンチは `ROS_DOMAIN_ID=88`・`--network=host --ipc=host` で走るため、
同ドメインで他の ROS 2 ノードを動かさないこと。

```bash
# 1. イメージビルド(3 RMW 同居)
docker build -t senoh-bench:jazzy .

# 2. スモーク(1 セルで配線確認)
python3 driver.py smoke

# 3. ベースマトリクス 120 セル(~1.5h)
python3 driver.py full            # -> results/cells.jsonl, results/driver.log

# 4. プローブ + 追加ファミリ(~2h)
python3 probe_rates.py            # -> results/probe_rates.json
bash run_additions.sh             # -> results/cells_heavy.jsonl, composite.jsonl, bag.jsonl, qos.jsonl

# 5. 集計
python3 aggregate.py              # ベース+heavy -> markdown 表 + results/summary.json
python3 aggregate2.py             # composite / bag / qos -> markdown 表
python3 analyze_spread.py         # per-trial ばらつき
```

- bag ファミリのみ外部データ(HSR の MCAP bag)が必要。`SENOH_DATA` 環境変数でデータディレクトリを
  指定(既定 `~/kairos/data`、bag 本体はこのリポジトリに含まれない)。
- 計測の仕組み(net-loopback による SHM 実効判定、cgroup CPU、計測窓の同期)は REPORT.md §3 参照。

## 注意

- 結果は特定環境(aarch64 20 コア、カーネル既定 `rmem_max=208KiB`、未チューニング)での値。
  序列はカーネルバッファ設定・NIC・RMW バージョンで変わりうる。
- レイテンシは「配送されたメッセージ」条件付き。ロスの大きいセルの値は生存バイアスを含む
  (詳細は REPORT.md §5)。
