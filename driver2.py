#!/usr/bin/env python3
"""Additions to the transport benchmark (run AFTER the base matrix finishes):

  heavy   : cranked point-to-point (max-sustainable 4MB rate + 8MB)   -> cells_heavy.jsonl
  composite: 31-topic kairos-shaped load (4x1MB@25 + 27x256B@50)      -> composite.jsonl
  bag     : real MCAP replay of the compressed-camera topics          -> bag.jsonl

Reuses driver.py's helpers (docker_run, cgroup/lo/idle sampling, router, cleanup).
All families keep the isolation + neutrality rules: domain 88, senoh- containers,
uniform --ulimit memlock=-1, one image, RMW-only differences, interleaved by config.
"""
import glob
import json
import os
import sys
import time

import driver as D

WS = D.WS
TMP = D.TMP
RESULTS = D.RESULTS
CONFIGS = D.CONFIGS
ZENOH = D.ZENOH_CONFIGS
BAG = "/data/airoa-moma-mcap/064423"
DATA_MOUNT = os.environ.get("SENOH_DATA", os.path.expanduser("~/kairos/data"))
# Compressed-camera topics only (all sensor_msgs/CompressedImage; avoids the bag's
# tmc_control_msgs custom types -> no msgs overlay, stays neutral).
BAG_TOPICS = [
    "/hsrb/head_rgbd_sensor/rgb/image_rect_color/compressed",
    "/hsrb/hand_camera/image_raw/compressed",
    "/hsrb/head_rgbd_sensor/depth_registered/image_rect_raw/compressedDepth",
]


def pctl(vals, q):
    return D.pct(sorted(vals), q)


def docker_run_ro(name, config, cmd, ro_mount):
    """Like driver.docker_run but adds a read-only bind mount (host, container)."""
    env = {"ROS_DOMAIN_ID": D.DOMAIN, "RMW_IMPLEMENTATION": config["rmw"]}
    env.update(config["env"])
    args = ["docker", "run", "-d", "--rm", "--name", name, "--ulimit", "memlock=-1",
            "--network=host", "--ipc=host", "-v", f"{WS}:/ws",
            "-v", f"{ro_mount[0]}:{ro_mount[1]}:ro"]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    args += [D.IMAGE] + cmd
    r = D.sh(args)
    if r.returncode != 0:
        raise RuntimeError(f"docker run {name} failed: {r.stderr.strip()}")
    return r.stdout.strip()


# --------------------------------------------------------------------------- window sampler
def measure_lo_baseline(seconds=3.0):
    """Loopback baseline while subscribers are up but idle (call BEFORE starting
    the publisher/player) so net-lo isolates the payload's loopback contribution."""
    a = D.read_lo_bytes()
    time.sleep(seconds)
    return (D.read_lo_bytes() - a) / 1e6 / seconds


def sample_window(names_cids, router_cid, is_zenoh, warmup, window, lo_baseline):
    """Start-of-window/end-of-window cgroup + lo + idle deltas. Returns dict +
    (w0_ns, w1_ns). names_cids maps a label -> full container id. lo_baseline is
    pre-measured (pre-payload) by the caller."""
    t_ref = time.monotonic()
    w0 = t_ref + warmup
    w1 = w0 + window
    while time.monotonic() < w0:
        time.sleep(0.02)
    cpu0 = {k: D.read_cpu_usec(c) for k, c in names_cids.items()}
    cpu0["router"] = D.read_cpu_usec(router_cid) if router_cid else None
    lo0 = D.read_lo_bytes()
    hi0, ht0 = D.read_host_cpu()
    w0_ns = time.monotonic_ns()

    while time.monotonic() < w1:
        time.sleep(0.02)
    cpu1 = {k: D.read_cpu_usec(c) for k, c in names_cids.items()}
    cpu1["router"] = D.read_cpu_usec(router_cid) if router_cid else None
    lo1 = D.read_lo_bytes()
    hi1, ht1 = D.read_host_cpu()
    w1_ns = time.monotonic_ns()
    win_s = (w1_ns - w0_ns) / 1e9

    def cpu_pct(k):
        a, b = cpu0.get(k), cpu1.get(k)
        return round((b - a) / 1e6 / win_s * 100.0, 2) if (a is not None and b is not None) else None

    lo_MBps = (lo1 - lo0) / 1e6 / win_s
    idle = round((hi1 - hi0) / (ht1 - ht0) * 100.0, 1) if ht1 > ht0 else None
    return {
        "win_s": win_s, "w0_ns": w0_ns, "w1_ns": w1_ns,
        "cpu": {k: cpu_pct(k) for k in names_cids},
        "cpu_router": cpu_pct("router") if is_zenoh else None,
        "lo_MBps": round(lo_MBps, 3), "lo_baseline_MBps": round(lo_baseline, 3),
        "lo_net_MBps": round(lo_MBps - lo_baseline, 3),
        "host_idle_pct": idle, "idle_low": (idle is not None and idle < D.IDLE_FLOOR),
    }


