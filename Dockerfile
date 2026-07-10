# Single benchmark image containing all three RMWs.
# Fast DDS (rmw_fastrtps_cpp) ships as the Jazzy default; we add Cyclone + Zenoh.
FROM ros:jazzy-ros-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-rmw-cyclonedds-cpp \
        ros-jazzy-rmw-zenoh-cpp \
        python3-numpy \
        sysstat \
        iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Record the exact package versions into the image for the report.
RUN dpkg -l | grep -E 'rmw|fastrtps|cyclonedds|zenoh' > /versions.txt || true

WORKDIR /ws
CMD ["bash"]
