"""Real-bag subscriber: subscribes raw (no image decode) to compressed-camera
topics and records per-topic receive time + serialized data size.

Bag messages carry no embedded publish timestamp we control, so one-way latency
isn't available; the comparison signals are receive-side inter-arrival jitter,
delivered msg/s, and bandwidth. Same code + QoS for every config (neutral).
"""
import argparse
import json
import signal
import time

import rclpy
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from rclpy.utilities import get_rmw_implementation_identifier
from sensor_msgs.msg import CompressedImage

from common import make_qos

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
    node = Node("senoh_bag_sub")

    topics = args.topics.split(",")
    data = {t: {"recv_ns": [], "size": []} for t in topics}

    def make_cb(topic):
        rec = data[topic]

        def cb(msg: CompressedImage) -> None:
            rec["recv_ns"].append(time.monotonic_ns())
            rec["size"].append(len(msg.data))

        return cb

    for t in topics:
        node.create_subscription(CompressedImage, t, make_cb(t), make_qos())

    with open(args.ready, "w") as f:
        f.write(get_rmw_implementation_identifier())

    t_end = time.monotonic() + args.duration
    while time.monotonic() < t_end and not _STOP["flag"]:
        rclpy.spin_once(node, timeout_sec=0.1)

    with open(args.out, "w") as f:
        json.dump({"role": "bag_sub", "rmw": get_rmw_implementation_identifier(),
                   "per_topic": data}, f)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
