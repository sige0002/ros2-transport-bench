## SHM verification — NET loopback MB/s (baseline-subtracted), fanout=1

net-lo ~0 vs payload => SHM engaged. net-lo ~= payload => UDP/TCP loopback. (host baseline ~116 MB/s; net-lo noise ~+/-20, so trust large-payload cells.)

| config | 256B(pay 0.026) | 40KB(pay 1.024) | 1MB(pay 10.486) | 4MB(pay 20.972) |
|---|---|---|---|---|
| Fast DDS (SHM) | 0.0 | 2.627 | 2.145 | 0.0 |
| Fast DDS (no-SHM) | 0.044 | -0.378 | 10.468 | 21.039 |
| Cyclone (no-SHM) | 0.036 | 1.032 | 11.463 | 15.518 |
| Zenoh (no-SHM) | 0.042 | 0.291 | 6.228 | 21.166 |
| Zenoh (SHM) | 0.241 | 0.004 | 0.002 | 1.547 |

## SHM verification — NET loopback MB/s (baseline-subtracted), fanout=4

net-lo ~0 vs payload => SHM engaged. net-lo ~= payload => UDP/TCP loopback. (host baseline ~116 MB/s; net-lo noise ~+/-20, so trust large-payload cells.)

| config | 256B(pay 0.102) | 40KB(pay 4.096) | 1MB(pay 41.943) | 4MB(pay 83.886) |
|---|---|---|---|---|
| Fast DDS (SHM) | -0.008 | 0.0 | -0.011 | 18.422 |
| Fast DDS (no-SHM) | 0.981 | 4.092 | 40.319 | 88.031 |
| Cyclone (no-SHM) | -0.002 | 0.015 | -0.003 | -0.004 |
| Zenoh (no-SHM) | -0.549 | 3.192 | 42.034 | 84.086 |
| Zenoh (SHM) | 0.169 | -2.802 | 0.007 | 0.004 |

Fast DDS /dev/shm segment delta (fanout=1): Fast DDS (SHM) 4MB=8, Fast DDS (no-SHM) 4MB=0


## Latency median / p99 (ms), fanout=1

| config | 256B med/p99 | 40KB med/p99 | 1MB med/p99 | 4MB med/p99 |
|---|---|---|---|---|
| Fast DDS (SHM) | 0.335/1.132 | 0.53/1.527 | 2.211/5.733 | 5.96/11.946 |
| Fast DDS (no-SHM) | 0.362/1.14 | 0.544/1.671 | 2.707/5.074 | 7.688/15.054 |
| Cyclone (no-SHM) | 0.295/0.934 | 0.492/1.495 | 2.467/6.225 | 9.013/15.516 |
| Zenoh (no-SHM) | 0.445/1.281 | 0.628/1.75 | 2.914/6.539 | 8.186/15.474 |
| Zenoh (SHM) | 0.448/1.328 | 0.703/2.051 | 2.555/5.41 | 6.163/12.758 |

## Loss % / delivered Hz, fanout=1

| config | 256B | 40KB | 1MB | 4MB |
|---|---|---|---|---|
| Fast DDS (SHM) | 0.0%/100.0 | 0.0%/25.01 | 63.731%/3.5 | 72.222%/1.1 |
| Fast DDS (no-SHM) | 0.0%/100.0 | 0.0%/25.01 | 70.558%/2.9 | 74.419%/1.2 |
| Cyclone (no-SHM) | 0.0%/100.0 | 0.0%/25.01 | 43.147%/5.6 | 55.102%/2.2 |
| Zenoh (no-SHM) | 0.0%/100.01 | 0.0%/25.01 | 0.0%/10.0 | 0.0%/5.0 |
| Zenoh (SHM) | 0.0%/100.0 | 0.0%/25.01 | 0.0%/10.0 | 0.0%/5.0 |

## CPU % of one core (pub / sub-each / router), fanout=1

| config | 256B | 40KB | 1MB | 4MB |
|---|---|---|---|---|
| Fast DDS (SHM) | 10.47/4.71 | 2.88/1.75 | 2.1/1.29 | 1.39/1.44 |
| Fast DDS (no-SHM) | 10.72/4.69 | 2.91/1.8 | 2.2/1.41 | 1.53/1.75 |
| Cyclone (no-SHM) | 10.32/4.34 | 2.87/1.72 | 1.89/2.2 | 2.08/2.71 |
| Zenoh (no-SHM) | 11.14/5.02/0.0 | 3.05/1.81/0.0 | 2.72/2.85/0.0 | 2.21/4.91/0.0 |
| Zenoh (SHM) | 11.19/5.03/0.0 | 3.2/1.98/0.0 | 2.11/2.47/0.0 | 1.22/4.01/0.0 |

## Latency median / p99 (ms), fanout=4

| config | 256B med/p99 | 40KB med/p99 | 1MB med/p99 | 4MB med/p99 |
|---|---|---|---|---|
| Fast DDS (SHM) | 0.358/1.11 | 0.546/1.571 | 2.784/5.499 | 7.61/14.554 |
| Fast DDS (no-SHM) | 0.373/1.12 | 0.556/1.667 | 3.67/6.921 | 12.196/18.215 |
| Cyclone (no-SHM) | 0.311/0.977 | 0.542/1.516 | 3.792/6.125 | 12.74/20.11 |
| Zenoh (no-SHM) | 0.494/1.369 | 0.696/2.021 | 3.831/8.37 | 9.057/11.852 |
| Zenoh (SHM) | 0.463/1.321 | 0.697/1.905 | 2.797/5.225 | 5.286/6.521 |

## Loss % / delivered Hz, fanout=4

| config | 256B | 40KB | 1MB | 4MB |
|---|---|---|---|---|
| Fast DDS (SHM) | 0.0%/100.01 | 0.0%/25.01 | 30.665%/6.925 | 53.5%/2.312 |
| Fast DDS (no-SHM) | 0.0%/100.01 | 0.0%/25.01 | 11.625%/8.838 | 27.413%/3.612 |
| Cyclone (no-SHM) | 0.0%/100.01 | 0.0%/25.01 | 3.875%/9.613 | 13.25%/4.338 |
| Zenoh (no-SHM) | 0.0%/100.0 | 0.0%/24.96 | 0.0%/10.0 | 0.0%/5.0 |
| Zenoh (SHM) | 0.0%/100.0 | 0.0%/25.01 | 0.0%/10.01 | 0.0%/5.0 |

## CPU % of one core (pub / sub-each / router), fanout=4

| config | 256B | 40KB | 1MB | 4MB |
|---|---|---|---|---|
| Fast DDS (SHM) | 10.68/4.68 | 2.96/1.752 | 2.43/1.96 | 1.72/2.417 |
| Fast DDS (no-SHM) | 10.98/4.56 | 3.05/1.725 | 3.03/2.547 | 3.31/4.022 |
| Cyclone (no-SHM) | 10.79/4.502 | 3.16/1.695 | 3.5/3.083 | 5.09/4.572 |
| Zenoh (no-SHM) | 11.79/5.032/0.0 | 3.36/1.86/0.0 | 4.16/3.03/0.0 | 4.39/3.802/0.0 |
| Zenoh (SHM) | 11.71/4.923/0.0 | 3.35/1.885/0.0 | 2.33/2.547/0.0 | 0.99/3.013/0.0 |
