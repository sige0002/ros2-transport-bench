#!/usr/bin/env bash
# Falsification experiments requested by the adversarial review (see REVIEW.md):
#   A. rmem control  : raise net.core.{r,w}mem_{max,default} to 64MiB and re-run the
#      DDS best_effort headline cells (4MB@5Hz, 10MB@30Hz; fanout 1). If no-SHM loss
#      collapses, the headline loss is a kernel-default artifact on the UDP path.
#      fastdds_shm is the control-of-the-control: its loss must NOT move (no UDP path).
#   B. LARGE_DATA    : FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA (TCP+SHM builtin profile),
#      kernel back at defaults. Same-substrate comparison vs zenoh-over-TCP.
# Sysctl writes go through a privileged container sharing the host netns; original
# values are restored on exit no matter what.
set -e
cd "$(dirname "$0")"

SYSCTL_IMG=senoh-bench:jazzy
ORIG=$(sysctl -n net.core.rmem_max net.core.rmem_default net.core.wmem_max net.core.wmem_default | tr '\n' ' ')
read -r OR_MAX OR_DEF OW_MAX OW_DEF <<<"$ORIG"
restore() {
  docker run --rm --privileged --network=host "$SYSCTL_IMG" \
    sysctl -w net.core.rmem_max="$OR_MAX" net.core.rmem_default="$OR_DEF" \
              net.core.wmem_max="$OW_MAX" net.core.wmem_default="$OW_DEF" >/dev/null
  echo "[sysctl] restored: rmem_max=$(sysctl -n net.core.rmem_max) rmem_default=$(sysctl -n net.core.rmem_default)"
}
trap restore EXIT

echo "[expA] raising kernel buffers to 64MiB (was rmem_max=$OR_MAX rmem_default=$OR_DEF)"
docker run --rm --privileged --network=host "$SYSCTL_IMG" \
  sysctl -w net.core.rmem_max=67108864 net.core.rmem_default=67108864 \
            net.core.wmem_max=67108864 net.core.wmem_default=67108864 >/dev/null
sysctl -n net.core.rmem_max net.core.rmem_default

python3 - <<'EOF'
import json
import time
import driver as D

rc = D.ensure_router()
out = open(f"{D.RESULTS}/cells_rmem.jsonl", "a")
points = [("4MB", 4 * 1024 * 1024, 5.0), ("10MB", 10 * 1024 * 1024, 30.0)]
cells = [(cfg, sl, sz, rt, tr) for tr in (7, 8) for (sl, sz, rt) in points
         for cfg in ("fastdds_shm", "fastdds_noshm", "cyclone_noshm")]
for n, (cfg, sl, sz, rt, tr) in enumerate(cells, 1):
    try:
        rec = D.run_cell(cfg, sl, sz, rt, 1, tr, rc)
        rec["family"] = "rmem_tuned_64M"
        rec["rmw_ok"] = all(r == rec["expected_rmw"] for r in rec["sub_rmw"] if r)
        out.write(json.dumps(rec) + "\n"); out.flush()
        print(f"[expA {n}/{len(cells)}] {cfg} {sl}@{rt} t{tr} loss={rec['loss_pct']}% "
              f"deliv={rec['delivered_rate']}Hz net-lo={rec['lo_net_MBps']} idle={rec['host_idle_pct']}%",
              flush=True)
    except Exception as e:
        print(f"[expA {n}/{len(cells)}] {cfg} {sl} ERROR: {e}", flush=True)
        D.cleanup_bench(); time.sleep(3)
out.close()
D.cleanup_bench()
EOF

restore
trap - EXIT

python3 - <<'EOF'
import json
import time
import driver as D

D.CONFIGS["fastdds_ld"] = {"rmw": "rmw_fastrtps_cpp",
                           "env": {"FASTDDS_BUILTIN_TRANSPORTS": "LARGE_DATA"}}
rc = D.ensure_router()
out = open(f"{D.RESULTS}/cells_ld.jsonl", "a")
points = [("4MB", 4 * 1024 * 1024, 5.0), ("10MB", 10 * 1024 * 1024, 30.0)]
cells = [("fastdds_ld", sl, sz, rt, fo, tr) for tr in (7, 8)
         for (sl, sz, rt) in points for fo in (1, 4)]
for n, (cfg, sl, sz, rt, fo, tr) in enumerate(cells, 1):
    try:
        rec = D.run_cell(cfg, sl, sz, rt, fo, tr, rc)
        rec["family"] = "fastdds_large_data"
        rec["rmw_ok"] = all(r == rec["expected_rmw"] for r in rec["sub_rmw"] if r)
        out.write(json.dumps(rec) + "\n"); out.flush()
        lat = rec["lat_ms"]["median"] if rec.get("lat_ms") else None
        print(f"[expB {n}/{len(cells)}] fastdds_ld {sl}@{rt} f{fo} t{tr} loss={rec['loss_pct']}% "
              f"deliv={rec['delivered_rate']}Hz lat={lat}ms net-lo={rec['lo_net_MBps']} "
              f"idle={rec['host_idle_pct']}%", flush=True)
    except Exception as e:
        print(f"[expB {n}/{len(cells)}] fastdds_ld {sl} ERROR: {e}", flush=True)
        D.cleanup_bench(); time.sleep(3)
out.close()
D.cleanup_bench()
EOF

echo "FALSIFICATION DONE"
