#!/usr/bin/env bash
# 10MB@30Hz family: the real-robot camera regime (uncompressed / large-resolution
# image topics, ~300MB/s per topic sustained). Sits between the base matrix
# (4MB@5Hz = 21MB/s) and the saturation probes (8MB@181Hz = 1.5GB/s), where loss
# behaviour cannot be interpolated. Point-to-point best_effort cells first, then
# a best_effort-vs-reliable QoS contrast at the same operating point.
set -e
cd "$(dirname "$0")"

python3 - <<'EOF'
import json
import time
import driver as D

rc = D.ensure_router()
out = open(f"{D.RESULTS}/cells_10mb.jsonl", "a")
cells = [(cfg, fo, tr) for tr in range(3) for fo in (1, 4) for cfg in D.CONFIGS]
for n, (cfg, fo, tr) in enumerate(cells, 1):
    try:
        rec = D.run_cell(cfg, "10MB", 10 * 1024 * 1024, 30.0, fo, tr, rc)
        rec["family"] = "cam10mb"
        rec["rmw_ok"] = all(r == rec["expected_rmw"] for r in rec["sub_rmw"] if r)
        out.write(json.dumps(rec) + "\n"); out.flush()
        lat = rec["lat_ms"]["median"] if rec.get("lat_ms") else None
        print(f"[{n}/{len(cells)}] 10MB@30 {cfg} f{fo} t{tr} loss={rec['loss_pct']}% "
              f"ach={rec['pub_achieved_rate']}Hz deliv={rec['delivered_rate']}Hz "
              f"lat={lat}ms net-lo={rec['lo_net_MBps']} idle={rec['host_idle_pct']}%", flush=True)
    except Exception as e:
        print(f"[{n}/{len(cells)}] 10MB@30 {cfg} f{fo} t{tr} ERROR: {e}", flush=True)
        D.cleanup_bench(); time.sleep(3)
out.close()
D.cleanup_bench()
EOF

# QoS contrast at the same point. phase_qos hardcodes results/qos.jsonl, so park
# the 4MB run's file and give each fanout its own output.
[ -f results/qos.jsonl ] && mv results/qos.jsonl results/.qos_4mb.keep
python3 driver2.py qos 10485760 30 1
mv results/qos.jsonl results/qos_10mb_f1.jsonl
python3 driver2.py qos 10485760 30 4
mv results/qos.jsonl results/qos_10mb_f4.jsonl
[ -f results/.qos_4mb.keep ] && mv results/.qos_4mb.keep results/qos.jsonl
echo "10MB FAMILY DONE"
