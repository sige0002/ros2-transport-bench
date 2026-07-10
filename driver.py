#!/usr/bin/env python3
"""Host-side orchestrator for the transport benchmark.

Spawns publisher/subscriber containers (one process each, separate containers so
SHM benefits are genuinely inter-process), times a steady-state window on the
shared CLOCK_MONOTONIC timeline, and samples host metrics cheaply and exactly via
cgroup v2 cpu.stat deltas + /proc counters. All statistics are computed here from
the subscribers' raw per-message dumps.

Usage:
    driver.py smoke        # 5 configs x {256B,4MB} x fanout1 x1 trial -> stdout + smoke.jsonl
    driver.py full         # full matrix -> cells.jsonl
    driver.py full <cfg>   # restrict to one config name (debug)
"""
import glob
import json
import os
import subprocess
import sys
import time

WS = os.path.dirname(os.path.abspath(__file__))
RESULTS = f"{WS}/results"
TMP = f"{RESULTS}/tmp"
IMAGE = "senoh-bench:jazzy"
DOMAIN = "88"

CONFIGS = {
    "fastdds_shm": {"rmw": "rmw_fastrtps_cpp", "env": {}},
    "fastdds_noshm": {
        "rmw": "rmw_fastrtps_cpp",
        "env": {"FASTRTPS_DEFAULT_PROFILES_FILE": "/ws/configs/fastdds_noshm.xml"},
    },
    "cyclone_noshm": {"rmw": "rmw_cyclonedds_cpp", "env": {}},
    "zenoh_noshm": {
        "rmw": "rmw_zenoh_cpp",
        "env": {"ZENOH_SESSION_CONFIG_URI": "/ws/configs/zenoh_session_noshm.json5"},
    },
    "zenoh_shm": {
        "rmw": "rmw_zenoh_cpp",
        "env": {"ZENOH_SESSION_CONFIG_URI": "/ws/configs/zenoh_session_shm.json5"},
    },
}
ZENOH_CONFIGS = {"zenoh_noshm", "zenoh_shm"}

# (label, bytes, rate_hz)
SIZES = [
    ("256B", 256, 100.0),
    ("40KB", 40 * 1024, 25.0),
    ("1MB", 1024 * 1024, 10.0),
    ("4MB", 4 * 1024 * 1024, 5.0),
]
FANOUTS = [1, 4]
TRIALS = 3

WARMUP = 8.0
WINDOW = 20.0
SUB_DUR = 90.0  # safety cap; the driver SIGTERM-stops subs right after the window
PUB_DUR = 35.0
READY_TIMEOUT = 30.0
IDLE_FLOOR = 40.0  # host idle% below this -> flag cell


