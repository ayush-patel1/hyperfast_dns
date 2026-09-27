# config — typed YAML configuration

| File | Purpose | Milestone |
|---|---|---|
| `dev.yaml` | local development: 4 emulated POPs, 2 workers | 1 |
| `benchmark.yaml` | pinned workers, logging at `warn`, dashboard off | 11 |
| `stress.yaml` | rate limits, overload shedding, flash-crowd settings | 12 |
| `encrypted.yaml` | DoT/DoH/DoQ listeners with test certificates | 15 |

Covers listeners, workers, backends (address, weight, region, capacity), region
CIDRs, health checks, timeouts, retries, policy, adaptive parameters, rate
limits, metrics, and TLS. Backend addresses exist only in these files, never in
source code.
