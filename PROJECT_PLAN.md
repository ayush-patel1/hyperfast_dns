# Project Plan — Hyperfast DNS Load Balancer

A research-oriented prototype of a DNS-aware load balancer with adaptive,
health-aware, and ML-assisted routing. It includes a reproducible benchmark and
ablation framework. Architecture: [ARCHITECTURE.md](ARCHITECTURE.md). Research
mapping: [RESEARCH_NOTES.md](RESEARCH_NOTES.md).

---

## 1. Goals and non-goals

**Goals**
1. A C++ data plane that forwards UDP (then TCP, DoT, DoH, DoQ) DNS queries
   across multiple backends, correctly and with minimal per-query overhead.
2. Seven interchangeable routing policies behind a single interface, each tested
   and benchmarked.
3. Health checking, failover, rate limiting, and overload shedding that keep
   working without any external component.
4. An adaptive control loop in two modes, heuristic-only and ML-assisted, so they
   can be compared in an ablation study.
5. A benchmark framework that answers research questions Q1–Q10 (§4) with
   reproducible, metadata-rich results, compared against a valid baseline
   (dnsdist).
6. A dashboard and a one-command Docker Compose demo.

**Non-goals**
- A recursive resolver or an authoritative server with real zones.
- Internet-scale BGP anycast. The project emulates multi-POP behaviour (M13).
- Hand-written eBPF/XDP programs. They would be in restricted C, which the
  language policy excludes (RESEARCH_NOTES §B).
- Claiming ≥ 1M QPS without measuring it. Synthetic decision throughput (Mode A)
  and real-wire throughput (Mode B) are always reported separately (§5).

---

## 2. Language policy and technology decisions

Allowed languages: **Python, C++, TypeScript/JavaScript, Go** (Go only with a
strong reason). CMake, Dockerfiles, YAML, and a thin Makefile are build and
config formats, not application code.

| Component | Language | Decision rationale |
|---|---|---|
| Data plane `hfdns-lb` | **C++23** (GCC ≥ 13) | Needs precise control of memory, threads, and syscalls (`epoll`, `SO_REUSEPORT`, `recvmmsg`). C++23 gives `std::expected` for explicit error handling without exceptions on the hot path. |
| Backend simulator `hfdns-backend` | **C++23** | Must not bottleneck real-wire benchmarks. A Python server tops out far below the load-balancer's target rates, which would turn every benchmark into a simulator benchmark. Shares `libhfdns` with the load balancer. |
| Load generator `hfdns-bench` | **C++23** | Open-loop, high-rate generation with accurate timestamps. |
| Local control loop (health, EWMA, snapshots) | **C++23** (inside `hfdns-lb`) | Failover must not depend on an external process being alive (ARCHITECTURE §1 invariant). |
| Adaptive / ML control plane `hfdns-control` | **Python 3.12** | Runs every 500 ms, not per query. FastAPI plus NumPy/scikit-learn in one process. |
| ML training and datasets | **Python** | NumPy, pandas, scikit-learn. PyTorch only if a model needs it (decided at M9). |
| Benchmark orchestration and analysis | **Python** | Scenario runner, CPU/memory sampling, CSV/JSON output, plots. |
| Automation scripts | **Python** | Replaces the suggested `.sh` scripts. |
| Dashboard | **TypeScript** (Next.js, React) | Talks only to `hfdns-control`, never to the data plane. |
| Go | **not used** | No component currently needs it. Python covers the control service, and C++ covers networking. |

### 2.1 C++ dependencies (Ubuntu 24.04 packages, pinned by the Docker base image)

| Dependency | Purpose | Chosen over |
|---|---|---|
| libknot (Knot DNS) | DNS parsing and packet writing; question-only parsing for responses; EDNS/ECS | ldns (allocates per packet); hand-written parser (the spec forbids it without strong justification) |
| yaml-cpp | typed configuration loading | — |
| spdlog (async sink) | structured JSON logging | glog (no async JSON) |
| cpp-httplib | admin HTTP on its own thread | Boost.Beast (heavy) |
| nlohmann/json | admin API JSON, off the hot path | — |
| GoogleTest + CTest | unit and integration tests | Catch2 (either would work; GTest is packaged) |
| Google Benchmark | Mode A microbenchmarks | — |
| OpenSSL 3 | DoT/DoH TLS (M15) | — |
| nghttp2 | DoH HTTP/2 (M15) | — |
| ngtcp2 | DoQ (M15; package availability to verify at M15) | — |
| libxdp / libbpf | optional AF_XDP (M16) | DPDK (not reproducible on the dev host) |