# ----------------------------------------------------------------------------- docker helpers
def sh(args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def docker_run(name, config, cmd, extra_env=None):
    env = {"ROS_DOMAIN_ID": DOMAIN, "RMW_IMPLEMENTATION": config["rmw"]}
    env.update(config["env"])
    if extra_env:
        env.update(extra_env)
    # memlock=-1 applied UNIFORMLY to every cell: zenoh SHM fails to initialize
    # (POSIX shm ENOMEM) at the 8MB default that kairos containers currently use;
    # raising it lets zenoh SHM function. Verified it does NOT materially change the
    # DDS configs (Fast DDS SHM 4MB loss 71% @8MB vs 75% @unlimited), so it is a
    # neutral, uniform environment rather than a per-vendor tuning.
    args = ["docker", "run", "-d", "--rm", "--name", name, "--ulimit", "memlock=-1",
            "--network=host", "--ipc=host", "-v", f"{WS}:/ws"]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    args += [IMAGE] + cmd
    r = sh(args)
    if r.returncode != 0:
        raise RuntimeError(f"docker run {name} failed: {r.stderr.strip()}")
    return r.stdout.strip()  # full container id


def docker_rm(names):
    for n in names:
        sh(["docker", "rm", "-f", n], timeout=30)


def docker_stop(names, grace=15):
    # SIGTERM (then SIGKILL after grace); lets subscribers flush their dump.
    for n in names:
        sh(["docker", "stop", "-t", str(grace), n], timeout=grace + 20)


def cleanup_bench(keep_router=True):
    r = sh(["docker", "ps", "-a", "--format", "{{.Names}}"])
    victims = [
        n for n in r.stdout.split()
        if n.startswith(("senoh-pub", "senoh-sub"))
        or (n.startswith("senoh-") and not (keep_router and n == "senoh-zenohd"))
    ]
    if victims:
        docker_rm(victims)


# ----------------------------------------------------------------------------- host metrics
def read_cpu_usec(cid):
    p = f"/sys/fs/cgroup/system.slice/docker-{cid}.scope/cpu.stat"
    try:
        with open(p) as f:
            for line in f:
                if line.startswith("usage_usec"):
                    return int(line.split()[1])
    except FileNotFoundError:
        return None
    return None


def read_lo_bytes():
    with open("/proc/net/dev") as f:
        for line in f:
            if "lo:" in line:
                fields = line.replace(":", " ").split()
                # fields: ['lo', rx_bytes, rx_pkts, ...(8)..., tx_bytes, ...]
                return int(fields[1])  # loopback rx_bytes (== tx_bytes)
    return 0


def read_host_cpu():
    with open("/proc/stat") as f:
        vals = list(map(int, f.readline().split()[1:]))
    idle = vals[3] + vals[4]  # idle + iowait
    return idle, sum(vals)


def read_shm_segs():
    try:
        return sum(1 for n in os.listdir("/dev/shm") if "fastrtps" in n)
    except OSError:
        return None


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(q * (len(sorted_vals) - 1) + 0.5))
    return sorted_vals[i]


# ----------------------------------------------------------------------------- router
def ensure_router():
    r = sh(["docker", "ps", "--format", "{{.Names}}"])
    if "senoh-zenohd" in r.stdout.split():
        r2 = sh(["docker", "inspect", "-f", "{{.Id}}", "senoh-zenohd"])
        return r2.stdout.strip()
    cid = docker_run(
        "senoh-zenohd",
        CONFIGS["zenoh_noshm"],
        ["ros2", "run", "rmw_zenoh_cpp", "rmw_zenohd"],
        extra_env={"ZENOH_ROUTER_CONFIG_URI": "/ws/configs/zenoh_router.json5"},
    )
    time.sleep(6)  # let the router bind :7887
    return cid