# --------------------------------------------------------------------------- composite cell
def run_composite_cell(cfg, fanout, trial, router_cid, n_img=4, img_rate=25.0,
                       n_num=27, num_rate=50.0):
    D.cleanup_bench()
    time.sleep(3)
    tag = f"composite_{cfg}_f{fanout}_t{trial}"
    for f in glob.glob(f"{TMP}/{tag}_*"):
        os.remove(f)
    config = CONFIGS[cfg]
    topics = [f"/img{i}" for i in range(n_img)] + [f"/num{i}" for i in range(n_num)]
    tstr = ",".join(topics)

    sub_names = [f"senoh-sub-{i}" for i in range(fanout)]
    cids = {}
    for i, name in enumerate(sub_names):
        cids[name] = D.docker_run(name, config, [
            "python3", "/ws/bench/sub_multi.py", "--topics", tstr,
            "--duration", "70", "--out", f"/ws/results/tmp/{tag}_sub{i}.json",
            "--ready", f"/ws/results/tmp/{tag}_sub{i}.ready"])
    _wait_ready([f"{TMP}/{tag}_sub{i}.ready" for i in range(fanout)])
    sub_rmws = [_read(f"{TMP}/{tag}_sub{i}.ready") for i in range(fanout)]

    lo_baseline = measure_lo_baseline()  # subs idle, before pub -> clean baseline
    pub_dur = 45.0
    pub_cid = D.docker_run("senoh-pub", config, [
        "python3", "/ws/bench/pub_composite.py",
        "--n_img", str(n_img), "--img_rate", str(img_rate),
        "--n_num", str(n_num), "--num_rate", str(num_rate),
        "--duration", str(pub_dur), "--out", f"/ws/results/tmp/{tag}_pub.json"])
    names_cids = dict(cids)
    names_cids["senoh-pub"] = pub_cid

    win = sample_window(names_cids, router_cid, cfg in ZENOH, warmup=10.0, window=20.0,
                        lo_baseline=lo_baseline)

    time.sleep(max(0, pub_dur - win["win_s"] - 10 + 1))
    pub_json = D._load_json(f"{TMP}/{tag}_pub.json", timeout=10)
    D.docker_stop(sub_names, grace=15)
    sub_jsons = [D._load_json(f"{TMP}/{tag}_sub{i}.json", timeout=15) for i in range(fanout)]
    D.docker_rm(["senoh-pub"] + sub_names)

    fam = _composite_stats(sub_jsons, win["w0_ns"], win["w1_ns"], win["win_s"], n_img, n_num)
    return {
        "family": "composite", "config": cfg, "fanout": fanout, "trial": trial,
        "expected_rmw": config["rmw"], "sub_rmw": sub_rmws,
        "img_spec": f"{n_img}x1MB@{img_rate}", "num_spec": f"{n_num}x256B@{num_rate}",
        "payload_MBps": round((n_img * 1024 * 1024 * img_rate + n_num * 256 * num_rate) / 1e6 * fanout, 2),
        "pub_per_topic": pub_json.get("per_topic") if pub_json else None,
        "cpu_pub": win["cpu"].get("senoh-pub"),
        "cpu_sub_each": _avg([win["cpu"][n] for n in sub_names]),
        "cpu_sub_total": round(sum(win["cpu"][n] for n in sub_names if win["cpu"][n]), 2),
        "cpu_router": win["cpu_router"],
        "lo_MBps": win["lo_MBps"], "lo_net_MBps": win["lo_net_MBps"],
        "host_idle_pct": win["host_idle_pct"], "idle_low": win["idle_low"],
        "window_s": round(win["win_s"], 3), **fam,
    }


