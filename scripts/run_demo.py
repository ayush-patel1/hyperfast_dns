"""Deterministic end-to-end demo.

    python scripts/run_demo.py            # all core scenarios
    python scripts/run_demo.py type_drift # one scenario

Milestone 1 scope: healthy runs -> upstream change -> detection + structured failure event.
"""
from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.pipeline.definition import load_pipeline  # noqa: E402
from app.pipeline.engine import RunResult, RunStatus  # noqa: E402
from app.pipeline.runtime import build_engine  # noqa: E402
from app.pipeline.simulator import Scenario, SimulatedCustomerSource  # noqa: E402

CORE_SCENARIOS = [
    Scenario.TYPE_DRIFT,
    Scenario.DATE_FORMAT_DRIFT,
    Scenario.INVALID_VALUES,
    Scenario.NEW_COLUMN,
    Scenario.SEMANTIC_DRIFT,
]
HEALTHY_PARTITIONS = ["2026-09-20", "2026-09-21", "2026-09-22"]
DRIFT_PARTITION = "2026-09-27"

BOLD, DIM, RED, GREEN, YELLOW, CYAN, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"
STATUS_COLOR = {RunStatus.SUCCEEDED: GREEN, RunStatus.SUCCEEDED_WITH_WARNINGS: YELLOW, RunStatus.FAILED: RED}


def headline(text: str) -> None:
    print(f"\n{BOLD}{CYAN}== {text} {'=' * max(0, 70 - len(text))}{RESET}")


def show_run(result: RunResult) -> None:
    color = STATUS_COLOR[result.status]
    print(f"  partition {result.partition_id}  {color}{result.status:<24}{RESET} "
          f"rows {result.rows_loaded}/{result.rows_in}  schema v{result.schema_version}  {result.duration_ms} ms")


def show_event(result: RunResult) -> None:
    event = result.failure_event
    if event is None:
        return
    print(f"  {BOLD}failure event{RESET} {DIM}{event.event_id}{RESET}")
    print(f"    category   {event.category} / {event.failure_type}  severity={event.severity}  blocking={event.blocking}")
    print(f"    summary    {event.summary}")
    if event.schema_diff:
        print(f"    schema     v{event.expected_schema_version} -> v{event.observed_schema_version}")
        for change in event.schema_diff.changes:
            mark = f"{RED}BREAKING{RESET}" if change.breaking else f"{YELLOW}additive{RESET}"
            print(f"      - {change.kind:<18} {change.column:<14} {change.before or '':>9} -> {change.after or '':<9} {mark}")
    for report in event.drift_reports:
        print(f"    drift      {report.column}: mean {report.baseline_mean:.1f} -> {report.current_mean:.1f}, "
              f"PSI={report.psi}, KS={report.ks_statistic}")
    for col in event.affected_columns[:3]:
        p = event.column_profiles.get(col)
        if p and p.physical_type == "STRING":
            facts = []
            if p.integer_like_ratio > 0:
                facts.append(f"{p.integer_like_ratio:.0%} integer-like")
                if p.non_numeric_examples:
                    facts.append(f"invalid {p.non_numeric_examples}")
            if p.best_datetime_format:
                facts.append(f"datetime format {p.best_datetime_format!r}")
            if facts:
                print(f"    profile    {col}: " + ", ".join(facts))
    print(f"    affected   {event.affected_records} records  fingerprint={event.fingerprint}")


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.disable(logging.CRITICAL)
    scenarios = [Scenario(a) for a in argv] or CORE_SCENARIOS

    data_dir = REPO_ROOT / "data" / "demo"
    shutil.rmtree(data_dir, ignore_errors=True)
    settings = Settings(data_dir=data_dir, config_dir=REPO_ROOT / "config")
    engine = build_engine(settings)
    definition = load_pipeline(settings.config_dir, "acme", "customer_pipeline")
    contract = definition.load_contract(settings.config_dir)
    source = SimulatedCustomerSource(rows=500)

    headline("1. Healthy upstream: bootstrap schema registry and drift baseline")
    for partition in HEALTHY_PARTITIONS:
        show_run(engine.run(definition, contract, source, partition))

    detected = 0
    for scenario in scenarios:
        headline(f"2. Upstream change: {scenario}")
        source.scenario = scenario
        result = engine.run(definition, contract, source, DRIFT_PARTITION)
        show_run(result)
        show_event(result)
        detected += result.failure_event is not None

    headline("Result")
    print(f"  {detected}/{len(scenarios)} upstream changes detected and captured as structured failure events")
    print(f"  {DIM}state written to {data_dir}{RESET}")
    return 0 if detected == len(scenarios) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
