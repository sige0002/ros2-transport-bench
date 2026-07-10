#!/usr/bin/env python3
"""Aggregate cells.jsonl into per-(size,fanout) tables + SHM verification.

n=3 trials -> report the median across trials (robust to one bad trial). Trials
flagged idle_low are excluded when >=2 clean trials remain, else kept with a note.
Emits a JSON summary and markdown tables to stdout.
"""
import json
import os
import statistics as st
import sys
from collections import defaultdict

CONFIG_ORDER = ["fastdds_shm", "fastdds_noshm", "cyclone_noshm", "zenoh_noshm", "zenoh_shm"]
CONFIG_LABEL = {
    "fastdds_shm": "Fast DDS (SHM)",
    "fastdds_noshm": "Fast DDS (no-SHM)",
    "cyclone_noshm": "Cyclone (no-SHM)",
    "zenoh_noshm": "Zenoh (no-SHM)",
    "zenoh_shm": "Zenoh (SHM)",
}
SIZE_ORDER = ["256B", "40KB", "1MB", "4MB"]


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 3) if xs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), 3) if xs else None


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def select_trials(trials):
    """Drop idle_low trials if >=2 clean remain."""
    clean = [t for t in trials if not t.get("idle_low")]
    return clean if len(clean) >= 2 else trials


def sub_latency(rec, key):
    ms = [s["lat_ms"][key] for s in rec["per_sub"] if s.get("lat_ms")]
    return mean(ms)


def sub_loss(rec):
    return mean([s["loss_pct"] for s in rec["per_sub"]])


def sub_rate(rec):
    return mean([s["delivered_rate"] for s in rec["per_sub"]])


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else f"{here}/results/cells.jsonl"
    rows = load(path)
    groups = defaultdict(list)
    for r in rows:
        groups[(r["config"], r["size_label"], r["fanout"])].append(r)

    summary = {}
    for (cfg, size, fo), trials in groups.items():
        used = select_trials(trials)
        n_all, n_used = len(trials), len(used)
        summary[(cfg, size, fo)] = {
            "n_trials": n_all, "n_used": n_used,
            "lat_med": med([sub_latency(t, "median") for t in used]),
            "lat_p90": med([sub_latency(t, "p90") for t in used]),
            "lat_p99": med([sub_latency(t, "p99") for t in used]),
            "lat_max": med([sub_latency(t, "max") for t in used]),
            "loss_pct": med([sub_loss(t) for t in used]),
            "delivered_rate": med([sub_rate(t) for t in used]),
            "ach_rate": med([t.get("pub_achieved_rate") for t in used]),
            "cpu_pub": med([t.get("cpu_pub_pct") for t in used]),
            "cpu_sub_each": med([mean(t.get("cpu_sub_pct") or []) for t in used]),
            "cpu_sub_total": med([sum(x for x in (t.get("cpu_sub_pct") or []) if x) for t in used]),
            "cpu_router": med([t.get("cpu_router_pct") for t in used]),
            "lo_net_MBps": med([t.get("lo_net_MBps") for t in used]),
            "payload_MBps": used[0].get("payload_MBps"),
            "shm_seg_delta": med([t.get("shm_seg_delta") for t in used]),
            "host_idle": med([t.get("host_idle_pct") for t in used]),
            "rmw_ok": all(t.get("rmw_ok", True) for t in used),
            "coverage_ok": all(t.get("coverage_ok") for t in used),
            "idle_low_any": any(t.get("idle_low") for t in trials),
        }

    def g(cfg, size, fo):
        return summary.get((cfg, size, fo))

    out = []
    for fo in (1, 4):
        out.append(f"## SHM verification — NET loopback MB/s (baseline-subtracted), fanout={fo}\n")
        out.append("net-lo ~0 vs payload => SHM engaged. net-lo ~= payload => UDP/TCP loopback. "
                   "(host baseline ~116 MB/s; net-lo noise ~+/-20, so trust large-payload cells.)\n")
        out.append("| config | " + " | ".join(f"{s}(pay {g(CONFIG_ORDER[2], s, fo)['payload_MBps'] if g(CONFIG_ORDER[2], s, fo) else '?'})" for s in SIZE_ORDER) + " |")
        out.append("|" + "---|" * (len(SIZE_ORDER) + 1))
        for cfg in CONFIG_ORDER:
            cells = []
            for size in SIZE_ORDER:
                s = g(cfg, size, fo)
                cells.append(f"{s['lo_net_MBps']}" if s else "-")
            out.append(f"| {CONFIG_LABEL[cfg]} | " + " | ".join(cells) + " |")
        out.append("")
    out.append("Fast DDS /dev/shm segment delta (fanout=1): "
               + ", ".join(f"{CONFIG_LABEL[c]} 4MB={g(c,'4MB',1)['shm_seg_delta'] if g(c,'4MB',1) else '-'}"
                           for c in ("fastdds_shm", "fastdds_noshm")))
    out.append("")

    for fo in (1, 4):
        out.append(f"\n## Latency median / p99 (ms), fanout={fo}\n")
        out.append("| config | " + " | ".join(f"{s} med/p99" for s in SIZE_ORDER) + " |")
        out.append("|" + "---|" * (len(SIZE_ORDER) + 1))
        for cfg in CONFIG_ORDER:
            cells = []
            for size in SIZE_ORDER:
                s = g(cfg, size, fo)
                cells.append(f"{s['lat_med']}/{s['lat_p99']}" if s else "-")
            out.append(f"| {CONFIG_LABEL[cfg]} | " + " | ".join(cells) + " |")

        out.append(f"\n## Loss % / delivered Hz, fanout={fo}\n")
        out.append("| config | " + " | ".join(SIZE_ORDER) + " |")
        out.append("|" + "---|" * (len(SIZE_ORDER) + 1))
        for cfg in CONFIG_ORDER:
            cells = []
            for size in SIZE_ORDER:
                s = g(cfg, size, fo)
                cells.append(f"{s['loss_pct']}%/{s['delivered_rate']}" if s else "-")
            out.append(f"| {CONFIG_LABEL[cfg]} | " + " | ".join(cells) + " |")

        out.append(f"\n## CPU % of one core (pub / sub-each / router), fanout={fo}\n")
        out.append("| config | " + " | ".join(SIZE_ORDER) + " |")
        out.append("|" + "---|" * (len(SIZE_ORDER) + 1))
        for cfg in CONFIG_ORDER:
            cells = []
            for size in SIZE_ORDER:
                s = g(cfg, size, fo)
                if s:
                    rt = f"/{s['cpu_router']}" if s["cpu_router"] is not None else ""
                    cells.append(f"{s['cpu_pub']}/{s['cpu_sub_each']}{rt}")
                else:
                    cells.append("-")
            out.append(f"| {CONFIG_LABEL[cfg]} | " + " | ".join(cells) + " |")

    print("\n".join(out))

    # JSON summary for programmatic use / archival.
    js = {f"{k[0]}|{k[1]}|f{k[2]}": v for k, v in summary.items()}
    with open(f"{os.path.dirname(os.path.abspath(path))}/summary.json", "w") as f:
        json.dump(js, f, indent=2)


if __name__ == "__main__":
    main()
