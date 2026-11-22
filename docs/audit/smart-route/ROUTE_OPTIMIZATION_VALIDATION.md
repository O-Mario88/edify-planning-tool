# Smart Route Optimization Engine Validation

**Project:** Edify Planning & Monitoring Platform  
**Engine:** `platform/backend/internal/routeplan/smart_optimize.go`  
**Date:** 2026-11-22

---

## 1. Implemented Optimization Modes & Explicit Objectives

| Mode | Objective | Working-Hour Overflow Handling |
|---|---|---|
| **Balanced Route — Recommended** (`balanced`) | Balances road driving time, feasible school coverage, and early placement of critical verified SSA schools. | Ranks candidates by SSA-priority-per-minute value, retaining locked stops first. |
| **Fastest Route** (`fastest`) | Minimizes total road driving duration (`RoadSeconds`) using exact permutation (`<= 8` stops) or nearest-first + 2-opt (`> 8` stops). | Flags overtime conflicts transparently without silently dropping stops. |
| **Shortest Route** (`shortest`) | Minimizes total road distance (`RoadMeters`) over the provider's road matrix. | Flags overtime conflicts transparently. |
| **Maximum Schools** (`max_schools`) | Maximizes feasible school count within `work_start`–`work_end` minus break buffer. | Greedily packs feasible stops and lists excluded schools with explicit working-hour reason. |
| **Priority Schools** (`priority_schools`) | Prioritizes verified critical/high SSA need and Core School obligations first, then optimizes road travel order among included stops. | Retains critical/high SSA schools even when farther, excluding lower-priority overflow with explicit reason. |

## 2. Live Test B — Multi-School Optimization Across All 5 Modes

Tested live on `cceo@edify.org`'s planned field day (`2026-11-17`, starting from `Edify Uganda Office (Kampala)`, `08:00`–`17:00`, `60 min` visit duration):

| Mode | Stops Included | Road Distance | Driving Time | Baseline Distance | Distance Saved | Stop Order (School Codes) | Activity IDs Preserved | Latency |
|---|---|---|---|---|---|---|---|---|
| `balanced` | 4 / 4 | `110.2 km` | `2h 28m` (`8,900s`) | `118.5 km` | **`8.29 km`** | `1687 → 1688 → 1685 → 1686` | Yes (4/4) | `8.5 ms` |
| `fastest` | 4 / 4 | `110.2 km` | `2h 28m` (`8,900s`) | `118.5 km` | **`8.29 km`** | `1687 → 1688 → 1685 → 1686` | Yes (4/4) | `7.9 ms` |
| `shortest` | 4 / 4 | **`108.9 km`** | `2h 35m` (`9,279s`) | `118.5 km` | **`9.64 km`** | `1687 → 1688 → 1686 → 1685` | Yes (4/4) | `7.9 ms` |
| `max_schools` | 4 / 4 | `110.2 km` | `2h 28m` (`8,900s`) | `118.5 km` | **`8.29 km`** | `1687 → 1688 → 1685 → 1686` | Yes (4/4) | `11.3 ms` |
| `priority_schools` | 4 / 4 | `110.2 km` | `2h 28m` (`8,900s`) | `118.5 km` | **`8.29 km`** | `1687 → 1688 → 1685 → 1686` | Yes (4/4) | `8.3 ms` |

Notice how `shortest` genuinely selected a different road stop sequence (`1686 → 1685`) that saved an additional `1.35 km` of road travel (`108.9 km` vs `110.2 km`) while taking `6.3 min` longer (`9,279s` vs `8,900s`), whereas `fastest` minimized driving time!

## 3. SSA Priority & Tight Working-Day Proof

In `TestSmartRoute_FiveSchoolOptimizationAllModes` (Go `-race` test), constraining the working day to `08:00`–`12:30` across 5 schools in opposing directions proved:
- `priority_schools` retained the **Critical SSA** school (`score = 100`, `3.2/10`) even when geographically farther than routine schools.
- Overflow schools were moved to `excluded[]` with explicit `reason_code: "exceeds_working_hours"` and human-readable explanation.

## 4. User Control Preserved

Staff can accept, reorder (`↑` / `↓`), lock/unlock individual stop positions, remove stops, add stops from the map, re-optimize, save to `field_routes.route_plan`, or revert to original order — without mutating approved `public.activity` schedules.
