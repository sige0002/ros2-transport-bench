#!/usr/bin/env python3
"""Stage-0 measurement cells for kairos deployment_topology.md §5.5 (Option C verdict).

Measures, per payload profile, the gates the arbiter defined:
  G1  F(T) >= 0.99 with an INDEPENDENT denominator (publisher driver stats,
      never a co-located best_effort subscriber).
  G2  source-integrity guard: attaching the cross-boundary bridge (and its
      downstream consumers) must not reduce the publisher's achieved rate.
      Includes the risky reliable-writer pairing under a constrained link.
  G3  single-session boundary: robot-namespace eth0 bytes ~= 1x payload with
      the bridge up (and ~= 0 in baseline => DDS loopback pinning holds).
  G4  native-peer compatibility probe: can an rmw_zenoh subscriber consume the
      zenoh-bridge-ros2dds session directly? (Outcome is a finding either way.)

Two runtime modes share this protocol:
  - netns mode (this script, single host): two docker namespaces joined by a
    docker bridge network. Validates the harness and yields UPPER-BOUND numbers.
    It does NOT satisfy the Stage-0 GO gate, which requires a real NIC/switch.
  - two-host mode: run the same members with network_mode:host on robot and PC,
    pointing STAGE0_ROBOT_IP at the robot's LAN IP (see README).

Heavy (uncompressed) cells run twice: with default kernel buffers (expected to
FAIL even the local recorder, documenting the runbook knob) and with rmem/wmem
raised to 64MiB (restored afterwards).
"""
import glob
import json
import os
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = f"{WS}/results/stage0"
TMP = f"{RESULTS}/tmp"
CFG = "/ws/stage0/configs"

NET = "stage0net"
CORE = {"robot": "stage0-robot", "pc": "stage0-pc"}
IMAGE = "senoh-bench:jazzy"
BRIDGE_IMAGE = "eclipse/zenoh-bridge-ros2dds:latest"
DOMAIN = {"robot": "88", "pc": "89"}
MEMBERS = ["s0-pub", "s0-rec", "s0-egress", "s0-ingress", "s0-pcsub", "s0-natsub"]

WARMUP = 8.0
WINDOW = 20.0
PUB_DUR = 35.0
SUB_DUR = 90.0
READY_TIMEOUT = 30.0

PROFILES = {
    "cam_comp": {"size": 120_000, "rate": 30.0},          # ~3.4MB/s: compressed-depth-like
    "cam_uncomp": {"size": 10 * 1024 * 1024, "rate": 30.0},  # 300MB/s: uncompressed spec point
}
F_GATE = 0.99


def sh(args, timeout=90, check=False):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()}")
    return r


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(f"{RESULTS}/stage0.log", "a") as f:
        f.write(line + "\n")


# --------------------------------------------------------------- infrastructure
def ensure_infra():
    os.makedirs(TMP, exist_ok=True)
    sh(["docker", "network", "create", NET])
    for core in CORE.values():
        r = sh(["docker", "ps", "--format", "{{.Names}}"])
        if core not in r.stdout.split():
            sh(["docker", "run", "-d", "--rm", "--name", core, "--network", NET,
                "--cap-add", "NET_ADMIN", IMAGE, "sleep", "infinity"], check=True)
    r = sh(["docker", "inspect", "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", CORE["robot"]], check=True)
    return os.environ.get("STAGE0_ROBOT_IP", r.stdout.strip())


def cleanup_members():
    sh(["docker", "rm", "-f"] + MEMBERS)
    time.sleep(2)


def teardown():
    cleanup_members()
    sh(["docker", "rm", "-f"] + list(CORE.values()))
    sh(["docker", "network", "rm", NET])


def run_member(name, ns, image, cmd, env=None, memlock=True):
    args = ["docker", "run", "-d", "--rm", "--name", name,
            "--network", f"container:{CORE[ns]}", "-v", f"{WS}:/ws"]
    if memlock:
        args += ["--ulimit", "memlock=-1"]
    for k, v in (env or {}).items():
        args += ["-e", f"{k}={v}"]
    sh(args + [image] + cmd, check=True)


