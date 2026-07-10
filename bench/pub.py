"""Benchmark publisher: publishes a fixed-size uint8[] blob at a fixed rate.

Runs for a fixed wall-clock duration, then writes a small JSON summary and exits.
The measurement window is selected post-hoc by the driver on the shared monotonic
timeline, so the publisher just needs to run long enough to cover it.
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
    ap.add_argument("--topic", default="/bench")
    ap.add_argument("--size", type=int, required=True)  # bytes
    ap.add_argument("--rate", type=float, required=True)  # Hz
    ap.add_argument("--duration", type=float, required=True)  # seconds
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rclpy.init()
    node = Node("senoh_pub")
    pub = node.create_publisher(UInt8MultiArray, args.topic, make_qos())

    # Pre-allocate the payload once; only the 16-byte header changes per message.
    buf = bytearray(args.size)
    msg = UInt8MultiArray()

    period = 1.0 / args.rate
    t_end = time.monotonic() + args.duration
    next_t = time.monotonic()
    seq = 0
    published = 0
    t_first = None
    t_last = None

    # Busy-ish paced loop: sleep to the next deadline, spin briefly for callbacks.
    while time.monotonic() < t_end:
        now = time.monotonic()
        if now < next_t:
            dt = next_t - now
            # Coarse sleep, then let the deadline pass without oversleeping the tail.
            if dt > 0.002:
                time.sleep(dt - 0.001)
            continue
        pack_header(buf, seq, time.monotonic_ns())
        msg.data = array.array("B", buf)
        pub.publish(msg)
        published += 1
        if t_first is None:
            t_first = time.monotonic()
        t_last = time.monotonic()
        seq += 1
        next_t += period
        # If we fell badly behind (host stall), resync to avoid a burst catch-up.
        if time.monotonic() - next_t > 0.5:
            next_t = time.monotonic() + period

    span = (t_last - t_first) if (t_first and t_last and t_last > t_first) else 0.0
    achieved = (published - 1) / span if span > 0 else 0.0
    with open(args.out, "w") as f:
        json.dump(
            {
                "role": "pub",
                "size": args.size,
                "target_rate": args.rate,
                "published": published,
                "duration": args.duration,
                "achieved_rate": achieved,
            },
            f,
        )
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
