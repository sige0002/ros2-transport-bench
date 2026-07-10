"""Benchmark subscriber: records (t_recv_ns, seq, latency_ns) for every message.

Writes a raw sample dump on exit. The driver filters samples to the measurement
window on the shared monotonic timeline and computes all statistics, so the
subscriber stays dumb and identical across configs. It also records the actual
RMW identifier so the driver can catch a silent fallback to a different RMW.
"""
import argparse
import json
import signal
import time

import rclpy
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from rclpy.utilities import get_rmw_implementation_identifier
from std_msgs.msg import UInt8MultiArray

from common import make_qos, unpack_header

_STOP = {"flag": False}


def _on_term(signum, frame):
    _STOP["flag"] = True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="/bench")
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ready", required=True)  # touched once the node is up
    args = ap.parse_args()

    # Disable rclpy's own signal handling so our SIGTERM handler (which flushes the
    # dump and exits cleanly) is the one that runs when the driver stops us.
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    node = Node("senoh_sub")

    recv_ns: list[int] = []
    seqs: list[int] = []
    lat_ns: list[int] = []

    def on_msg(msg: UInt8MultiArray) -> None:
        t = time.monotonic_ns()
        seq, t_pub = unpack_header(msg.data)
        recv_ns.append(t)
        seqs.append(seq)
        lat_ns.append(t - t_pub)

    node.create_subscription(UInt8MultiArray, args.topic, on_msg, make_qos())

    # Node is up and subscribed: signal readiness so the driver can start the
    # publisher. Actual pub/sub match happens after; the warmup absorbs it.
    with open(args.ready, "w") as f:
        f.write(get_rmw_implementation_identifier())

    t_end = time.monotonic() + args.duration
    while time.monotonic() < t_end and not _STOP["flag"]:
        rclpy.spin_once(node, timeout_sec=0.1)

    with open(args.out, "w") as f:
        json.dump(
            {
                "role": "sub",
                "rmw": get_rmw_implementation_identifier(),
                "recv_ns": recv_ns,
                "seq": seqs,
                "lat_ns": lat_ns,
            },
            f,
        )
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
