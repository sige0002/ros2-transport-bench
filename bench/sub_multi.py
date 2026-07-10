"""Multi-topic subscriber (UInt8MultiArray) for the composite scenario.

Subscribes to every listed topic and records per-topic (recv_ns, seq, lat_ns) so
the driver can compute per-topic and aggregate latency/loss within the window.
Same SIGTERM-flush contract as sub.py.
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
    ap.add_argument("--topics", required=True)  # comma-separated
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ready", required=True)
    args = ap.parse_args()

    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    node = Node("senoh_multi_sub")

    topics = args.topics.split(",")
    data = {t: {"recv_ns": [], "seq": [], "lat_ns": []} for t in topics}

    def make_cb(topic):
        rec = data[topic]

        def cb(msg: UInt8MultiArray) -> None:
            t = time.monotonic_ns()
            seq, t_pub = unpack_header(msg.data)
            rec["recv_ns"].append(t)
            rec["seq"].append(seq)
            rec["lat_ns"].append(t - t_pub)

        return cb

    for t in topics:
        node.create_subscription(UInt8MultiArray, t, make_cb(t), make_qos())

    with open(args.ready, "w") as f:
        f.write(get_rmw_implementation_identifier())

    t_end = time.monotonic() + args.duration
    while time.monotonic() < t_end and not _STOP["flag"]:
        rclpy.spin_once(node, timeout_sec=0.05)

    with open(args.out, "w") as f:
        json.dump({"role": "multi_sub", "rmw": get_rmw_implementation_identifier(),
                   "per_topic": data}, f)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