Histograms, the timer wheel, the alias table, the LPM trie, and token buckets are
implemented in-repo. Each is small, needs zero-allocation behaviour, and is unit
tested.

### 2.2 Python dependencies
FastAPI, uvicorn, httpx, pydantic, NumPy, pandas, scikit-learn, matplotlib,
dnspython (independent DNS implementation for tests), psutil (CPU/memory
sampling), pytest. The project uses one `pyproject.toml` at the repo root, with
packages `hfdns_control`, `hfdns_ml`, `hfdns_bench`.

### 2.3 External tools
dnsdist (baseline, M17), dnsperf/resperf (generator cross-check), Prometheus,
Grafana (optional), Docker Compose.

---

## 3. Environment and prerequisites

**Measured at M0:** Intel i5-10300H (4 cores / 8 threads), 7.8 GiB RAM, Windows
11 build 26200. Python 3.14 and Node 22 are installed on Windows. There is no
C++ compiler, CMake, or Docker CLI on Windows, and the data plane needs Linux
APIs anyway (`epoll`, `SO_REUSEPORT`, `recvmmsg`, AF_XDP). All C++ work
therefore happens in WSL2.

**Linux build environment (installed at M0):** WSL2 with Ubuntu 24.04.5 LTS,
kernel 6.6.87.2-microsoft-standard-WSL2, 8 vCPUs, **3.7 GiB RAM** (the WSL
default of half the host's memory, relevant to R2/R10).

```
wsl --install -d Ubuntu-24.04
sudo apt install build-essential cmake ninja-build pkg-config git libknot-dev libyaml-cpp-dev \
  libspdlog-dev nlohmann-json3-dev libgtest-dev libgmock-dev libbenchmark-dev libssl-dev \
  python3-venv python3-pip dnsutils clang-format clang-tidy
```

| Tool / library | Version |
|---|---|
| g++ | 13.3.0 (C++23 verified: test program links against libknot and yaml-cpp) |
| CMake / Ninja | 3.28.3 / 1.11.1 |
| clang-format | 18.1.3 |
| Python (in WSL) | 3.12.3 |
| libknot-dev | 3.3.4 |
| libyaml-cpp-dev | 0.8.0 |
| libspdlog-dev | 1.12.0 |
| nlohmann-json3-dev | 3.11.3 |
| libgtest-dev / libbenchmark-dev | 1.14.0 / 1.8.3 |
| libssl-dev | 3.0.13 |
| dig | 9.18.39 |

cpp-httplib will be vendored as a single header at M1.

Notes:
1. Keep **build directories inside WSL's own filesystem** (for example
   `~/build/hfdns`), not under the OneDrive-synced Windows path. Building over
   `/mnt/c` is slow, and OneDrive would try to sync build artifacts. Benchmarks
   must also run from the WSL filesystem.
2. Docker Desktop is needed from M19 (Compose demo). Before then, everything runs
   natively in WSL.

---

## 4. Research questions → experiments

| Q | Question | Scenario(s) | Independent variable | Primary metrics |
|---|---|---|---|---|
| Q1 | Does latency-aware steering beat round robin? | 01, 03 | policy | mean/p95/p99 latency, distribution |
| Q2 | Does health-aware routing reduce failed queries during backend failure? | 05 | `health.enforce` on/off | failed/timeout count, recovery time |
| Q3 | Does adaptive routing help under dynamic conditions? | 06, 09 | static vs adaptive heuristic | p95/p99 over time, time-to-shift |
| Q4 | Does ML beat heuristic routing? | 09, 10 | EWMA estimator vs model predictor (everything else identical) | p95/p99, prediction MAE vs EWMA |
| Q5 | Flash crowd behaviour | 07 | burst factor | success rate, queue depth, recovery |
| Q6 | Slow backend vs dead backend | 06 vs 05 | fault type | p99, traffic shift speed, ejection events |
| Q7 | Skewed geographic demand | 04 | region distribution, `geo.mode` | per-region latency, POP load |
| Q8 | Overhead of the adaptive control layer | 09 (+ Mode A) | control plane off / in-process / external | decisions/s, p99 delta, CPU |
| Q9 | Socket path vs AF_XDP | 12 | `PacketIO` backend | pps, CPU/packet, p99 |
| Q10 | Encrypted transports vs UDP | 11 | transport | handshake cost, p50/p99, CPU/query |

