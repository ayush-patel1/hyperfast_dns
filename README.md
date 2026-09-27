# Adaptive Self-Healing Data Pipeline

**An autonomous data reliability platform.** It detects schema and data-quality
failures and investigates root causes using agentic AI and historical knowledge.
It generates repairs and validates them in isolated sandboxes, then restores failed
pipelines. Incidents that are ambiguous are escalated to human engineers.

> The system doesn't just detect that a pipeline failed. It works out **why**,
> proves a repair is safe, applies it, recovers the failed workload, and verifies
> that the system is healthy again.

```
DETECT → DIAGNOSE → PLAN → SANDBOX → TEST → SCORE → APPROVE → REPAIR → REPLAY → VERIFY
```

🚧 **Status: under active development.** Milestone 1 (ETL, schema registry,
failure detection) is complete. See [docs/architecture.md](docs/architecture.md).

## Quick start

```bash
python -m venv .venv
.venv/Scripts/pip install -e "backend[dev]"      # Windows
# source .venv/bin/activate && pip install -e "backend[dev]"   # macOS/Linux

python scripts/run_demo.py          # healthy runs, then 5 upstream changes
cd backend && python -m pytest      # unit + integration tests
```

## What works today

- **Declarative pipelines.** SQL column transformations run over DuckDB, with
  idempotent partition loads into per-tenant warehouse schemas.
- **Versioned schema registry.** Schemas are fingerprinted and move through the
  `ACCEPTED` / `OBSERVED` / `REJECTED` lifecycle.
- **Deterministic detection:**
  - schema drift: type change, add, remove, rename, nullability, constraint
  - data quality: nulls, duplicates, formats, ranges, enums, outliers, referential integrity
  - pipeline failures: malformed JSON, API schema, missing partition, SQL/transform errors
  - semantic distribution drift: PSI, KS, and mean shift
- **Structured failure events** with the evidence a diagnosis needs: diff,
  value profiles, violations, drift stats, sample records.
- **Upstream simulator** with 12 scenarios for reproducible demos and benchmarks.
