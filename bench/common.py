"""Shared payload + QoS for the transport benchmark.

Neutrality: this exact code runs for every RMW. Only RMW_IMPLEMENTATION and the
per-config transport files (passed via env) differ between configs.

Payload layout (little-endian), packed into the first 16 bytes of a uint8[] blob:
    uint64 seq          message sequence number (per publisher)
    uint64 t_pub_ns     CLOCK_MONOTONIC nanoseconds set immediately before publish

CLOCK_MONOTONIC is host-global (Docker uses no time namespace by default), so a
subscriber in a separate container computes a valid one-way delta on the same clock.
"""
import struct

from rclpy.qos import QoSProfile, QoSHistoryPolicy, QoSReliabilityPolicy

HEADER = struct.Struct("<QQ")  # seq, t_pub_ns
HEADER_SIZE = HEADER.size  # 16


def make_qos(depth: int = 10) -> QoSProfile:
    """Fixed QoS for ALL configs: BEST_EFFORT + KEEP_LAST + depth.

    BEST_EFFORT is required for loss% to measure transport loss (under RELIABLE
    you would measure blocking/history overwrite instead). It also matches the
    kairos live monitor/stream path that motivated the middleware question. The
    recorder's RELIABLE path is intentionally out of scope for these numbers.
    """
    return QoSProfile(
        reliability=QoSReliabilityPolicy.BEST_EFFORT,
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=depth,
    )


def pack_header(buf: bytearray, seq: int, t_pub_ns: int) -> None:
    HEADER.pack_into(buf, 0, seq, t_pub_ns)


def unpack_header(data) -> tuple[int, int]:
    return HEADER.unpack(bytes(data[:HEADER_SIZE]))