# ----------------------------------------------------------------------------- one cell
def run_cell(config_name, size_label, size, rate, fanout, trial, router_cid):
    cleanup_bench()
    time.sleep(3)  # let prior DDS/zenoh participants leave
    tag = f"{config_name}_{size_label}_f{fanout}_t{trial}"
    for f in glob.glob(f"{TMP}/{tag}_*"):
        os.remove(f)
    config = CONFIGS[config_name]

    sub_names = [f"senoh-sub-{i}" for i in range(fanout)]
    sub_cids = {}
    for i, name in enumerate(sub_names):
        out = f"/ws/results/tmp/{tag}_sub{i}.json"
        ready = f"/ws/results/tmp/{tag}_sub{i}.ready"
        sub_cids[name] = docker_run(
            name, config,
            ["python3", "/ws/bench/sub.py", "--duration", str(SUB_DUR),
             "--out", out, "--ready", ready],
        )

    # Wait for all subscribers to report node-up.
    ready_files = [f"{TMP}/{tag}_sub{i}.ready" for i in range(fanout)]
    t0 = time.monotonic()
    while time.monotonic() - t0 < READY_TIMEOUT:
        if all(os.path.exists(rf) for rf in ready_files):
            break
        time.sleep(0.3)
    ready_ok = all(os.path.exists(rf) for rf in ready_files)
    sub_rmws = []
    for rf in ready_files:
        try:
            sub_rmws.append(open(rf).read().strip())
        except FileNotFoundError:
            sub_rmws.append(None)

    # Contemporaneous loopback baseline: subs are up but idle (no payload yet), so
    # this captures the host's ~stable background lo traffic (Isaac Sim + kairos on
    # domain 42). Subtracting it isolates the net lo my bench adds -> the SHM signal.
    lo_b0 = read_lo_bytes()
    shm_seg_base = read_shm_segs()
    time.sleep(3)
    lo_baseline_MBps = (read_lo_bytes() - lo_b0) / 1e6 / 3.0

    # Start publisher.
    pub_out = f"/ws/results/tmp/{tag}_pub.json"
    pub_cid = docker_run(
        config=config, name="senoh-pub",
        cmd=["python3", "/ws/bench/pub.py", "--size", str(size), "--rate", str(rate),
             "--duration", str(PUB_DUR), "--out", pub_out],
    )
    pub_start = time.monotonic()

    # Measurement window on the shared monotonic clock.
    w0 = pub_start + WARMUP
    w1 = w0 + WINDOW
    while time.monotonic() < w0:
        time.sleep(0.05)
    cpu0 = {n: read_cpu_usec(c) for n, c in sub_cids.items()}
    cpu0["senoh-pub"] = read_cpu_usec(pub_cid)
    cpu0["router"] = read_cpu_usec(router_cid) if router_cid else None
    lo0 = read_lo_bytes()
    hidle0, htot0 = read_host_cpu()
    w0_ns = time.monotonic_ns()

    while time.monotonic() < w1:
        time.sleep(0.05)
    cpu1 = {n: read_cpu_usec(c) for n, c in sub_cids.items()}
    cpu1["senoh-pub"] = read_cpu_usec(pub_cid)
    cpu1["router"] = read_cpu_usec(router_cid) if router_cid else None
    lo1 = read_lo_bytes()
    shm_seg_win = read_shm_segs()
    hidle1, htot1 = read_host_cpu()
    w1_ns = time.monotonic_ns()

    # Zenoh SHM: capture the session log (while sub-0 is still alive; --rm wipes it
    # on exit) to record whether SHM was announced / fell back / errored. This is
    # the "announced" signal; net-lo is the "engaged" signal.
    zenoh_log = None
    if config_name in ZENOH_CONFIGS:
        r = sh(["docker", "logs", sub_names[0]], timeout=15)
        lines = [ln for ln in (r.stdout + r.stderr).splitlines()
                 if any(k in ln.lower() for k in ("shm", "shared", "threshold", "fallback", "error"))]
        zenoh_log = lines[:6]

    win_s = (w1_ns - w0_ns) / 1e9

    def cpu_pct(name):
        a, b = cpu0.get(name), cpu1.get(name)
        if a is None or b is None:
            return None
        return round((b - a) / 1e6 / win_s * 100.0, 2)  # % of one core

    lo_bytes = lo1 - lo0
    host_idle = round((hidle1 - hidle0) / (htot1 - htot0) * 100.0, 1) if htot1 > htot0 else None

    # Let the publisher finish (writes its summary and exits on its own).
    while time.monotonic() < pub_start + PUB_DUR + 1:
        time.sleep(0.2)
    pub_json = _load_json(f"{TMP}/{tag}_pub.json", timeout=8)

    # Stop subscribers with SIGTERM so they flush their per-message dumps, then read.
    docker_stop(sub_names, grace=15)
    sub_jsons = [_load_json(f"{TMP}/{tag}_sub{i}.json", timeout=12) for i in range(fanout)]

    docker_rm(["senoh-pub"] + sub_names)

    # Per-subscriber stats within [w0_ns, w1_ns].
    per_sub = []
    for sj in sub_jsons:
        per_sub.append(_sub_stats(sj, w0_ns, w1_ns, win_s))

    rec = {
        "config": config_name, "size_label": size_label, "size": size,
        "rate": rate, "fanout": fanout, "trial": trial,
        "expected_rmw": config["rmw"],
        "sub_rmw": sub_rmws,
        "ready_ok": ready_ok,
        "window_s": round(win_s, 3),
        "pub_achieved_rate": round(pub_json.get("achieved_rate", 0.0), 2) if pub_json else None,
        "pub_published": pub_json.get("published") if pub_json else None,
        "cpu_pub_pct": cpu_pct("senoh-pub"),
        "cpu_sub_pct": [cpu_pct(n) for n in sub_names],
        "cpu_router_pct": cpu_pct("router") if config_name in ZENOH_CONFIGS else None,
        "lo_bytes": lo_bytes,
        "lo_MBps": round(lo_bytes / 1e6 / win_s, 3),
        "lo_baseline_MBps": round(lo_baseline_MBps, 3),
        "lo_net_MBps": round(lo_bytes / 1e6 / win_s - lo_baseline_MBps, 3),
        "payload_MBps": round(size * rate * fanout / 1e6, 3),
        "shm_seg_delta": (shm_seg_win - shm_seg_base) if (shm_seg_win is not None and shm_seg_base is not None) else None,
        "zenoh_log": zenoh_log,
        "host_idle_pct": host_idle,
        "idle_low": (host_idle is not None and host_idle < IDLE_FLOOR),
        "per_sub": per_sub,
    }
    # Convenience aggregates across subscribers (median latency of sub0 as ref;
    # loss/rate averaged; coverage is min across subs).
    rec["lat_ms"] = per_sub[0]["lat_ms"] if per_sub else None
    rec["loss_pct"] = round(sum(s["loss_pct"] for s in per_sub) / len(per_sub), 3) if per_sub else None
    rec["delivered_rate"] = round(sum(s["delivered_rate"] for s in per_sub) / len(per_sub), 2) if per_sub else None
    rec["coverage_ok"] = all(s["coverage_ok"] for s in per_sub) if per_sub else False
    return rec