Scenarios 01–12 are named as in the specification (`scenario_01_baseline_round_robin` …
`scenario_12_fast_path_comparison`) and will live in `benchmarks/scenarios/`.

---

## 5. Benchmark strategy

**Two modes, always reported separately:**
- **Mode A — synthetic/logical** (`hfdns-microbench`): pre-encoded wire queries
  → parse → classify → region lookup → policy select. It runs in a loop per thread
  with no network, and reports decisions/s and ns/decision per policy and thread
  count. This is where a ≥ 1M decisions/s claim may be supported. It says nothing
  about network throughput.
- **Mode B — real wire** (`hfdns-bench` against `hfdns-lb` against
  `hfdns-backend`): real UDP/TCP packets on loopback or a Docker bridge. It
  reports achieved QPS at a bounded loss rate, plus latency percentiles. On the
  4-core dev host, the generator, load balancer, and backends share CPUs. Mode B
  numbers from this host describe **this host only**.

**Methodology rules**
- Open-loop arrivals (constant, Poisson, ramp, burst). Latency is measured from
  the intended send time, to correct for coordinated omission.
- Warm-up (default 5 s) is discarded. The measurement interval is reported.
- At least 5 repetitions per configuration, run in interleaved order. Reported as
  median with min/max (and 95% CI when n ≥ 10).
- Every result records: timestamp, git commit, full resolved configuration, host
  hardware/OS/kernel, CPU pinning, workers, transport, packet size distribution,
  query mix, concurrency, offered vs achieved QPS, success/failure/timeout counts,
  mean/p50/p95/p99/max latency, load-balancer CPU and RSS, generator saturation
  flags, and loopback vs bridge.
- The generator reports its own saturation. If the achieved send rate is below
  the offered rate, the result is flagged as invalid for throughput claims.
- `hfdns-bench` is cross-checked against dnsperf on the same workload.
- Unmeasured values are written as **NOT MEASURED**. Nothing is estimated in
  place of a measurement.

---

## 6. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | No C++ toolchain on the Windows host | Resolved at M0 | — | WSL2 Ubuntu 24.04 with GCC 13.3 installed (§3); the Docker image will pin the same toolchain |
| R2 | 4C/8T, 7.8 GiB host: generator, LB, and backends compete for CPU, so Mode B is capped by the host, not the design | High | Throughput claims | Report Mode A and B separately; CPU pinning; generator saturation flags; document host limits; no dashboard/Prometheus during runs |
| R3 | WSL2 / Docker Desktop virtualization adds noise and changes kernel behaviour (loopback, AF_XDP generic mode only) | High | Q9 result may be null | Repetitions and CIs; label results "WSL2 loopback"; report a null Q9 result honestly |
| R4 | libknot GPL-3.0 licence constrains project licensing | Medium | Legal / distribution | Decide the licence at M1; ldns fallback is possible behind the parser adapter |
| R5 | ML fails to beat the EWMA baseline | Medium | Q4 answer is "no" | Acceptable research outcome. Report the persistence/EWMA baseline next to the model, and never tune on the test split |
| R6 | Synthetic telemetry makes ML look good only on its own generator | Medium | Invalid Q4 | Train on traces recorded from the emulated system under randomized fault schedules; split by episode; evaluate on unseen fault types |
| R7 | Adaptive weights oscillate (herding on stale signals) | Medium | Worse p99 than static | Smoothing, step caps, P2C, exported snapshot age; oscillation metric in scenarios 06/09 |
| R8 | Per-worker rate limiting is approximate under `SO_REUSEPORT` | Certain | Limits looser than configured | Documented; measured in scenario 08 |
| R9 | Encrypted DNS library availability (ngtcp2 packaging) | Medium | M15 DoQ delay | Verify at M15; build from pinned source in Docker if needed; DoT/DoH do not depend on it |
| R10 | Correlation table memory on a small host | Low | OOM under stress | Bounded `max_inflight`, backpressure (shed) when full, and memory reported per run |
| R11 | Repo lives in a OneDrive-synced folder | Medium | Slow builds, sync conflicts | Build and benchmark from the WSL filesystem; large outputs are gitignored |
| R12 | dnsdist comparison configured unfairly | Medium | Invalid baseline | Same backends, generator, worker count, cache off; publish both configs; map policies explicitly |

---

## 7. Milestones

Each milestone ends with: tests, formatting, linting, the smallest relevant
integration test, a diff review, a summary, manual test steps, known limitations,
and a suggested Conventional Commit message. **Then it stops** until the user says
**"NEXT MILESTONE"**. The user makes all commits.

