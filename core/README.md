# core — C++ data plane

`libhfdns` (DNS request model, parsing adapter, policies, telemetry shards,
health FSM, routing snapshots) and the `hfdns-lb` executable.

- `include/hfdns/`: public headers shared with the backend simulator and load generator
- `src/`: implementation
- `tests/`: GoogleTest unit and integration tests
- `bench/`: Mode A microbenchmarks (`hfdns-microbench`)

Implemented from Milestone 1 onward. Design: [../ARCHITECTURE.md](../ARCHITECTURE.md) §2–§6.