def _load_json(path, timeout=8):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, ValueError):
                time.sleep(0.3)
                continue
        time.sleep(0.3)
    return None


def _sub_stats(sj, w0_ns, w1_ns, win_s):
    if not sj:
        return {"lat_ms": None, "loss_pct": 100.0, "delivered_rate": 0.0,
                "count": 0, "coverage_ok": False, "note": "no_sub_output"}
    recv = sj["recv_ns"]
    seq = sj["seq"]
    lat = sj["lat_ns"]
    idx = [i for i in range(len(recv)) if w0_ns <= recv[i] <= w1_ns]
    if not idx:
        return {"lat_ms": None, "loss_pct": 100.0, "delivered_rate": 0.0,
                "count": 0, "coverage_ok": False, "note": "no_msgs_in_window"}
    win_seq = [seq[i] for i in idx]
    win_lat = sorted(lat[i] for i in idx)
    count = len(idx)
    expected = max(win_seq) - min(win_seq) + 1
    loss = max(0.0, (expected - count) / expected * 100.0) if expected > 0 else 0.0
    # Coverage: delivered messages span the window from near its start to near its
    # end. A 2.5s tolerance keeps this robust for sparse high-loss streams (e.g.
    # 4MB@5Hz where 70% loss leaves ~1 msg/s) while still catching a truncated
    # window from slow discovery or an early subscriber stop.
    win_recv = [recv[i] for i in idx]
    coverage_ok = (min(win_recv) - w0_ns) < 2.5e9 and (w1_ns - max(win_recv)) < 2.5e9
    return {
        "lat_ms": {
            "median": round(pct(win_lat, 0.50) / 1e6, 3),
            "p90": round(pct(win_lat, 0.90) / 1e6, 3),
            "p99": round(pct(win_lat, 0.99) / 1e6, 3),
            "max": round(win_lat[-1] / 1e6, 3),
        },
        "loss_pct": round(loss, 3),
        "delivered_rate": round(count / win_s, 2),
        "count": count,
        "coverage_ok": coverage_ok,
    }


