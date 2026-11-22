# My Plan, Calendar & Smart Route Integration Report

**Project:** Edify Planning & Monitoring Platform  
**Date:** 2026-11-22

---

## 1. Single Authoritative Scheduling Source

Smart Route Planner reads planned school visits directly from PostgreSQL `public.activity` (filtered by `responsible_staff_id`, active `Rules.VisitTypes`, live statuses, and `Africa/Kampala` local day). No duplicate scheduling table was created.

- **Activity ID Preservation:** Every `SmartStopOutput` carries `planned_activity_id`, and every saved `field_routes.route_stop` row persists `planned_activity_id` alongside `school_id`, `stop_sequence`, and `route_version`.
- **Non-Mutation Guarantee:** Reordering, optimizing, locking, saving a route (`POST /api/v1/smart-route/save`), or recording field-day arrivals/departures NEVER mutates `public.activity`. Official schedule changes occur strictly through existing authorized Planning / My Plan workflows.

## 2. Synchronization & Route Revalidation (Test G & Test L)

- **Route Save Persistence (`POST /api/v1/smart-route/save`):**
  - Atomically writes `field_routes.route_plan` (upserted on `(user_id, day)` with monotonic `route_version` — **0 duplicate route plans**), versioned `field_routes.route_stop` rows, `field_routes.route_calculation`, and `field_routes.field_day`.
  - Publishes `route_plan.saved` via `internal/realtime.Broker` after PostgreSQL commit.
- **Route Validation (`POST /api/v1/smart-route/validate`):**
  - Compares saved stops against live `public.activity` rows for the day, flagging rescheduled/cancelled visits or newly added visits, AND checks whether the date falls on a Sunday, `public_holiday`, or approved `leave` date.
  - When stale, displays an actionable **My Plan synchronization notice** with one-click **Re-optimize now** in `RoutePlanner.tsx`.
- **Location Correction Sync:**
  - Approved GPS corrections increment `field_routes.school_location.version` and log `field_routes.location_change`, which refreshes Smart Route Planner automatically.

## 3. Live PostgreSQL Reconciliation (`edify_gorn_test`)

Verified directly via `psql` after Test G & Test K:

| Table (`field_routes.*`) | Row Count | Invariant Verified |
|---|---|---|
| `field_routes.route_plan` | `1` | Unique `(user_id, day)` — **0 duplicate route plans** across 4 save versions (`route_version = 4`). |
| `field_routes.route_stop` | `16` | 4 stops × 4 versions, every stop linked to its authoritative `planned_activity_id`. |
| `field_routes.route_calculation` | `4` | 1 auditable calculation row per saved route version with `input_hash` and provider metadata. |
| `field_routes.road_condition_report` | `2` | Both QA test closures cleanly marked `resolved` after verification. |