def _composite_stats(sub_jsons, w0, w1, win_s, n_img, n_num):
    img_t = [f"/img{i}" for i in range(n_img)]
    num_t = [f"/num{i}" for i in range(n_num)]

    def family(topics):
        lats, losses, rates = [], [], []
        for sj in sub_jsons:
            if not sj:
                continue
            for t in topics:
                rec = sj["per_topic"].get(t)
                if not rec or not rec["recv_ns"]:
                    continue
                idx = [k for k in range(len(rec["recv_ns"])) if w0 <= rec["recv_ns"][k] <= w1]
                if not idx:
                    continue
                ws = [rec["seq"][k] for k in idx]
                wl = [rec["lat_ns"][k] for k in idx]
                cnt = len(idx)
                exp = max(ws) - min(ws) + 1
                losses.append(max(0.0, (exp - cnt) / exp * 100.0) if exp > 0 else 0.0)
                rates.append(cnt / win_s)
                lats.append(pctl(wl, 0.5) / 1e6)
        return {
            "lat_med_ms": round(_median(lats), 3) if lats else None,
            "lat_p99_ms": round(pctl([x for sj in sub_jsons if sj for t in topics
                                      for x in _win_lat(sj, t, w0, w1)], 0.99) / 1e6, 3)
                           if any(sj for sj in sub_jsons) else None,
            "loss_pct": round(_avg(losses), 3) if losses else None,
            "delivered_rate_each": round(_avg(rates), 2) if rates else None,
        }

    return {"img": family(img_t), "num": family(num_t)}


def _win_lat(sj, t, w0, w1):
    rec = sj["per_topic"].get(t)
    if not rec:
        return []
    return [rec["lat_ns"][k] for k in range(len(rec["recv_ns"])) if w0 <= rec["recv_ns"][k] <= w1]


# --------------------------------------------------------------------------- bag cell
def run_bag_cell(cfg, topics, rate_mult, fanout, trial, router_cid):
    D.cleanup_bench()
    time.sleep(3)
    tag = f"bag_{cfg}_r{rate_mult}_f{fanout}_t{trial}"
    for f in glob.glob(f"{TMP}/{tag}_*"):
        os.remove(f)
    config = CONFIGS[cfg]
    tstr = ",".join(topics)

    sub_names = [f"senoh-sub-{i}" for i in range(fanout)]
    cids = {}
    for i, name in enumerate(sub_names):
        cids[name] = D.docker_run(name, config, [
            "python3", "/ws/bench/sub_bag.py", "--topics", tstr,
            "--duration", "80", "--out", f"/ws/results/tmp/{tag}_sub{i}.json",
            "--ready", f"/ws/results/tmp/{tag}_sub{i}.ready"])
    _wait_ready([f"{TMP}/{tag}_sub{i}.ready" for i in range(fanout)])
    sub_rmws = [_read(f"{TMP}/{tag}_sub{i}.ready") for i in range(fanout)]

    lo_baseline = measure_lo_baseline()  # subs idle, before player -> clean baseline
    # Player: senoh- container, same image/code for all configs (neutral), CPU
    # accounted like the zenoh router. Mount kairos data READ-ONLY.
    player_cid = docker_run_ro(
        "senoh-player", config,
        # BAG must precede --topics: the flag is greedy (nargs) and would swallow
        # the positional bag path, yielding "no input bags were provided".
        ["ros2", "bag", "play", BAG, "--loop", "-r", str(rate_mult),
         "--topics", *topics],
        ro_mount=(DATA_MOUNT, "/data"))

    names_cids = dict(cids)
    names_cids["senoh-player"] = player_cid
    win = sample_window(names_cids, router_cid, cfg in ZENOH, warmup=14.0, window=20.0,
                        lo_baseline=lo_baseline)

    D.docker_stop(sub_names, grace=15)
    sub_jsons = [D._load_json(f"{TMP}/{tag}_sub{i}.json", timeout=15) for i in range(fanout)]
    D.docker_rm(["senoh-player"] + sub_names)

    stats = _bag_stats(sub_jsons, topics, win["w0_ns"], win["w1_ns"], win["win_s"])
    return {
        "family": "bag", "config": cfg, "rate_mult": rate_mult, "fanout": fanout,
        "trial": trial, "expected_rmw": config["rmw"], "sub_rmw": sub_rmws,
        "cpu_player": win["cpu"].get("senoh-player"),
        "cpu_sub_each": _avg([win["cpu"][n] for n in sub_names]),
        "cpu_sub_total": round(sum(win["cpu"][n] for n in sub_names if win["cpu"][n]), 2),
        "cpu_router": win["cpu_router"],
        "lo_MBps": win["lo_MBps"], "lo_net_MBps": win["lo_net_MBps"],
        "host_idle_pct": win["host_idle_pct"], "idle_low": win["idle_low"],
        "window_s": round(win["win_s"], 3), "per_topic": stats,
    }


