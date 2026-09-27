# Hyperfast DNS Load Balancer

A research-oriented DNS-aware load balancer. It steers queries across
authoritative/edge DNS backends using round-robin, weighted, least-inflight,
latency-based, geo-aware, health-aware, and adaptive (heuristic or ML-assisted)
policies. It includes a reproducible benchmark and ablation framework.

**Status: Milestone 0 (architecture and research). No component is implemented
yet, and every performance figure is NOT MEASURED.**

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
