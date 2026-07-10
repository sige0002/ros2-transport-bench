#!/usr/bin/env python3
"""Aggregate the addition families into report tables.

  composite.jsonl -> per-config img/num loss, latency, CPU, net-lo (median of trials)
  bag.jsonl       -> per-config per-topic delivered rate, inter-arrival jitter, CPU, lo
  qos.jsonl       -> per-config best_effort vs reliable: loss, achieved vs delivered, latency

Idle-low trials are dropped when >=2 clean trials remain (same policy as aggregate.py).
"""
import json
import os
import statistics as st
import sys
from collections import defaultdict

CONFIG_ORDER = ["fastdds_shm", "fastdds_noshm", "cyclone_noshm", "zenoh_noshm", "zenoh_shm"]
LABEL = {"fastdds_shm": "Fast DDS (SHM)", "fastdds_noshm": "Fast DDS (no-SHM)",
         "cyclone_noshm": "Cyclone (no-SHM)", "zenoh_noshm": "Zenoh (no-SHM)",
         "zenoh_shm": "Zenoh (SHM)"}


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 3) if xs else None


def load(path):
    try:
        return [json.loads(l) for l in open(path) if l.strip()]
    except FileNotFoundError:
        return []


def select(trials):
    clean = [t for t in trials if not t.get("idle_low")]
    return clean if len(clean) >= 2 else trials


def composite(path):
    rows = load(path)
    if not rows:
        return "(no composite data)\n"
    g = defaultdict(list)
    for r in rows:
        g[(r["config"], r["fanout"])].append(r)
    out = ["## Composite (4x1MB@25 img + 27x256B@50 num), median of trials\n",
           "| config | fo | img loss% | img lat med/p99 ms | img deliv Hz | num loss% | "
           "cpu_pub | cpu_sub_tot | net-lo MB/s | idle% |",
           "|" + "---|" * 10]
    for fo in (1, 4):
        for cfg in CONFIG_ORDER:
            ts = select(g.get((cfg, fo), []))
            if not ts:
                continue
            out.append(
                f"| {LABEL[cfg]} | {fo} | {med([t['img']['loss_pct'] for t in ts])} | "
                f"{med([t['img']['lat_med_ms'] for t in ts])}/{med([t['img']['lat_p99_ms'] for t in ts])} | "
                f"{med([t['img']['delivered_rate_each'] for t in ts])} | "
                f"{med([t['num']['loss_pct'] for t in ts])} | "
                f"{med([t['cpu_pub'] for t in ts])} | {med([t['cpu_sub_total'] for t in ts])} | "
                f"{med([t['lo_net_MBps'] for t in ts])} | {med([t['host_idle_pct'] for t in ts])} |")
        out.append("|" + " |" * 10)
    # payload reference
    ex = rows[0]
    out.append(f"\npayload per subscriber ~{ex['payload_MBps'] / ex['fanout']:.0f} MB/s "
               f"(x fanout). img_spec={ex['img_spec']} num_spec={ex['num_spec']}\n")
    return "\n".join(out)


def bag(path):
    rows = load(path)
    if not rows:
        return "(no bag data)\n"
    topics = sorted({t for r in rows for t in r["per_topic"]})
    short = {t: t.split("/")[-2] + "/" + t.split("/")[-1] for t in topics}
    g = defaultdict(list)
    for r in rows:
        g[(r["config"], r["fanout"])].append(r)
    out = [f"## Real-bag replay ({rows[0].get('rate_mult')}x rate), median of trials\n",
           "Signals: delivered Hz + inter-arrival jitter (no embedded-ts latency for replay). "
           "Player CPU is the replay cost (report separately).\n"]
    for t in topics:
        out.append(f"\n### {short[t]}")
        out.append("| config | fo | deliv Hz | bw MB/s | jitter med/p99/max ms | mean KB | "
                   "cpu_player | cpu_sub_tot | lo MB/s | idle% |")
        out.append("|" + "---|" * 10)
        for fo in (1, 4):
            for cfg in CONFIG_ORDER:
                ts = select(g.get((cfg, fo), []))
                if not ts:
                    continue
                pt = [x["per_topic"].get(t, {}) for x in ts]
                out.append(
                    f"| {LABEL[cfg]} | {fo} | {med([p.get('delivered_rate_each') for p in pt])} | "
                    f"{med([p.get('bw_MBps_each') for p in pt])} | "
                    f"{med([p.get('interarrival_med_ms') for p in pt])}/"
                    f"{med([p.get('interarrival_p99_ms') for p in pt])}/"
                    f"{med([p.get('interarrival_max_ms') for p in pt])} | "
                    f"{med([p.get('mean_size_KB') for p in pt])} | "
                    f"{med([x['cpu_player'] for x in ts])} | {med([x['cpu_sub_total'] for x in ts])} | "
                    f"{med([x['lo_MBps'] for x in ts])} | {med([x['host_idle_pct'] for x in ts])} |")
    return "\n".join(out) + "\n"


def qos(path):
    rows = load(path)
    if not rows:
        return "(no qos data)\n"
    ex = rows[0]
    g = defaultdict(list)
    for r in rows:
        g[(r["config"], r["reliability"])].append(r)
    out = [f"## QoS contrast: BEST_EFFORT vs RELIABLE ({ex['size']}B @ {ex['rate']}Hz, "
           f"fanout {ex['fanout']}), median of trials\n",
           "Shows shed (best_effort: loss up, latency flat) vs backpressure "
           "(reliable: loss down, achieved-rate/latency pay).\n",
           "| config | QoS | loss% | pub achieved Hz | sub delivered Hz | lat med/p99 ms | "
           "cpu_pub | net-lo MB/s |",
           "|" + "---|" * 8]
    for cfg in CONFIG_ORDER:
        for rel in ("best_effort", "reliable"):
            ts = select(g.get((cfg, rel), []))
            if not ts:
                continue
            lat_med = med([t["lat_ms"]["median"] for t in ts if t.get("lat_ms")])
            lat_p99 = med([t["lat_ms"]["p99"] for t in ts if t.get("lat_ms")])
            out.append(
                f"| {LABEL[cfg]} | {rel} | {med([t['loss_pct'] for t in ts])} | "
                f"{med([t['pub_achieved_rate'] for t in ts])} | {med([t['delivered_rate'] for t in ts])} | "
                f"{lat_med}/{lat_p99} | {med([t['cpu_pub'] for t in ts])} | "
                f"{med([t['lo_net_MBps'] for t in ts])} |")
        out.append("|" + " |" * 8)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "composite"):
        print(composite(f"{base}/composite.jsonl"))
    if which in ("all", "bag"):
        print(bag(f"{base}/bag.jsonl"))
    if which in ("all", "qos"):
        print(qos(f"{base}/qos.jsonl"))