def _bag_stats(sub_jsons, topics, w0, w1, win_s):
    out = {}
    for t in topics:
        # aggregate across subscribers: use sub 0 for jitter, sum sizes for bw per-sub avg
        per_sub_rate, per_sub_bw, jit = [], [], None
        for sj in sub_jsons:
            if not sj:
                continue
            rec = sj["per_topic"].get(t)
            if not rec or not rec["recv_ns"]:
                continue
            idx = [k for k in range(len(rec["recv_ns"])) if w0 <= rec["recv_ns"][k] <= w1]
            if len(idx) < 2:
                continue
            rv = [rec["recv_ns"][k] for k in idx]
            sz = [rec["size"][k] for k in idx]
            per_sub_rate.append(len(idx) / win_s)
            per_sub_bw.append(sum(sz) / 1e6 / win_s)
            if jit is None:
                deltas = [(rv[k + 1] - rv[k]) / 1e6 for k in range(len(rv) - 1)]
                sd = sorted(deltas)
                jit = {"interarrival_med_ms": round(pctl(sd, 0.5), 3),
                       "interarrival_p99_ms": round(pctl(sd, 0.99), 3),
                       "interarrival_max_ms": round(sd[-1], 3),
                       "mean_size_KB": round(_avg(sz) / 1024, 1)}
        out[t] = {"delivered_rate_each": round(_avg(per_sub_rate), 2) if per_sub_rate else 0.0,
                  "bw_MBps_each": round(_avg(per_sub_bw), 3) if per_sub_bw else 0.0,
                  **(jit or {})}
    return out


# --------------------------------------------------------------------------- qos-contrast cell
def run_qos_cell(cfg, size, rate, fanout, reliability, trial, router_cid):
    """One heavy p2p cell under a chosen reliability, to show shed-vs-backpressure."""
    D.cleanup_bench()
    time.sleep(3)
    tag = f"qos_{cfg}_{reliability}_f{fanout}_t{trial}"
    for f in glob.glob(f"{TMP}/{tag}_*"):
        os.remove(f)
    config = CONFIGS[cfg]
    sub_names = [f"senoh-sub-{i}" for i in range(fanout)]
    cids = {}
    for i, name in enumerate(sub_names):
        cids[name] = D.docker_run(name, config, [
            "python3", "/ws/bench/sub_qos.py", "--reliability", reliability,
            "--duration", "90", "--out", f"/ws/results/tmp/{tag}_sub{i}.json",
            "--ready", f"/ws/results/tmp/{tag}_sub{i}.ready"])
    _wait_ready([f"{TMP}/{tag}_sub{i}.ready" for i in range(fanout)])
    sub_rmws = [_read(f"{TMP}/{tag}_sub{i}.ready") for i in range(fanout)]

    lo_baseline = measure_lo_baseline()
    pub_dur = 35.0
    pub_cid = D.docker_run("senoh-pub", config, [
        "python3", "/ws/bench/pub_qos.py", "--reliability", reliability,
        "--size", str(size), "--rate", str(rate), "--duration", str(pub_dur),
        "--out", f"/ws/results/tmp/{tag}_pub.json"])
    names_cids = dict(cids)
    names_cids["senoh-pub"] = pub_cid
    win = sample_window(names_cids, router_cid, cfg in ZENOH, warmup=8.0, window=20.0,
                        lo_baseline=lo_baseline)

    time.sleep(max(0, pub_dur - win["win_s"] - 8 + 1))
    pub_json = D._load_json(f"{TMP}/{tag}_pub.json", timeout=10)
    D.docker_stop(sub_names, grace=15)
    sub_jsons = [D._load_json(f"{TMP}/{tag}_sub{i}.json", timeout=15) for i in range(fanout)]
    D.docker_rm(["senoh-pub"] + sub_names)

    per_sub = [D._sub_stats(sj, win["w0_ns"], win["w1_ns"], win["win_s"]) for sj in sub_jsons]
    loss = _avg([s["loss_pct"] for s in per_sub])
    deliv = _avg([s["delivered_rate"] for s in per_sub])
    lat = per_sub[0]["lat_ms"] if per_sub and per_sub[0].get("lat_ms") else None
    return {
        "family": "qos", "config": cfg, "reliability": reliability, "size": size,
        "rate": rate, "fanout": fanout, "trial": trial, "expected_rmw": config["rmw"],
        "sub_rmw": sub_rmws,
        "pub_achieved_rate": round(pub_json["achieved_rate"], 2) if pub_json else None,
        "delivered_rate": round(deliv, 2) if deliv is not None else None,
        "loss_pct": round(loss, 3) if loss is not None else None,
        "lat_ms": lat,
        "cpu_pub": win["cpu"].get("senoh-pub"),
        "cpu_sub_each": _avg([win["cpu"][n] for n in sub_names]),
        "cpu_router": win["cpu_router"],
        "lo_net_MBps": win["lo_net_MBps"], "lo_MBps": win["lo_MBps"],
        "host_idle_pct": win["host_idle_pct"], "idle_low": win["idle_low"],
        "window_s": round(win["win_s"], 3),
    }


