"""QoS-parameterized publisher (for the best_effort-vs-reliable contrast pass).

Identical to pub.py except reliability is selectable via --reliability so a single
heavy cell can show how the shed-vs-backpressure picture flips with QoS. Kept as a
separate file so the base matrix's pub.py stays untouched while it runs.
"""
import argparse
import array
import json
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSHistoryPolicy, QoSReliabilityPolicy
from std_msgs.msg import UInt8MultiArray

from common import pack_header


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="/bench")
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--reliability", choices=["best_effort", "reliable"], required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rel = (QoSReliabilityPolicy.RELIABLE if args.reliability == "reliable"
           else QoSReliabilityPolicy.BEST_EFFORT)
    qos = QoSProfile(reliability=rel, history=QoSHistoryPolicy.KEEP_LAST, depth=10)

    rclpy.init()
    node = Node("senoh_pub_qos")
    pub = node.create_publisher(UInt8MultiArray, args.topic, qos)

    buf = bytearray(args.size)
    msg = UInt8MultiArray()
    period = 1.0 / args.rate
    t_end = time.monotonic() + args.duration
    next_t = time.monotonic()
    seq = published = 0
    t_first = t_last = None

    while time.monotonic() < t_end:
        now = time.monotonic()
        if now < next_t:
            dt = next_t - now
            if dt > 0.002:
                time.sleep(dt - 0.001)
            continue
        pack_header(buf, seq, time.monotonic_ns())
        msg.data = array.array("B", buf)
        pub.publish(msg)  # may block under RELIABLE if readers backpressure
        published += 1
        if t_first is None:
            t_first = time.monotonic()
        t_last = time.monotonic()
        seq += 1
        next_t += period
        if time.monotonic() - next_t > 0.5:
            next_t = time.monotonic() + period

    span = (t_last - t_first) if (t_first and t_last and t_last > t_first) else 0.0
    achieved = (published - 1) / span if span > 0 else 0.0
    with open(args.out, "w") as f:
        json.dump({"role": "pub", "reliability": args.reliability, "size": args.size,
                   "target_rate": args.rate, "published": published,
                   "achieved_rate": achieved}, f)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
