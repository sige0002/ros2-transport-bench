#!/usr/bin/env python3
"""Show per-trial spread so ranking claims are only made when trials separate.

For each (config, size, fanout): the 3 trials' loss%, delivered Hz, median latency,
and net-lo. Used to decide whether inter-config differences (esp. DDS loss at 1MB/4MB)
are real or within run-to-run noise before writing any ranking into the report.
"""
import json
import os
import sys
from collections import defaultdict

CONFIG_ORDER = ["fastdds_shm", "fastdds_noshm", "cyclone_noshm", "zenoh_noshm", "zenoh_shm"]
SIZE_ORDER = ["256B", "40KB", "1MB", "4MB"]


def load(path):
    with open(path) as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def main():
    rows = load(sys.argv[1] if len(sys.argv) > 1 else
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "results/cells.jsonl"))
    g = defaultdict(list)
    for r in rows:
        g[(r["config"], r["size_label"], r["fanout"])].append(r)
    for fo in (1, 4):
        print(f"\n===== fanout={fo} : loss% [t0,t1,t2] | delivered Hz | lat_med ms | net-lo MB/s | idle_low =====")
        for size in SIZE_ORDER:
            print(f"-- {size} --")
            for cfg in CONFIG_ORDER:
                ts = sorted(g.get((cfg, size, fo), []), key=lambda x: x["trial"])
                if not ts:
                    print(f"  {cfg:14} (none)")
                    continue
                loss = [t["loss_pct"] for t in ts]
                deliv = [t["delivered_rate"] for t in ts]
                lat = [t["lat_ms"]["median"] if t["lat_ms"] else None for t in ts]
                nlo = [t["lo_net_MBps"] for t in ts]
                il = sum(1 for t in ts if t["idle_low"])
                print(f"  {cfg:14} loss{loss} del{deliv} lat{lat} nlo{nlo} idle_low={il}")


if __name__ == "__main__":
    main()
