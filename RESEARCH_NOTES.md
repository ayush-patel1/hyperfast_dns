# Research Notes

How each source shapes the design, what the project actually implements, and
what it deliberately does not.

**Labelling rules**
- **RELATED WORK RESULT**: a finding reported by someone else's system. This file
  quotes no performance numbers from other work. Numbers from related work must
  be checked against the primary source before they appear in any document.
- **OUR MEASUREMENT**: produced by this repository's benchmarks. None exist yet;
  every result is **NOT MEASURED** as of Milestone 0.
- "Planned (Mx)" means that milestone is designed to implement it. Nothing below
  is implemented yet.

---

## A. DNS protocol

### RFC 1034 / RFC 1035: DNS concepts and wire protocol
- **Concept:** message format (12-byte header, question/answer/authority/additional
  sections), name compression, the 512-byte classic UDP limit, the TC bit, and
  the RCODE set.
- **Design influence:** the load balancer reads the header, the question, and the
  OPT record, and treats everything else as opaque bytes. It forwards the
  received buffer itself and rewrites only the 2-byte ID. Responses are validated
  by question hash (ARCHITECTURE §3.2). Malformed packets are counted and dropped
  or answered FORMERR (configurable) and are never forwarded.
- **Implemented:** Planned (M2). Parsing uses a mature library (libknot, §F), not
  a hand-written parser.
- **Not implemented:** zone data, recursion, answer synthesis in the load
  balancer. Those belong to the backend simulator, and only as far as tests need.

### RFC 2308: Negative caching
- **Concept:** NXDOMAIN/NODATA responses are cacheable for min(SOA TTL, SOA
  MINIMUM).
- **Design influence:** relevant only if response caching is added (ARCHITECTURE
  §10). It shapes the high-NXDOMAIN workload (traffic pattern F): the backend
  simulator returns a correct SOA in the authority section, so a cache would
  behave realistically.
- **Implemented:** backend simulator negative responses with SOA (planned, M2/M11).
- **Not implemented:** caching in the load balancer (off by design; not on the
  milestone path).

### RFC 6891: EDNS(0)
- **Concept:** the OPT pseudo-RR advertises the UDP payload size, the DO bit, and
  options.
- **Design influence:** receive buffers are sized to the configured
  `edns.max_udp_payload` (default 4096 B). OPT is parsed into `EdnsInfo`. The
  load balancer passes OPT through unchanged unless ECS handling is enabled.
  Correctness tests cover queries with and without EDNS and oversized responses
  (TC fallback).
- **Implemented:** Planned (M2, M7).
- **Not implemented:** negotiating a different payload size with backends. The
  load balancer is transparent.

### RFC 7871: EDNS Client Subnet (ECS)
- **Concept:** a resolver can pass a truncated client subnet so authoritative
  servers can tailor answers. The RFC itself discusses privacy and cache
  fragmentation.
- **Design influence:** ECS is an **optional hint** for client-region
  classification (`geo.trust_ecs`, default off). When it is on, only the
  configured source-prefix length is used, and region inference stays a lookup,
  never a latency estimate.
- **Implemented:** Planned (M7): ECS extraction and trust gating.
- **Not implemented:** adding ECS to upstream queries or scoped responses.
  Privacy implications are documented in SECURITY.md (M20).

### RFC 7766 and RFC 9210: DNS over TCP
- **Concept:** TCP support is mandatory. Clients may pipeline queries and servers
  may answer out of order, so responses are correlated by message ID. RFC 9210
  sets operational requirements such as connection reuse and idle timeouts.
- **Design influence:** the TCP listener is non-blocking, handles
  length-prefixed framing, correlates out-of-order responses by ID, applies
  idle and per-connection limits, and keeps persistent upstream TCP connections.
- **Implemented:** Planned (M14).
- **Not implemented:** TCP Fast Open tuning (environment-dependent).

### RFC 5452: Making DNS more resilient against forged answers
- **Concept:** unpredictable transaction IDs and source ports raise the cost of
  off-path spoofing.
- **Design influence:** the LB→backend hop is itself a DNS client. Upstream txids
  are random per query, and upstream sockets use random ephemeral ports.
  Responses must match txid, generation, and question hash.
- **Implemented:** Planned (M3).

### RFC 7858 (DoT), RFC 8484 (DoH), RFC 9250 (DoQ)
- **Concept:** encrypted client-to-server DNS over TLS on port 853, HTTPS
  (`application/dns-message`, GET and POST), and QUIC (one query per stream).
  RFC 7830 / RFC 8467 cover EDNS padding against traffic analysis.
- **Design influence:** encryption terminates at the load balancer on dedicated
  listener loops. Every transport produces the same `DnsRequestContext`. The
  overhead of each transport is measured on its own (Q10).
- **Implemented:** Planned (M15), in the order DoT → DoH → DoQ, and only after
  UDP/TCP are stable.
