#!/usr/bin/env bash
# Post-matrix addition families, run sequentially on domain 88 (never concurrently
# with each other or the base matrix). Rates come from probe_rates.py:
#   heavy 4MB=417Hz 8MB=181Hz = floor(0.8 * min pub-achieved across configs)
#   bag x1.0 = real-time fidelity (natural rate re-probed below after the
#   ros2-bag-play argument-order fix; the first probe delivered 0 msgs).
set -e
cd "$(dirname "$0")"

python3 - <<'EOF'
import json
import driver as D
import driver2 as D2
rc = D.ensure_router()
rec = D2.run_bag_cell("cyclone_noshm", D2.BAG_TOPICS, 1.0, 1, 9, rc)
p = json.load(open(f"{D.RESULTS}/probe_rates.json"))
p["bag"] = {"rate_mult": 1.0, "per_topic": rec["per_topic"],
            "lo_MBps": rec["lo_MBps"], "cpu_player": rec["cpu_player"]}
json.dump(p, open(f"{D.RESULTS}/probe_rates.json", "w"), indent=1)
for t, s in rec["per_topic"].items():
    print(f"[re-probe] bag x1.0 {t}: rate={s.get('delivered_rate_each')}Hz", flush=True)
D.cleanup_bench()
EOF

python3 driver2.py heavy 417 181
python3 driver2.py composite
python3 driver2.py bag 1.0
python3 driver2.py qos 4194304 5 4
echo "ALL ADDITIONS DONE"
