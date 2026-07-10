## 10MB@30Hz point-to-point, best_effort (median of 3 trials)

| fo | config | loss% | deliv Hz | lat med ms | cpu_pub | cpu_sub_each | net-lo MB/s |
|---|---|---|---|---|---|---|---|
| 1 | Fast DDS (SHM) | 73.0 | 7.95 | 12.75 | 11.9 | 12.21 | 0.0 |
| 1 | Fast DDS (no-SHM) | 80.74 | 5.75 | 13.21 | 12.95 | 9.93 | 315.1 |
| 1 | Cyclone (no-SHM) | 79.06 | 6.25 | 16.11 | 19.11 | 14.75 | 316.3 |
| 1 | Zenoh (no-SHM) | 0.0 | 30.02 | 14.66 | 19.96 | 45.67 | 314.78 |
| 1 | Zenoh (SHM) | 0.0 | 30.01 | 11.06 | 8.21 | 33.79 | 0.01 |
| 4 | Fast DDS (SHM) | 71.36 | 8.55 | 13.92 | 14.92 | 13.77 | -0.01 |
| 4 | Fast DDS (no-SHM) | 25.09 | 22.41 | 19.95 | 28.53 | 34.69 | 1261.94 |
| 4 | Cyclone (no-SHM) | 17.94 | 24.61 | 25.9 | 60.73 | 46.19 | -0.0 |
| 4 | Zenoh (no-SHM) | 0.0 | 30.01 | 21.98 | 57.88 | 47.64 | 1260.37 |
| 4 | Zenoh (SHM) | 0.0 | 30.02 | 11.55 | 8.4 | 36.25 | 0.02 |

## 10MB@30Hz QoS contrast, fanout=1 (median of 2 trials)

| config | QoS | loss% | deliv Hz | lat med/p99 ms |
|---|---|---|---|---|
| Fast DDS (SHM) | best_effort | 87.71 | 3.6 | 12.32/14.88 |
| Fast DDS (SHM) | reliable | 0.0 | 29.92 | 31.33/99.76 |
| Fast DDS (no-SHM) | best_effort | 79.34 | 5.72 | 13.82/15.38 |
| Fast DDS (no-SHM) | reliable | 0.0 | 30.01 | 32.78/112.12 |
| Cyclone (no-SHM) | best_effort | 74.92 | 7.47 | 15.08/17.94 |
| Cyclone (no-SHM) | reliable | 0.08 | 29.98 | 17.26/221.75 |
| Zenoh (no-SHM) | best_effort | 0.0 | 29.99 | 14.81/17.29 |
| Zenoh (no-SHM) | reliable | 0.0 | 30.01 | 15.14/17.57 |
| Zenoh (SHM) | best_effort | 0.0 | 30.04 | 11.16/12.28 |
| Zenoh (SHM) | reliable | 0.0 | 30.0 | 10.89/12.97 |

## 10MB@30Hz QoS contrast, fanout=4 (median of 2 trials)

| config | QoS | loss% | deliv Hz | lat med/p99 ms |
|---|---|---|---|---|
| Fast DDS (SHM) | best_effort | 67.23 | 9.76 | 14.15/16.26 |
| Fast DDS (SHM) | reliable | 0.0 | 30.01 | 22.15/43.61 |
| Fast DDS (no-SHM) | best_effort | 43.82 | 16.77 | 18.76/22.89 |
| Fast DDS (no-SHM) | reliable | 0.0 | 30.02 | 21.32/32.43 |
| Cyclone (no-SHM) | best_effort | 15.79 | 25.24 | 26.17/30.38 |
| Cyclone (no-SHM) | reliable | 0.0 | 30.02 | 25.68/38.9 |
| Zenoh (no-SHM) | best_effort | 0.0 | 30.01 | 18.21/22.37 |
| Zenoh (no-SHM) | reliable | 0.0 | 29.99 | 16.75/19.61 |
| Zenoh (SHM) | best_effort | 0.0 | 30.0 | 11.06/12.78 |
| Zenoh (SHM) | reliable | 0.0 | 30.01 | 11.19/12.75 |
