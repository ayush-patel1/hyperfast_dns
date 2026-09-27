# benchmarks — scenarios, runner, results

- `scenarios/`: `scenario_01_baseline_round_robin` … `scenario_12_fast_path_comparison`
  (YAML)
- `results/`: summary JSON/CSV with full metadata (committed); raw captures in
  `results/raw/` (gitignored)

Mode A (synthetic decisions/s) and Mode B (real wire) results are always stored
and reported separately. Methodology: [../PROJECT_PLAN.md](../PROJECT_PLAN.md) §5.

Implemented in Milestones 10–11.