- **Not implemented:** encrypted LB→backend hops (backends are local). 0-RTT is
  disabled by default because of replay risk.

---

## B. Fast packet processing

### Høiland-Jørgensen et al., "The eXpress Data Path: Fast Programmable Packet Processing in the Operating System Kernel," CoNEXT 2018
- **Concept:** XDP runs eBPF programs in the driver before an `sk_buff` is
  allocated. Packets can be dropped, passed, redirected, or delivered to
  userspace through AF_XDP, while the kernel network stack keeps working.
- **Design influence:** the client-facing I/O sits behind a `PacketIO`
  abstraction (ARCHITECTURE §9). AF_XDP can then be added without touching
  routing logic, and the standard socket path stays the default.
- **Implemented:** Planned (M16): an optional `AfXdpIO` using libxdp's bundled
  redirect program.
- **Not implemented:** **custom XDP/eBPF programs**, including XDP-level DDoS
  filtering and in-kernel load balancing. BPF programs are written in restricted
  C, which the project's language policy (Python / C++ / TypeScript / Go) does
  not allow. Native-mode XDP needs driver support that WSL2 / Docker Desktop
  lacks. Only generic mode is available there, and it may show no gain.
- **Results:** the paper's throughput figures are **RELATED WORK RESULTS** for
  their hardware and kernel. This project does not claim to reproduce them.

### DPDK (Data Plane Development Kit), project documentation
- **Concept:** kernel-bypass polling drivers, burst (batch) I/O, hugepage-backed
  memory pools, lockless rings, and per-core run-to-completion loops.
- **Design influence:** the ideas are adopted inside the kernel-socket design:
  batch I/O (`recvmmsg`/`sendmmsg`), preallocated buffer pools, per-core worker
  ownership with no shared per-packet state, lock-free counters, and forwarding
  from the receive buffer.
- **Implemented:** these techniques, planned for M2–M3.
- **Not implemented:** DPDK itself. It needs NIC binding, hugepages, and
  supported hardware, which a WSL2 laptop doesn't provide, and it would make the
  project hard to reproduce.

### Emmerich et al., "MoonGen: A Scriptable High-Speed Packet Generator," IMC 2015
- **Concept:** a load generator must itself be measured. Precise rate control and
  timestamping decide whether latency results mean anything.
- **Design influence:** `hfdns-bench` is open-loop: send times come from a
  schedule, not from response arrivals. It records its own achieved send rate
  and scheduling lag, and reports when it could not reach the offered rate, so
  that a generator limit is not mistaken for a load-balancer limit. Its results
  are cross-checked against `dnsperf` (§F).
- **Implemented:** Planned (M10).
- **Not implemented:** hardware timestamping and DPDK-based generation.

### Gil Tene, "coordinated omission" (HdrHistogram documentation; talk "How NOT to Measure Latency")
- **Concept:** closed-loop generators understate tail latency, because a slow
  response delays the next request instead of being queued behind it.
- **Design influence:** latency is measured from the **intended** send time.
  Histograms are log-linear with bounded relative error and are merged, never
  averaged across threads.
- **Implemented:** Planned (M6 histograms, M10 generator).

### Dean and Barroso, "The Tail at Scale," CACM 56(2), 2013
- **Concept:** tail latency dominates user experience at scale. Remedies include
  hedged or retried requests with bounded extra load.
- **Design influence:** p95/p99/max are primary metrics. Retry on timeout is
  capped at one extra attempt and is subject to the client's deadline budget.
- **Implemented:** retry policy planned (M3/M4).
- **Not implemented:** speculative hedged requests before a timeout. They are a
  possible extension and would need their own experiment, because they add load.

---

## C. Load-balancing algorithms

### Mitzenmacher, "The Power of Two Choices in Randomized Load Balancing," IEEE TPDS 12(10), 2001
- **Concept:** sampling two random servers and choosing the less loaded one
  balances load dramatically better than one random choice, at O(1) cost.
- **Design influence:** `least_inflight` uses P2C over worker-local inflight
  counts. `latency_based` and `adaptive` use P2C between two weighted samples, so
  every worker doesn't pile onto the single "best" backend.
- **Implemented:** Planned (M5, M8).

### Dahlin, "Interpreting Stale Load Information," IEEE TPDS 11(10), 2000
- **Concept:** when load information is stale, deterministic "pick the least
  loaded" causes herding and oscillation. Randomized choice that accounts for
  staleness performs better.
- **Design influence:** snapshot signals are up to 100 ms old and advice up to
  roughly 0.5–2.5 s. Therefore snapshot age is exported, advice weights are
  smoothed and step-capped, selection is randomized (alias sampling + P2C), and
  exact local inflight is mixed into the decision.
- **Implemented:** Planned (M8). Oscillation is measured in scenario_06 / 09.

### Vose, "A Linear Algorithm for Generating Random Numbers with a Given Distribution," IEEE TSE 17(9), 1991
- **Concept:** the alias method: O(n) build, O(1) weighted sampling.
- **Design influence:** the control thread builds alias tables when a snapshot is
  published, so workers sample weighted distributions in constant time with no
  allocation.