def phase_qos(size, rate, fanout, trials=2):
    logp = _logger(f"{RESULTS}/driver2.log")
    out = open(f"{RESULTS}/qos.jsonl", "a")
    rc = D.ensure_router()
    cells = [(cfg, rel, tr) for tr in range(trials)
             for rel in ("best_effort", "reliable") for cfg in CONFIG_LIST]
    logp(f"START qos: {len(cells)} cells ({size}B@{rate} f{fanout})")
    for n, (cfg, rel, tr) in enumerate(cells, 1):
        try:
            rec = run_qos_cell(cfg, size, rate, fanout, rel, tr, rc)
            rec["rmw_ok"] = all(r == rec["expected_rmw"] for r in rec["sub_rmw"] if r)
            out.write(json.dumps(rec) + "\n"); out.flush()
            latm = rec["lat_ms"]["median"] if rec["lat_ms"] else None
            logp(f"[{n}/{len(cells)}] qos {cfg} {rel} f{fanout} t{tr} "
                 f"loss={rec['loss_pct']}% ach={rec['pub_achieved_rate']}Hz "
                 f"deliv={rec['delivered_rate']}Hz lat_med={latm}ms idle={rec['host_idle_pct']}%")
        except Exception as e:
            logp(f"[{n}/{len(cells)}] qos {cfg} {rel} ERROR: {e}"); D.cleanup_bench(); time.sleep(3)
    out.close(); logp("DONE qos"); D.cleanup_bench()