def dds_env(ns, rmw="rmw_fastrtps_cpp"):
    return {"ROS_DOMAIN_ID": DOMAIN[ns], "RMW_IMPLEMENTATION": rmw,
            "FASTRTPS_DEFAULT_PROFILES_FILE": f"{CFG}/fastdds_lo.xml"}


def eth0_tx(ns):
    r = sh(["docker", "exec", CORE[ns], "cat", "/sys/class/net/eth0/statistics/tx_bytes"])
    return int(r.stdout.strip())


def shape(ns, mbit):
    sh(["docker", "exec", CORE[ns], "tc", "qdisc", "del", "dev", "eth0", "root"])
    if mbit:
        sh(["docker", "exec", CORE[ns], "tc", "qdisc", "add", "dev", "eth0", "root",
            "tbf", "rate", f"{mbit}mbit", "burst", "1mbit", "latency", "400ms"], check=True)


def set_kernel_buffers(nbytes):
    """None restores the recorded originals. Uses a privileged container (host netns)."""
    global _orig_buf
    keys = ["net.core.rmem_max", "net.core.rmem_default",
            "net.core.wmem_max", "net.core.wmem_default"]
    if nbytes is None:
        vals = _orig_buf
    else:
        if "_orig_buf" not in globals():
            r = sh(["sysctl", "-n"] + keys, check=True)
            _orig_buf = [int(x) for x in r.stdout.split()]
        vals = [nbytes] * 4
    sh(["docker", "run", "--rm", "--privileged", "--network=host", IMAGE,
        "sysctl", "-w"] + [f"{k}={v}" for k, v in zip(keys, vals)], check=True)


# --------------------------------------------------------------- bridges
def start_egress():
    run_member("s0-egress", "robot", BRIDGE_IMAGE,
               ["-d", DOMAIN["robot"], "-l", "tcp/0.0.0.0:7447", "--no-multicast-scouting"],
               env={"CYCLONEDDS_URI": f"file://{CFG}/cyclonedds_lo.xml"})


def start_ingress(robot_ip):
    run_member("s0-ingress", "pc", BRIDGE_IMAGE,
               ["-d", DOMAIN["pc"], "-e", f"tcp/{robot_ip}:7447", "--no-multicast-scouting"],
               env={"CYCLONEDDS_URI": f"file://{CFG}/cyclonedds_lo.xml"})


# --------------------------------------------------------------- one cell
def _wait_ready(files):
    t0 = time.monotonic()
    while time.monotonic() - t0 < READY_TIMEOUT:
        if all(os.path.exists(f) for f in files):
            return True
        time.sleep(0.3)
    return False


def _load_json(path, timeout=20):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.4)
    return None


