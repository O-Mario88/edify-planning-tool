# 26. Proving a save in shadow before Go writes it

A save (scheduling, completing, approving, paying) moves to Go only after
it has been shown to write what the existing application writes (03, 3.7;
04, M5: "shadow comparison on a sanitised restore shows identical rows").
This is the harness every save is proved with. It reads development data
once and writes only to its own copies.

## 26.1 The pieces

| Piece | What it does |
|---|---|
| `platform/backend/cmd/shadow/copies.sh base` | copies the development database into `edify_shadow_base` with `pg_dump` (the source is only read) |
| `copies.sh fresh` | drops and remakes `edify_shadow_a` and `edify_shadow_b` from the base, so both start identical (about a second each) |
| `cmd/shadow/django_runner.py` | plays a scenario on one copy as people make the saves: each step signs in as an account, opens the drawer the web opens, keeps every field the drawer fills (and, as its script would, the values the script starts with), applies the step's choices, and posts the drawer's own form. Nothing below the view is stood in for. Each step's answer (status, toast or error) is written down |
| `go run ./cmd/shadow -a … -b … -from … -to …` | compares the two copies table by table. Tables that hash the same are equal; for the rest, the ids the run made read as `<new>`, timestamps inside the run's window as `<now>`, the audit chain's sequence, hashes and each request's correlation tag as `<chain>`, and then every row must match. The runner's sign-in sessions and request timing telemetry are left out unless `-all` is given. It refuses any database not named `edify_shadow_*` and opens its connections read-only |

When a save moves, Go plays the same scenario on copy B through its own
save, and the comparison must come back with nothing differing, along with
the same answer for every step.

## 26.2 The harness proved against itself (2026-11-12)

Scenario: `cceo@edify.org` opens Planning's Schedule drawer
(`/planning/schedule-modal?school_id=…`) for five of their client schools and
saves five visits (Training Follow Up, SSA Support, Donor Visit,
Content/Story Collection, Social Visit) on days later this month, a second
visit to the first school on the same day, and one visit dated in the past.

- **Same saves on both copies:** both answered six saves and the same
  refusal ("1 October 2026 has passed. Schedule work from 12 November 2026
  onwards."). 21 tables changed (activities, cost snapshots and cost lines,
  day batches and routes, fund requests and their items, weekly fund
  requests and lines, transport payments, advance requests, the audit and
  domain event logs, the target ledger's dirty marks, among them); none
  differed.
- **Different saves:** copy B missed one save and wrote another with a
  different purpose. 17 of the 21 changed tables differed, each named with
  its rows.
- Untouched copies: 366 tables, none changed.

What a single visit save writes, as this shows, is far more than the
activity: its cost snapshot and lines, the day's batch and route, the fund
request and the week's request lines, transport and advance rows, the
audit chain and domain events. A Go save is proved only when all of it
matches.

## 26.3 What is next

- The first Go save: scheduling a school visit (M5, designed in 27), proved with this
  scenario and then with a replayed month of real scheduling on a sanitised
  restore, as M5's exit asks.
- The runner fills a drawer's script-bound fields from the values the
  script starts with. A save whose drawer computes a field in the browser
  (a total, a list of ticked schools) needs that field named in the step.