# --------------------------------------------------------------------------- small utils
def _wait_ready(ready_files, timeout=35.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if all(os.path.exists(rf) for rf in ready_files):
            return True
        time.sleep(0.3)
    return False


def _read(p):
    try:
        return open(p).read().strip()
    except FileNotFoundError:
        return None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


CONFIG_LIST = list(CONFIGS)
TRIALS = 3


def _logger(path):
    log = open(path, "a")

    def logp(m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()
    return logp


def phase_heavy(r4mb, r8mb):
    logp = _logger(f"{RESULTS}/driver2.log")
    out = open(f"{RESULTS}/cells_heavy.jsonl", "a")
    rc = D.ensure_router()
    sizes = [("4MB", 4 * 1024 * 1024, r4mb), ("8MB", 8 * 1024 * 1024, r8mb)]
    cells = [(cfg, sl, sz, rt, fo, tr)
             for tr in range(TRIALS) for (sl, sz, rt) in sizes
             for fo in (1, 4) for cfg in CONFIG_LIST]
    logp(f"START heavy: {len(cells)} cells (4MB@{r4mb} 8MB@{r8mb})")
    for n, (cfg, sl, sz, rt, fo, tr) in enumerate(cells, 1):
        try:
            rec = D.run_cell(cfg, sl, sz, rt, fo, tr, rc)
            rec["family"] = "heavy"
            rec["rmw_ok"] = all(r == rec["expected_rmw"] for r in rec["sub_rmw"] if r)
            out.write(json.dumps(rec) + "\n"); out.flush()
            logp(f"[{n}/{len(cells)}] heavy {cfg} {sl}@{rt} f{fo} t{tr} "
                 f"loss={rec['loss_pct']}% ach={rec['pub_achieved_rate']}Hz "
                 f"net-lo={rec['lo_net_MBps']} idle={rec['host_idle_pct']}%")
        except Exception as e:
            logp(f"[{n}/{len(cells)}] heavy {cfg} {sl} ERROR: {e}"); D.cleanup_bench(); time.sleep(3)
    out.close(); logp("DONE heavy"); D.cleanup_bench()


def phase_composite():
    logp = _logger(f"{RESULTS}/driver2.log")
    out = open(f"{RESULTS}/composite.jsonl", "a")
    rc = D.ensure_router()
    cells = [(cfg, fo, tr) for tr in range(TRIALS) for fo in (1, 4) for cfg in CONFIG_LIST]
    logp(f"START composite: {len(cells)} cells")
    for n, (cfg, fo, tr) in enumerate(cells, 1):
        try:
            rec = run_composite_cell(cfg, fo, tr, rc)
            rec["rmw_ok"] = all(r == rec["expected_rmw"] for r in rec["sub_rmw"] if r)
            out.write(json.dumps(rec) + "\n"); out.flush()
            logp(f"[{n}/{len(cells)}] composite {cfg} f{fo} t{tr} "
                 f"img(loss={rec['img']['loss_pct']}% lat={rec['img']['lat_med_ms']}ms) "
                 f"num(loss={rec['num']['loss_pct']}%) cpu_sub_tot={rec['cpu_sub_total']} "
                 f"net-lo={rec['lo_net_MBps']} idle={rec['host_idle_pct']}%")
        except Exception as e:
            logp(f"[{n}/{len(cells)}] composite {cfg} ERROR: {e}"); D.cleanup_bench(); time.sleep(3)
    out.close(); logp("DONE composite"); D.cleanup_bench()


def phase_bag(rate_mult):
    logp = _logger(f"{RESULTS}/driver2.log")
    out = open(f"{RESULTS}/bag.jsonl", "a")
    rc = D.ensure_router()
    cells = [(cfg, fo, tr) for tr in range(TRIALS) for fo in (1, 4) for cfg in CONFIG_LIST]
    logp(f"START bag: {len(cells)} cells (rate x{rate_mult}, {len(BAG_TOPICS)} topics)")
    for n, (cfg, fo, tr) in enumerate(cells, 1):
        try:
            rec = run_bag_cell(cfg, BAG_TOPICS, rate_mult, fo, tr, rc)
            rec["rmw_ok"] = all(r == rec["expected_rmw"] for r in rec["sub_rmw"] if r)
            out.write(json.dumps(rec) + "\n"); out.flush()
            rgb = rec["per_topic"].get(BAG_TOPICS[0], {})
            logp(f"[{n}/{len(cells)}] bag {cfg} f{fo} t{tr} "
                 f"rgb(rate={rgb.get('delivered_rate_each')}Hz jit_p99={rgb.get('interarrival_p99_ms')}ms) "
                 f"cpu_player={rec['cpu_player']} cpu_sub_tot={rec['cpu_sub_total']} "
                 f"lo={rec['lo_MBps']} idle={rec['host_idle_pct']}%")
        except Exception as e:
            logp(f"[{n}/{len(cells)}] bag {cfg} ERROR: {e}"); D.cleanup_bench(); time.sleep(3)
    out.close(); logp("DONE bag"); D.cleanup_bench()


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    if phase == "heavy":
        phase_heavy(float(sys.argv[2]), float(sys.argv[3]))
    elif phase == "composite":
        phase_composite()
    elif phase == "bag":
        phase_bag(float(sys.argv[2]))
    elif phase == "qos":
        # qos <size_bytes> <rate> <fanout>
        phase_qos(int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]))
    else:
        print("usage: driver2.py heavy <r4mb> <r8mb> | composite | bag <mult> | qos <size> <rate> <fanout>")
        sys.exit(1)
