# Platform audits

Measured, repeatable checks used for the 2026-09-06 speed, freeze and
consistency pass. All of them run against a **local** dev server on
`http://localhost:8000` with the dev database; nothing here types a
password — sessions are minted server-side.

```bash
.venv/bin/pip install -r requirements/dev.txt      # playwright is dev-only
.venv/bin/python -m playwright install chromium
.venv/bin/python tools/audit/mint_sessions.py       # writes tools/audit/out/
```

| Script | What it measures |
|---|---|
| `route_crawl.py [roles]` | Every routed page as each role, in-process: status, exception, query count, wall time. |
| `browser_audit.py [roles]` | Console errors, failed requests, long tasks (main-thread freezes), navigation timing. |
| `tablet_audit.py` | Portrait 820×1180 and landscape 1180×820: overflow, tables under 70% of a wide parent, dense grids, sub-12px text. |
| `ui_consistency_audit.py [roles]` | Control heights, type sizes, radii, card padding distributions and outliers. |
| `table_padding_audit.py` | Every visible table's cell padding, row height and type size. |
| `cpu_profile.py <role> <urls…>` | CPU profile of a page load, naming the functions behind long tasks. |

Outputs land in `tools/audit/out/` (ignored by git). To name the line behind a
repeated query, wrap a request in `connection.execute_wrapper` and record
`traceback.extract_stack()` frames under `apps/` — see the memory notes in
the performance pass for the snippet.

## Naming a long task

- `timeline_trace.py <role> <url>` — Chrome timeline trace of one page load:
  style-recalc and layout time grouped by the code that forced it, plus every
  event over 20ms in order. This is the tool that separates "our script is
  slow" from "our script made the browser resolve style four times".
- `recalc_cost.py <role> <url>` — cost of one full-document style resolution
  and how much each stylesheet contributes (consistency.css carries ~60% on
  a dashboard: 2,300 selectors, 600 of them attribute- or `:not()`-keyed).
- `chart_cost.py` — re-renders the Country Director performance chart with
  option variants and times each; data labels on three column series were
  ~260ms of a ~410ms render.
