# Hyperfast DNS Load Balancer

A research-oriented DNS-aware load balancer. It steers queries across
authoritative/edge DNS backends using round-robin, weighted, least-inflight,
latency-based, geo-aware, health-aware, and adaptive (heuristic or ML-assisted)
policies. It includes a reproducible benchmark and ablation framework.

**Status: Milestone 1 (project skeleton).** `hfdns-lb` loads and validates its
configuration, logs structured JSON, serves `/healthz`, and shuts down cleanly.
It **does not forward DNS yet** (Milestones 2–3). Every performance figure is
NOT MEASURED.

## Build and run

Everything runs on Linux. On Windows, use WSL2 Ubuntu 24.04 (setup and package
list in [PROJECT_PLAN.md §3](PROJECT_PLAN.md)). From the repo root, inside
Ubuntu:

```bash
make venv          # Python virtualenv at ~/venvs/hfdns (pytest, ruff)
make build         # CMake + Ninja; build output goes to ~/build/hfdns, outside the repo
make test          # C++ unit tests (ctest) + Python integration tests (pytest)
make lint          # clang-format check, clang-tidy, ruff
make check-config  # validate config/dev.yaml
make run-dev       # start hfdns-lb with config/dev.yaml (Ctrl-C to stop)
```

```bash
curl -s http://127.0.0.1:8053/healthz
# {"status":"ok","uptime_seconds":1.2,"version":"0.1.0"}
```

| `hfdns-lb` option | Meaning |
|---|---|
| `-c, --config <path>` | YAML configuration (required) |
| `--check-config` | validate and print a summary, then exit |
| `--log-level <lvl>` | `error`, `warn`, `info`, `debug`, or `trace`; the `LOG_LEVEL` environment variable overrides it |
| `-V`, `-h` | version, help |

Exit codes: `0` ok, `1` runtime error (such as an unreadable file or a port
already in use), `2` usage error, `3` invalid configuration. An invalid
configuration reports **every** problem with its YAML path and line number.
Unknown keys are errors, so a typo cannot silently fall back to a default.

| Document | Contents |
|---|---|
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | goals, technology decisions, prerequisites, research questions → experiments, benchmark strategy, risks, milestones |
| [ARCHITECTURE.md](ARCHITECTURE.md) | planes, thread model, data / policy / control / telemetry / failure flows |
| [RESEARCH_NOTES.md](RESEARCH_NOTES.md) | RFCs and papers: what each influences, what is and is not implemented |

## Layout

| Path | Language | Role |
|---|---|---|
| `core/` | C++23 | `libhfdns` + `hfdns-lb` data plane |
| `backend-simulator/` | C++23 | `hfdns-backend` emulated POPs |
| `load-generator/` | C++23 | `hfdns-bench` open-loop generator |
| `control-plane/` | Python | adaptive scorer + management API |
| `ml/` | Python | telemetry datasets, training, model artifacts |
| `benchmarks/` | Python + YAML | scenarios, runner, results |
| `frontend/` | TypeScript | Next.js dashboard |
| `config/` | YAML | dev / benchmark / stress / encrypted configs |
| `scripts/` | Python | automation |
| `deploy/docker/` | Dockerfile | images for the Compose demo |