| # | Milestone | Deliverables | Exit criteria |
|---|---|---|---|
| 0 | Inspection, research, architecture | PROJECT_PLAN, ARCHITECTURE, RESEARCH_NOTES, folder skeleton | Documents reviewed |
| 1 | C++ skeleton (+ Python skeleton) | CMake project, `libhfdns`, typed YAML config + validation, JSON logging with `LOG_LEVEL`, `std::expected` errors, CLI (`--config`, `--check-config`), admin `/healthz`, GTest/CTest; `pyproject.toml` with pytest; Makefile targets; `clang-format`/`clang-tidy` and `ruff` configs | `ctest` and `pytest` green; `hfdns-lb --check-config config/dev.yaml` works |
| 2 | DNS protocol correctness | libknot adapter, `DnsRequestContext`, UDP listener, response parsing/validation, malformed handling, minimal `hfdns-backend` (A/AAAA/CNAME/MX/TXT/NXDOMAIN/SERVFAIL/TC) | dnspython correctness suite green |
| 3 | Basic forwarding | client → LB → backend → client, multiple backends, random upstream txids, correlation table, timer wheel, timeouts, concurrency, basic counters | Integration test with 4 backends; no mismatches under concurrent load |
| 4 | Backend registry + health | Health FSM, active probes, passive signals, ejection guard, panic mode, events | Failure and recovery integration tests |
| 5 | Policies | `round_robin`, `weighted` (alias), `least_inflight` (P2C), `latency_based`, `health_aware` + policy interface and runtime switching | Deterministic unit tests per policy; distribution tests |
| 6 | Telemetry | Mergeable histograms, time-decayed EWMA, windowed rates, Prometheus `/metrics`, `/v1/telemetry`, structured events | Metric names/labels match the spec; percentile accuracy test |
| 7 | Geo-aware routing | Region model, LPM trie, ECS extraction (opt-in), geo scoring, `geo_first`/`latency_first` | Geo benchmark (scenario 04) runs |
| 8 | Adaptive heuristic | Score function, advice API with TTL, in-process fallback, smoothing, ablation switch | Static vs adaptive run (scenario 09) |
| 9 | ML-assisted routing | Telemetry trace collection, dataset, training with seed/splits, model card, periodic inference in `hfdns-control`, ML ON/OFF | Model vs EWMA metrics reported; scenario 10 runs |
| 10 | Load generator | `hfdns-bench`: fixed/ramp/burst/Poisson, region sources, Zipf query mix, workers, saturation reporting; Mode A `hfdns-microbench` | dnsperf cross-check within tolerance |
| 11 | Benchmark suite | All 12 scenarios, runner, JSON/CSV/terminal output, CPU/memory sampling, BENCHMARKING.md | Every scenario produces a result file |
| 12 | Failure / flash crowd / DDoS | Token buckets, overload shedding, circuit breaker verification, recovery-time measurement, traffic patterns A–I | Recovery times measured |
| 13 | Multi-POP emulation | POPs, client populations, latency/catchment matrix, POP failure, traffic shifting | Clearly labelled simulation results |
| 14 | TCP DNS | TCP listener, pipelining, persistent upstream TCP, TC fallback | TCP vs UDP benchmark |
| 15 | Encrypted DNS | DoT → DoH → DoQ, shared request model | Per-transport overhead benchmark |
| 16 | Optional AF_XDP | `PacketIO` with `AfXdpIO`, fallback preserved | Standard vs fast path benchmark (null result is acceptable) |
| 17 | Baseline | dnsdist configs, comparable workloads, documented limitations | Reproducible comparison |
| 18 | Dashboard | Six pages (Overview, Backend Monitor, Traffic Steering, Adaptive Engine, Stress Test, Benchmark Results) | Works with the LB running; LB unaffected when stopped |
| 19 | Docker Compose demo | One command: LB, backends, control, dashboard, Prometheus/Grafana, bench tools; demo script | `docker compose up` + demo script succeed |
| 20 | Final packaging | README, EXPERIMENTS.md, SECURITY.md, report template, reproducibility guide, diagrams, cleanup | Full test suite green |

---

## 8. Git protocol

The assistant never commits, pushes, stages, resets, rebases, merges, or
cherry-picks. It may run `git status`, `git diff`, and `git log`. At the end of
each milestone it suggests a Conventional Commit message, and the user commits.
