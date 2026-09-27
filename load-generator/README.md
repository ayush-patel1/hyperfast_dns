# load-generator — C++ open-loop DNS traffic generator

`hfdns-bench` supports fixed, ramp, burst, and Poisson arrivals, per-region
source addresses, Zipf-distributed query mixes, multiple workers, and
coordinated-omission-correct latency measurement. It reports its own saturation.

**It is for defensive testing of the local environment only.** It refuses any
target outside loopback and private/Docker ranges.

- `src/`: implementation
- `scenarios/`: traffic pattern definitions (normal, flash crowd, regional spike,
  single-client burst, concentrated QNAMEs, high NXDOMAIN, degradation, outage,
  mixed burst)

Implemented in Milestone 10.