def _win_count(sj, w0, w1):
    if not sj:
        return 0, None
    recv, lat = sj["recv_ns"], sj["lat_ns"]
    idx = [i for i in range(len(recv)) if w0 <= recv[i] <= w1]
    lat_med = None
    if idx:
        ls = sorted(lat[i] for i in idx)
        lat_med = round(ls[len(ls) // 2] / 1e6, 3)
    return len(idx), lat_med


def run_cell(tag, profile, bridge=False, pc_sub=False, reliability=None, shape_mbit=None,
             robot_ip=None):
    """One measurement window. Returns the record (also appended to stage0.jsonl)."""
    cleanup_members()
    for f in glob.glob(f"{TMP}/{tag}_*"):
        os.remove(f)
    shape("robot", shape_mbit)
    p = PROFILES[profile]
    qos_suffix = ["--reliability", reliability] if reliability else []
    sub_script = "sub_qos.py" if reliability else "sub.py"
    pub_script = "pub_qos.py" if reliability else "pub.py"

    ready = []
    run_member("s0-rec", "robot", IMAGE,
               ["python3", f"/ws/bench/{sub_script}", "--duration", str(SUB_DUR),
                "--out", f"/ws/results/stage0/tmp/{tag}_rec.json",
                "--ready", f"/ws/results/stage0/tmp/{tag}_rec.ready"] + qos_suffix,
               env=dds_env("robot"))
    ready.append(f"{TMP}/{tag}_rec.ready")
    if bridge:
        start_egress()
    if pc_sub:
        start_ingress(robot_ip)
        run_member("s0-pcsub", "pc", IMAGE,
                   ["python3", f"/ws/bench/{sub_script}", "--duration", str(SUB_DUR),
                    "--out", f"/ws/results/stage0/tmp/{tag}_pc.json",
                    "--ready", f"/ws/results/stage0/tmp/{tag}_pc.ready"] + qos_suffix,
                   env=dds_env("pc"))
        ready.append(f"{TMP}/{tag}_pc.ready")
    ready_ok = _wait_ready(ready)
    time.sleep(4)  # discovery + bridge route setup settle

    tx0 = eth0_tx("robot")
    run_member("s0-pub", "robot", IMAGE,
               ["python3", f"/ws/bench/{pub_script}", "--size", str(p["size"]),
                "--rate", str(p["rate"]), "--duration", str(PUB_DUR),
                "--out", f"/ws/results/stage0/tmp/{tag}_pub.json"] + qos_suffix,
               env=dds_env("robot"))
    t_pub = time.monotonic()
    while time.monotonic() < t_pub + WARMUP:
        time.sleep(0.05)
    w0 = time.monotonic_ns()
    txw0 = eth0_tx("robot")
    while time.monotonic() < t_pub + WARMUP + WINDOW:
        time.sleep(0.05)
    w1 = time.monotonic_ns()
    txw1 = eth0_tx("robot")
    win_s = (w1 - w0) / 1e9

    sh(["docker", "stop", "-t", "15", "s0-rec"] + (["s0-pcsub"] if pc_sub else []), timeout=60)
    pub_j = _load_json(f"{TMP}/{tag}_pub.json", timeout=PUB_DUR)
    rec_j = _load_json(f"{TMP}/{tag}_rec.json")
    pc_j = _load_json(f"{TMP}/{tag}_pc.json") if pc_sub else None
    cleanup_members()

    r_pub = pub_j["achieved_rate"] if pub_j else None
    n_rec, lat_rec = _win_count(rec_j, w0, w1)
    n_pc, lat_pc = _win_count(pc_j, w0, w1)
    payload_mbps = p["size"] * p["rate"] / 1e6
    rec = {
        "tag": tag, "profile": profile, "size": p["size"], "rate": p["rate"],
        "bridge": bridge, "pc_sub": pc_sub, "reliability": reliability or "best_effort",
        "shape_mbit": shape_mbit, "ready_ok": ready_ok, "window_s": round(win_s, 3),
        "R_pub": round(r_pub, 3) if r_pub else None,
        "F_rec": round(n_rec / (r_pub * win_s), 4) if r_pub else None,
        "F_through": round(n_pc / (r_pub * win_s), 4) if (r_pub and pc_sub) else None,
        "lat_rec_ms": lat_rec, "lat_through_ms": lat_pc,
        "eth0_tx_MBps": round((txw1 - txw0) / 1e6 / win_s, 3),
        "payload_MBps": round(payload_mbps, 3),
        "boundary_copies": round((txw1 - txw0) / 1e6 / win_s / payload_mbps, 3),
    }
    with open(f"{RESULTS}/stage0.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    log(f"{tag}: R_pub={rec['R_pub']} F_rec={rec['F_rec']} F_through={rec['F_through']} "
        f"eth0={rec['eth0_tx_MBps']}MB/s (~{rec['boundary_copies']}x payload)")
    return rec


def native_compat_cell(robot_ip):
    """G4: rmw_zenoh subscriber pointed straight at the egress bridge session."""
    tag = "natcompat_cam_comp"
    cleanup_members()
    for f in glob.glob(f"{TMP}/{tag}_*"):
        os.remove(f)
    start_egress()
    run_member("s0-natsub", "pc", IMAGE,
               ["python3", "/ws/bench/sub.py", "--duration", "45",
                "--out", f"/ws/results/stage0/tmp/{tag}_nat.json",
                "--ready", f"/ws/results/stage0/tmp/{tag}_nat.ready"],
               env={"ROS_DOMAIN_ID": DOMAIN["pc"], "RMW_IMPLEMENTATION": "rmw_zenoh_cpp",
                    "ZENOH_CONFIG_OVERRIDE":
                        f'connect/endpoints=["tcp/{robot_ip}:7447"];'
                        'scouting/multicast/enabled=false'})
    time.sleep(6)
    p = PROFILES["cam_comp"]
    run_member("s0-pub", "robot", IMAGE,
               ["python3", "/ws/bench/pub.py", "--size", str(p["size"]),
                "--rate", str(p["rate"]), "--duration", "25",
                "--out", f"/ws/results/stage0/tmp/{tag}_pub.json"],
               env=dds_env("robot"))
    time.sleep(30)
    logs = sh(["docker", "logs", "s0-natsub"], timeout=20)
    sh(["docker", "stop", "-t", "10", "s0-natsub"], timeout=30)
    nat_j = _load_json(f"{TMP}/{tag}_nat.json", timeout=10)
    n = len(nat_j["recv_ns"]) if nat_j else 0
    cleanup_members()
    verdict = "COMPATIBLE" if n > 10 else "INCOMPATIBLE (bridge pair or PC-side republish required)"
    rec = {"tag": tag, "gate": "G4_native_peer", "received": n, "verdict": verdict,
           "sub_stderr_tail": (logs.stdout + logs.stderr).splitlines()[-5:]}
    with open(f"{RESULTS}/stage0.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    log(f"{tag}: received={n} -> {verdict}")
    return rec


# --------------------------------------------------------------- main sequence
def main():
    os.makedirs(TMP, exist_ok=True)
    robot_ip = ensure_infra()
    log(f"infra up, robot_ip={robot_ip} (netns mode unless STAGE0_ROBOT_IP is set)")
    out = {"cells": []}
    try:
        # -- cam_comp (compressed-like): default kernel buffers ----------------
        for t in (0, 1):
            out["cells"].append(run_cell(f"comp_base_t{t}", "cam_comp"))
            out["cells"].append(run_cell(f"comp_through_t{t}", "cam_comp",
                                         bridge=True, pc_sub=True, robot_ip=robot_ip))
        # -- cam_uncomp: document default-kernel failure, then measure with knob
        out["cells"].append(run_cell("uncomp_base_defaultbuf_t0", "cam_uncomp"))
        set_kernel_buffers(64 * 1024 * 1024)
        try:
            for t in (0, 1):
                out["cells"].append(run_cell(f"uncomp_base_rmem64_t{t}", "cam_uncomp"))
                out["cells"].append(run_cell(f"uncomp_through_rmem64_t{t}", "cam_uncomp",
                                             bridge=True, pc_sub=True, robot_ip=robot_ip))
            # -- G2 reliable-writer guard under a constrained link -------------
            out["cells"].append(run_cell("rel_guard_base_t0", "cam_uncomp",
                                         reliability="reliable"))
            out["cells"].append(run_cell("rel_guard_bridged_shaped_t0", "cam_uncomp",
                                         bridge=True, pc_sub=True, reliability="reliable",
                                         shape_mbit=200, robot_ip=robot_ip))
        finally:
            set_kernel_buffers(None)
            log("kernel buffers restored")
        # -- G4 native peer compatibility probe --------------------------------
        out["cells"].append(native_compat_cell(robot_ip))
    finally:
        shape("robot", None)
        if os.environ.get("STAGE0_KEEP_INFRA") != "1":
            teardown()
    log("STAGE0 CELLS DONE")


if __name__ == "__main__":
    sys.exit(main())
