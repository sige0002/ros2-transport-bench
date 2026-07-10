#!/usr/bin/env bash
# Stage-0 cells (kairos deployment_topology.md §5.5). See stage0/README.md.
#   netns mode (default): single host, docker-emulated robot/pc namespaces.
#     Harness validation + upper-bound numbers. NOT Stage-0 GO evidence.
#   two-host mode: export STAGE0_ROBOT_IP=<robot LAN IP> and run the robot-side
#     members on the robot (see README) — same protocol over the real NIC.
# Heavy cells temporarily raise net.core.{r,w}mem to 64MiB via a privileged
# container and always restore the original values.
set -e
cd "$(dirname "$0")/.."
mkdir -p results/stage0
python3 stage0/driver_stage0.py
