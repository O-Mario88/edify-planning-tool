# Online Testing Phase 1 — Readiness Report (2026-06-16)

Two-phase autonomous task: (1) a strict clean workflow reset so testers can prove the
full workflow from the beginning, and (2) wiring the Messages & Notifications layer into
the workflow as a context-aware nervous system. Plus a final audit.

---

## VERDICT: ✅ READY for Online Testing Phase 1

- Clean reset done + verified (DB 37/37 checks, live `/schools` = 700·0·700, CCEO My Plan = 0).
- Both repos green: **web 590 tests · api 127 tests · web+api typecheck · web+api build**.
- Notifications upgraded to context-aware role-aware deep links + dedupe + resolution.
- Database is pristine and stays pristine (all Phase 2 work is code, no test data).

---

## A. Reset Summary (`npm run reset`)

Guarded (`CONFIRM_ONLINE_TEST_RESET=true`; production needs `ONLINE_TEST_RESET_ALLOWED=true`),
transactional, writes a JSON backup first, logs per-table counts, validates, exits non-zero on failure.

| Preserved | Cleared (this run) |
|---|---|
| 700 schools, ownership, geography | 268 activities, 37 clusters, 288 cluster assignments, 39 cluster sub-counties |
| users, staff & partner accounts | 26 evidence, 19 IA verifications, 8 payment requests, 8 payment logs |
| cost catalogue, project definitions | 4 budget lines / 1 annual plan / 1 budget version / 1 approval |
| previous-FY SSA, current-FY SSA | 1 fund request, 1 monthly fund request |
| FY config, audit chain | 30 project-school + 5 project-partner + 5 project impact assignments |
| | 24 notifications, 7 messages, 4 threads, 2 assignment audits, 1 report |
| | **created 490 current-FY SSA** so all 700 are SSA-complete |

Post-reset every school: `clusterStatus=unclustered`, `currentFySsaStatus=done`,
`planningReadiness=limited` (SSA-complete but cluster-first — not forced to Ready-to-Plan).

## B. Validation Results (`npm run validate` — 37/37 ✓)

active schools=700 · complete current-FY SSA=700 · incomplete SSA=0 · clustered=0 · clusters=0 ·
project-assigned=0 · activities=0 · partner-assigned=0 · annual/monthly plans=0 · fund requests=0 ·
budget lines=0 · evidence=0 · IA verifications=0 · payments=0 · debriefs=0 · notifications=0 · threads=0.
Preserved: users, staff, ownership, cost catalogue, partners, geography, project defs, previous-FY SSA.
Quality: two-weakest SSA computable on samples · ≥2 regions · ≥5 districts · ≥2 owners · Client+Core ·
SSA averages varied (critical <5 and strong ≥8 examples present).

## C. API / FE Smoke Test (verified live)

| Surface | Result |
|---|---|
| `/schools` (IA, live backend) | TOTAL 700 · CLIENT 466 · CORE 234 · CLUSTERED 0 · UNCLUSTERED 700 · SSA COMPLETE 700 — "Live · backend API" badge |
| `GET /api/cceo/my-plan?fy=2026` (CCEO) | `itemCount: 0`, `live: true`, all 5 sections empty |
| `GET /api/cceo/planning-gaps` (CCEO) | all gap categories count=0 (nothing to schedule until clustered — correct) |
| backend `/api/health` | `{status:ok, db:up}` |

The clean tester journey works: School Directory (700) → create cluster → assign school →
SSA recommendation → planning gap → schedule → cost → fund → My Plan → execution → evidence →
IA/Accountant → completed → analytics.

## D. Messages & Notifications — Context-Aware Nervous System

Built on the existing backbone (DomainEventService.emit → DB notifications + SSE; backend-backed counts).

- **ContextRouteResolver** (`edify-api/src/common/notifications/context-route.ts`): role-aware
  deep links for 24 context types. A CCEO struggling-school alert → `/schools/:id?view=plan`; a CD's
  → `/analytics` (summary/risk, never a planning route they can't act on); HR → `/staff`; evidence →
  IA `/verification`, partner `/partner/activities`, CCEO `/evidence`; money → finance routes only.
  Plus `roleCanActOnContext` + a stable `dedupeKey`. **11 unit tests.**
- **Dedupe**: `createNotifications()` keeps one unresolved notification per
  (recipient, context, title) — repeat events bump the row instead of spamming.
- **Auto role-aware routing**: any emit without an explicit `targetRoute` now gets one resolved for
  the recipient's role + context.
- **Resolution**: `resolveContext(contextType, contextId)` auto-resolves open alerts when the issue is
  fixed (e.g. accepting evidence clears "evidence missing"); `resolve(id)` + `PATCH
  /notifications/:id/resolve` for manual resolve; resolved alerts leave the active feed + bell badge.
- **Messages deep-link to the record** (was hardcoded `/messages`), routed for the recipient's role.
  Context was already required to send a message.

## E. Test Results

| Suite | Result |
|---|---|
| `edify-api` vitest | ✅ 127 passed (was 112; +11 resolver, +4 FY) |
| `edify-web` vitest | ✅ 590 passed |
| `edify-api` typecheck / build | ✅ clean |
| `edify-web` typecheck / build | ✅ clean |
| `npm run validate` | ✅ 37/37 |

## F. Remaining Risks / Out-of-Scope (honest)

- **Notifications spec is partially delivered.** The role-aware deep-link + dedupe + resolution core is
  done. The fuller spec — escalation engine, scheduled backend jobs (deadline/overdue/backlog scans),
  daily/weekly digests, the ~30-category taxonomy as enum columns, and a new notification-center UI —
  is a larger build, not done. Current notifications are backend-driven and correctly routed; they just
  don't yet auto-escalate or run on a timer. Resolution uses `status=archived` (no enum migration was
  done, deliberately, to keep the freshly-reset test DB stable).
- **Data-safety from the prior pass holds**: ~31 mock-leak pages still render "Insufficient data" in
  production until their backend is wired (feature work, not a data risk).
- **`partner/activities|inbox` etc.** are live-backed with a dev-only mock fallback gated by
  `isMockAllowed()`.

## G. How to run

```bash
# Backend (edify-api)
CONFIRM_ONLINE_TEST_RESET=true npm run reset     # clean the DB for Phase 1
npm run validate                                  # 37/37 must pass
npm run start:dev                                 # API on :4000

# Frontend (edify-web)
npm run dev                                        # reads .env.local (backend on, mock off)
```
Demo logins (seed password `edify`): admin@edify.org, cd@edify.org, ia@edify.org, accountant@edify.org,
hr@edify.org, plus seeded CCEOs/PLs. Each role is geography/portfolio-scoped.
