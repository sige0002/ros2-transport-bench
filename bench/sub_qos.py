"""QoS-parameterized subscriber (best_effort-vs-reliable contrast pass).

Identical to sub.py except reliability is selectable via --reliability. Separate
file so the base matrix's sub.py stays untouched while it runs.
"""
import argparse
import json
import signal
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSHistoryPolicy, QoSReliabilityPolicy
from rclpy.signals import SignalHandlerOptions
from rclpy.utilities import get_rmw_implementation_identifier
from std_msgs.msg import UInt8MultiArray

from common import unpack_header

_STOP = {"flag": False}


def _on_term(signum, frame):
    _STOP["flag"] = True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="/bench")
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--reliability", choices=["best_effort", "reliable"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ready", required=True)
    args = ap.parse_args()

    rel = (QoSReliabilityPolicy.RELIABLE if args.reliability == "reliable"
           else QoSReliabilityPolicy.BEST_EFFORT)
    qos = QoSProfile(reliability=rel, history=QoSHistoryPolicy.KEEP_LAST, depth=10)

    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    node = Node("senoh_sub_qos")

    recv_ns, seqs, lat_ns = [], [], []

    def on_msg(msg: UInt8MultiArray) -> None:
        t = time.monotonic_ns()
        seq, t_pub = unpack_header(msg.data)
        recv_ns.append(t)
        seqs.append(seq)
        lat_ns.append(t - t_pub)

    node.create_subscription(UInt8MultiArray, args.topic, on_msg, qos)
    with open(args.ready, "w") as f:
        f.write(get_rmw_implementation_identifier())

    t_end = time.monotonic() + args.duration
    while time.monotonic() < t_end and not _STOP["flag"]:
        rclpy.spin_once(node, timeout_sec=0.1)

    with open(args.out, "w") as f:
        json.dump({"role": "sub", "reliability": args.reliability,
                   "rmw": get_rmw_implementation_identifier(),
                   "recv_ns": recv_ns, "seq": seqs, "lat_ns": lat_ns}, f)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