# ----------------------------------------------------------------------------- runners
def smoke():
    router_cid = ensure_router()
    out = open(f"{RESULTS}/smoke.jsonl", "w")
    print(f"{'config':14} {'size':5} {'rmw_ok':6} {'ach.rate':9} "
          f"{'loss%':6} {'lat_med':8} {'cpu_pub':7} {'payMB/s':8} {'netloMB/s':10} "
          f"{'idle%':6} cov")
    for config_name in CONFIGS:
        for size_label, size, rate in [("256B", 256, 100.0), ("4MB", 4 * 1024 * 1024, 5.0)]:
            try:
                rec = run_cell(config_name, size_label, size, rate, 1, 0, router_cid)
            except Exception as e:
                print(f"{config_name:14} {size_label:5} ERROR: {e}")
                continue
            out.write(json.dumps(rec) + "\n")
            out.flush()
            rmw_ok = all(r == rec["expected_rmw"] for r in rec["sub_rmw"] if r)
            latm = rec["lat_ms"]["median"] if rec["lat_ms"] else None
            print(f"{config_name:14} {size_label:5} {str(rmw_ok):6} "
                  f"{str(rec['pub_achieved_rate']):9} {str(rec['loss_pct']):6} "
                  f"{str(latm):8} {str(rec['cpu_pub_pct']):7} "
                  f"{str(rec['payload_MBps']):8} {str(rec['lo_net_MBps']):10} "
                  f"{str(rec['host_idle_pct']):6} {rec['coverage_ok']}")
    out.close()
    cleanup_bench()


def full(only=None):
    router_cid = ensure_router()
    out_path = f"{RESULTS}/cells.jsonl"
    out = open(out_path, "a")
    log = open(f"{RESULTS}/driver.log", "a")

    def logp(m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    configs = [only] if only else list(CONFIGS)
    # Interleave: configs innermost (round-robin), trials outermost (spread over hours).
    cells = []
    for trial in range(TRIALS):
        for size_label, size, rate in SIZES:
            for fanout in FANOUTS:
                for cfg in configs:
                    cells.append((cfg, size_label, size, rate, fanout, trial))

    # Resume support: skip cells already in cells.jsonl (append-mode file), so a
    # killed run can be restarted without duplicating cells / skewing medians.
    done = set()
    if os.path.exists(out_path):
        with open(out_path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done.add((r["config"], r["size_label"], r["fanout"], r["trial"]))
                except (json.JSONDecodeError, KeyError):
                    pass
    logp(f"START full matrix: {len(cells)} cells ({len(done)} already done, resuming)")
    for n, (cfg, sl, sz, rt, fo, tr) in enumerate(cells, 1):
        if (cfg, sl, fo, tr) in done:
            continue
        t0 = time.monotonic()
        try:
            rec = run_cell(cfg, sl, sz, rt, fo, tr, router_cid)
            rmw_ok = all(r == rec["expected_rmw"] for r in rec["sub_rmw"] if r)
            rec["rmw_ok"] = rmw_ok
            out.write(json.dumps(rec) + "\n")
            out.flush()
            latm = rec["lat_ms"]["median"] if rec["lat_ms"] else None
            flag = ""
            if not rmw_ok:
                flag += " RMW_MISMATCH"
            if rec["idle_low"]:
                flag += " IDLE_LOW"
            if not rec["coverage_ok"]:
                flag += " COVERAGE"
            logp(f"[{n}/{len(cells)}] {cfg} {sl} f{fo} t{tr} "
                 f"lat_med={latm}ms loss={rec['loss_pct']}% ach={rec['pub_achieved_rate']}Hz "
                 f"lo={rec['lo_MBps']}MB/s idle={rec['host_idle_pct']}% "
                 f"({time.monotonic()-t0:.0f}s){flag}")
        except Exception as e:
            logp(f"[{n}/{len(cells)}] {cfg} {sl} f{fo} t{tr} ERROR: {e}")
            cleanup_bench()
            time.sleep(3)
    out.close()
    logp("DONE full matrix")
    cleanup_bench()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke()
    elif mode == "full":
        full(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print(__doc__)
        sys.exit(1)