- **Implemented:** Planned (M5).

### Envoy outlier detection and Finagle "Peak EWMA" (engineering references, project documentation)
- **Concept:** passive ejection of misbehaving hosts, with a maximum ejection
  percentage and backoff; a latency EWMA that reacts quickly to spikes.
- **Design influence:** the health FSM combines active probes with passive
  ejection, `max_ejection_percent`, and doubling cooldowns (ARCHITECTURE §6). The
  EWMA is time-decayed (α depends on Δt), so it doesn't depend on request rate.
- **Implemented:** Planned (M4, M6). Peak-EWMA asymmetry (fast rise, slow decay)
  is a configurable option, planned for M8.

### Circuit breaker (Nygard, *Release It!*, 2nd ed., 2018)
- **Concept:** closed → open → half-open states stop cascading failure.
- **Design influence:** the UNHEALTHY → RECOVERING (half-open, receiving only a
  probe fraction of traffic) → HEALTHY path.
- **Implemented:** Planned (M4).

---

## D. Anycast and geography

### de Oliveira Schmidt, Heidemann, Kuipers, "Anycast Latency: How Many Sites Are Enough?" PAM 2017
### Li, Levin, Spring, Bhattacharjee, "Internet Anycast: Performance, Problems, & Potential," SIGCOMM 2018
- **Concept:** BGP catchments often don't send clients to the geographically or
  latency-nearest site, and adding sites has diminishing latency returns. How
  well a site is placed and connected matters more than geography alone.
- **Design influence:** geographic affinity and **measured latency** are separate
  inputs (ARCHITECTURE §11). `geo.mode` chooses which one leads. Experiment Q7
  includes a case where the geographically nearest POP is not the fastest, to
  test whether a geo-first policy degrades.
- **Implemented:** Planned (M7, M13).
- **Not implemented:** Internet anycast / BGP. M13 is an **anycast-inspired
  multi-POP emulation**. Catchments are assigned by the load generator from a
  configurable matrix, with a configurable convergence delay on POP failure. It
  is labelled as a simulation throughout.

### Moura et al., "Anycast vs. DDoS: Evaluating the November 2015 Root DNS Event," IMC 2016
- **Concept:** under attack, an anycast operator either absorbs the load at the
  attacked sites or withdraws them to shift catchments. Both have costs for
  legitimate clients.
- **Design influence:** the M13 emulation models both responses (degrade in place
  vs. shift traffic) and measures their effect on legitimate-client success and
  latency.
- **Implemented:** Planned (M12–M13), as local emulation only.

### Kintis et al., "Understanding the Privacy Implications of ECS," DIMVA 2016
- **Concept:** ECS leaks client subnet information to authoritative operators and
  observers on the path, and can enable targeted surveillance.
- **Design influence:** ECS trust is off by default. The load balancer never adds
  ECS to upstream queries, and ECS values are never used as metric labels or
  logged above `trace`.

---

## E. Abuse resilience

### DNS Response Rate Limiting (Vixie and Schryver, ISC technical note, 2012), engineering reference
- **Concept:** limit responses per client prefix. "Slip" some answers as TC=1, so
  that genuine clients can retry over TCP, which spoofed sources cannot complete.
- **Design influence:** per-prefix token buckets (/24, /56). The overload action
  can be `drop`, `refused`, or `truncate` (ARCHITECTURE §7).
- **Implemented:** Planned (M12).
- **Not implemented:** RRL's response-content-based accounting (the load balancer
  limits queries per prefix, not identical responses). DNS cookies (RFC 7873) are
  also not implemented.

---

## F. Tools and libraries (engineering references)

| Tool | Role | Why this one |
|---|---|---|
| **libknot** (Knot DNS project, CZ.NIC) | DNS wire parsing in C++ | Mature and fast authoritative-server codebase. Supports question-only parsing and EDNS/ECS helpers. Can parse into a caller-provided memory pool (no per-packet `malloc`). **License: Knot DNS is GPL-3.0-or-later.** The project's license must be compatible, to be confirmed at M1. Fallback: ldns (BSD-3-Clause, but it allocates heavily per packet). |
| **dnsdist** (PowerDNS) | Baseline, M17 | A DNS-specific load balancer with comparable policies (`roundrobin`, `wrandom`, `leastOutstanding`, `firstAvailable`) and health checks. It is the like-for-like comparison. PowerDNS Recursor is **not** a valid load-balancer baseline and is excluded unless a separate "serving" comparison is justified. |
| **dnsperf / resperf** (DNS-OARC) | Cross-check of our generator (M10–M11) | The standard DNS benchmark tools. Used to validate `hfdns-bench` measurements on identical workloads. |
| **dnspython** | Python correctness tests (M2+) | An independent DNS implementation for assertions, so tests don't validate the C++ code against itself. |
