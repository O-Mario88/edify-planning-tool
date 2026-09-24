# Evidence for docs/live-performance-audit-2026-09-24.md

Raw measurements behind the report, from an isolated local environment
(50,000-school scaled copy; never production).

| File | What |
|---|---|
| `sweep-baseline-4404c24.jsonl.gz`, `sweep-final-37d1386.jsonl.gz` | `scripts/route_timing_sweep.py`: every argument-free GET route × 15 roles, one row per request (status, ms, queries, db_ms, bytes, most-repeated statement) |
| `slow-cohort-pairs.jsonl` | The 141 (role, route) pairs over 1 s in the baseline sweep |
| `cohort-baseline-4404c24.jsonl`, `cohort-final-37d1386.jsonl` | `scripts/route_pair_timing.py`: each cohort pair timed three times per build (median in `ms`, all three in `samples_ms`) |
| `load-baseline-4404c24.json`, `load-final-37d1386.json` | `scripts/load_test.py` stages, per-route and per-role summaries and the 2 s resource samples |
