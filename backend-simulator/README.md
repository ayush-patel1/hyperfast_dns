# backend-simulator — C++ emulated DNS POPs

`hfdns-backend` answers DNS queries (A, AAAA, CNAME, MX, TXT, NXDOMAIN with SOA,
SERVFAIL, truncated responses). Each instance can be given artificial latency,
jitter, packet loss, timeouts, error rates, CPU pressure, capacity limits, and
scheduled outages and recoveries. These are controllable at runtime through a
local admin API, and every injected fault is timestamped so recovery time can be
measured.

- `src/`: implementation (links `libhfdns`)
- `configs/`: per-POP profiles (india, singapore, germany, us_east)

Implemented from Milestone 2 onward. It is written in C++ so that the simulator
is never the bottleneck in a real-wire benchmark.
