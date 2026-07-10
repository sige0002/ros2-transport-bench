#!/usr/bin/env python3
"""Probe the parameters for the addition families (run AFTER the base matrix).

  heavy : saturate pub.py (4MB@1000Hz, 8MB@500Hz requested) per config, fanout 1.
          The heavy-family uniform rate = floor(0.8 * min(achieved across configs)),
          so every config runs at a rate every publisher can actually sustain.
  bag   : one replay cell at rate x1.0 (cyclone_noshm, fanout 1) to record the
          bag's natural per-topic delivery rate before picking the multiplier.

Writes results/probe_rates.json. Uses trial index 9 so tmp tags never collide
with the base matrix (t0-t2).
"""
import json
import math

import driver as D
import driver2 as D2

RESULTS = D.RESULTS


def probe_heavy(size_label, size, req_rate, rc):
    achieved = {}
    for cfg in D.CONFIGS:
        rec = D.run_cell(cfg, size_label, size, req_rate, 1, 9, rc)
        achieved[cfg] = rec["pub_achieved_rate"]
        print(f"[probe] {cfg} {size_label}: requested={req_rate}Hz "
              f"achieved={rec['pub_achieved_rate']}Hz loss={rec['loss_pct']}% "
              f"idle={rec['host_idle_pct']}%", flush=True)
    return achieved


def main():
    rc = D.ensure_router()
    out = {"heavy": {}, "bag": None}

    for sl, sz, rq in (("4MB", 4 * 1024 * 1024, 1000.0), ("8MB", 8 * 1024 * 1024, 500.0)):
        ach = probe_heavy(sl, sz, rq, rc)
        vals = [v for v in ach.values() if v]
        pick = math.floor(0.8 * min(vals)) if vals else None
        out["heavy"][sl] = {"achieved": ach, "picked_rate": pick}
        print(f"[probe] {sl}: min achieved={min(vals) if vals else None}Hz -> pick {pick}Hz", flush=True)

    rec = D2.run_bag_cell("cyclone_noshm", D2.BAG_TOPICS, 1.0, 1, 9, rc)
    out["bag"] = {"rate_mult": 1.0, "per_topic": rec["per_topic"],
                  "lo_MBps": rec["lo_MBps"], "cpu_player": rec["cpu_player"]}
    for t, s in rec["per_topic"].items():
        print(f"[probe] bag x1.0 {t}: rate={s.get('delivered_rate_each')}Hz", flush=True)

    D.cleanup_bench()
    with open(f"{RESULTS}/probe_rates.json", "w") as f:
        json.dump(out, f, indent=1)
    print("[probe] DONE -> results/probe_rates.json", flush=True)


if __name__ == "__main__":
    main()
