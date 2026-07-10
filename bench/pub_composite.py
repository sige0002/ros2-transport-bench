"""Composite publisher: the kairos-shaped workload in one process.

Publishes n_img image-like topics (/img0..) and n_num numeric-like topics (/num0..)
at their own rates, each carrying the seq + monotonic-timestamp header so the
subscriber can compute real one-way latency. Runs for a fixed duration, then writes
per-topic achieved rates.
"""
import argparse
import array
import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import UInt8MultiArray

from common import make_qos, pack_header


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_img", type=int, default=4)
    ap.add_argument("--img_size", type=int, default=1024 * 1024)
    ap.add_argument("--img_rate", type=float, default=25.0)
    ap.add_argument("--n_num", type=int, default=27)
    ap.add_argument("--num_size", type=int, default=256)
    ap.add_argument("--num_rate", type=float, default=50.0)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rclpy.init()
    node = Node("senoh_composite_pub")

    specs = []  # (topic, publisher, buf, period, next_deadline, seq, count)
    for i in range(args.n_img):
        t = f"/img{i}"
        specs.append({"topic": t, "pub": node.create_publisher(UInt8MultiArray, t, make_qos()),
                      "buf": bytearray(args.img_size), "period": 1.0 / args.img_rate,
                      "next": 0.0, "seq": 0, "count": 0})
    for i in range(args.n_num):
        t = f"/num{i}"
        specs.append({"topic": t, "pub": node.create_publisher(UInt8MultiArray, t, make_qos()),
                      "buf": bytearray(args.num_size), "period": 1.0 / args.num_rate,
                      "next": 0.0, "seq": 0, "count": 0})

    msg = UInt8MultiArray()
    start = time.monotonic()
    for s in specs:
        s["next"] = start
    t_end = start + args.duration

    while time.monotonic() < t_end:
        now = time.monotonic()
        soonest = min(s["next"] for s in specs)
        if soonest > now:
            dt = soonest - now
            if dt > 0.002:
                time.sleep(dt - 0.001)
            continue
        for s in specs:
            if now >= s["next"]:
                pack_header(s["buf"], s["seq"], time.monotonic_ns())
                msg.data = array.array("B", s["buf"])
                s["pub"].publish(msg)
                s["seq"] += 1
                s["count"] += 1
                s["next"] += s["period"]
                if now - s["next"] > 0.5:  # fell behind: resync, don't burst
                    s["next"] = now + s["period"]

    elapsed = time.monotonic() - start
    per_topic = {s["topic"]: {"count": s["count"], "rate": round(s["count"] / elapsed, 2)}
                 for s in specs}
    with open(args.out, "w") as f:
        json.dump({"role": "composite_pub", "elapsed": round(elapsed, 3),
                   "per_topic": per_topic}, f)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
