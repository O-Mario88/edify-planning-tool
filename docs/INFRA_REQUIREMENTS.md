# Phase 12 — Infrastructure Requirements

> **STALE — do not use for deployment.** This document describes the retired
> NestJS/Next.js stack (Prisma, S3 evidence, Twilio). The current Django
> deployment path is **DEPLOY.md** + `docs/scheduler-deployment.md`.

This document is the bill-of-materials for the real backend that the
in-memory action layer will swap onto. Every item lists:

- **What the mock does today** — the current behaviour
- **Production replacement** — the real service / library
- **Swap point** — the exact file(s) that change
- **Effort** — a calibrated estimate

The action signatures and UI components stay unchanged. Each swap is a
mechanical replacement of a single helper or import, not a redesign.

---

## 1. Postgres + Prisma — the entity store

**Mock today:**
[`src/lib/actions/store.ts`](../src/lib/actions/store.ts) holds every
entity (Plan, PlannedActivity, CostSetting, WeeklyFundRequest,
SchoolVisit, TrainingParticipant, SsaSnapshot, PartnerActivity,
LeaveRecord, DonorMetricSnapshot, Disbursement, Reimbursement,
BalanceReturn, FundsReceived) on `globalThis`. Survives HMR. Dies on
process restart. The shapes mirror `prisma/schema.prisma` exactly.

**Production replacement:** Managed Postgres (Neon, Supabase, RDS).
Run `npx prisma migrate dev --name init` against the existing schema.

**Swap point:**
- `findPlan`, `updatePlan`, `findActivity`, … → `prisma.plan.findUnique`, `prisma.plan.update`, …
- Array `.push()` calls → `prisma.X.create()`
- `claimIdempotencyKey()` → a real `IdempotencyKey` table with `@@unique([key])`
- `disbursementExistsFor()` → `prisma.disbursement.findUnique({ where: { weeklyFundRequestId_fundsReceivedId: { ... } } })` — requires `@@unique([weeklyFundRequestId, fundsReceivedId])` in schema

**Important:** wrap multi-write actions in `prisma.$transaction([...])`.
The action files already perform their writes in the right order;
just change `array.push` to `prisma.X.create` inside the transaction.

**Effort:** 2 weeks (migration, transaction wrappers, integration tests).

---

## 2. S3 (or R2 / GCS) — evidence storage

**Mock today:**
- `partnerUploadEvidence` and `uploadEvidence` (W6/W8) record a stub
  `s3://edify-evidence/<kind>/<id>/<ts>-<filename>` URI on the entity.
- No bytes are stored anywhere — the action receives only filename +
  contentLength.
- `EvidenceBulkDropzone` calls the action per file but never streams
  the actual bytes.

**Production replacement:**
- S3 bucket `edify-evidence-<env>` (KMS-encrypted at rest, lifecycle
  policy: glacier after 1 year)
- Presigned-PUT URL flow: action returns the presigned URL, client
  uploads directly to S3, then a `confirmUpload` action records the
  final URI on the entity.

**Swap point:**
- `src/lib/actions/activity-actions.ts` → `uploadEvidence` returns
  `{ presignedUrl, uri }` instead of a stub URI.
- `src/lib/actions/partner-actions.ts` → same for `partnerUploadEvidence`.
- `src/components/partner/EvidenceBulkDropzone.tsx` → `acceptFiles`
  changes from "call action, done" to "call action → PUT file at
  presignedUrl → call confirmUpload(uri)".

**Quotas:** Reject files > 25 MB (already enforced) + 100 MB per partner
per day (new limit; add a quota check in the action).

**Effort:** 1 week.

---

## 3. SES / Resend / SendGrid — transactional email

**Mock today:**
- `emitNotificationFanOut` writes a `NotificationRecord` to the
  in-memory store with `channel: "Inbox" | "Email" | "SMS"`. Only
  "Inbox" renders today; "Email" rows accumulate without delivery.
- Password reset (`src/app/api/auth/forgot-password/route.ts`)
  generates a token but never sends it.

**Production replacement:**
- Resend (recommended for simplicity) or AWS SES (recommended if AWS-
  native). Single transactional sender domain `notify@edify.app`.
- Mailgun-style template store keyed by `template` field on
  `NotificationRecord` (e.g. `weeklyFund.request_approved` →
  HTML + text templates with named placeholders).

**Swap point:**
- `src/lib/actions/audit.ts` → `emitNotification` becomes
  `emitNotificationAndDispatch` which queues the email send if
  `channel === "Email"` or `priority >= "important"`.
- New file: `src/lib/notifications/dispatch.ts` — drives the queue,
  retries with exponential backoff, marks `delivered_at` on success.
- `src/app/api/auth/forgot-password/route.ts` → wire to the new
  dispatcher with the reset-password template.

**Compliance:** SPF + DKIM + DMARC records on `edify.app`. Bounce + 
complaint webhooks land in an `EmailDeliveryEvent` table.

**Effort:** 1 week (basic) + 1 week (template library + i18n).

---

## 4. Twilio (or AWS SNS) — SMS

**Mock today:** Same as Email — `channel: "SMS"` rows accumulate, no
delivery.

**Production replacement:** Twilio Programmable Messaging. Routing
table: notifications with `priority === "critical"` go SMS-first then
fallback email; `priority === "important"` email-first SMS-fallback;
everything else inbox-only.

**Swap point:** Same `dispatch.ts` from item 3 picks up SMS via a
provider-agnostic `send({ to, body, channel })` interface.

**Cost ceiling:** Per-user SMS budget (e.g. 50 SMS / month / staff) to
prevent runaway from a misfiring notification loop.

**Effort:** 3 days.

---

## 5. Redis — rate limit + cache

**Mock today:**
- [`src/lib/rate-limit.ts`](../src/lib/rate-limit.ts) holds an
  in-memory `Map`. Single-instance only; bypassable by round-robin
  across replicas.
- No cache layer; every dashboard query hits the in-memory store.

**Production replacement:** Managed Redis (Upstash, ElastiCache).

**Swap point:**
- `src/lib/rate-limit.ts` → swap the Map for Redis `INCR` + `EXPIRE`.
- New `src/lib/cache.ts` for materialized-view snapshots (CCEO + CPL
  + Director dashboard rollups) keyed by `dashboard:<role>:<userId>:<periodIso>`.

**Effort:** 2 days (rate limit) + 1 week (dashboard cache).

---

## 6. Server-Sent Events — real-time notification bell

**Mock today:** The header bell is a static badge count; no live
updates. Notifications appear only on a page reload.

**Production replacement:** SSE endpoint at `/api/notifications/stream`
that the header bell subscribes to via `EventSource`. Each
`emitNotification` call writes to the user's stream queue (Redis pubsub
in production).

**Swap point:**
- New route: `src/app/api/notifications/stream/route.ts` (SSE handler)
- New client hook: `src/hooks/use-notification-stream.ts`
- Mount in the header bell component: `src/components/shell/HeaderBell.tsx`

**Important:** SSE doesn't work on Vercel's free serverless tier
(no long-lived connections). Either upgrade to Pro+Edge runtime
or use Pusher/Ably for the live channel.

**Effort:** 1 week.

---

## 7. Salesforce (jsforce) — Year-2 sync

**Mock today:**
- `PlannedActivity.salesforceId` / `matchStatus` columns exist but are
  never populated.
- `User.salesforceOwnerId` carries a hardcoded demo OID.

**Production replacement:** `jsforce` adapter behind a feature flag.

**Swap point:**
- New file: `src/lib/salesforce/sync.ts` — bi-directional sync engine.
- New cron: every 15 minutes, push unverified activities → Salesforce
  custom objects, pull match results.
- New worker: `src/workers/salesforce-sync.ts` (BullMQ recommended).

**Flag:** `EDIFY_SALESFORCE_SYNC_ENABLED=true` per environment. Off in
mock-mode. The action layer never branches on this flag — only the
sync worker does.

**Effort:** 3 weeks.

---

## 8. Sentry — error reporting

**Mock today:** Errors land in the Next.js dev console. The
`src/lib/log.ts` helper logs but doesn't ship anywhere.

**Production replacement:** Sentry SDK with the `@sentry/nextjs`
integration. Capture every action's failure modes (the discriminated-
union `reason` strings become Sentry tags).

**Swap point:** Wrap every action's catch boundary; pre-instrumented
in the `emitAudit` call site so the audit row carries the Sentry event
id when the action threw.

**Effort:** 2 days.

---

## 9. Audit retention — cold storage

**Mock today:** `AuditEventRecord` lives in `globalThis`. Cleared on
process restart.

**Production replacement:** Postgres `audit_event` table + nightly
archive job to S3 (Parquet, partitioned by month). Hot retention 90
days, cold retention 7 years (per donor compliance).

**Swap point:**
- `src/lib/actions/audit.ts` → `emitAudit` writes to Prisma.
- New worker: `src/workers/audit-archive.ts` — nightly job.

**Effort:** 1 week.

---

## 10. CI / deploy / monitoring

| Need | Today | Production |
| --- | --- | --- |
| Type-check + lint | `npm run typecheck && lint` works | GitHub Actions on every PR |
| Unit tests | 3,673 lines exist | Pin to coverage threshold in CI |
| E2E tests | None | Playwright — 1 happy-path per role |
| Migration check | None | `prisma migrate diff` in CI |
| Performance budget | None | Lighthouse CI on `/dashboards/*` |
| Uptime monitoring | None | StatusCake / Better Uptime → SLO 99.9 % |
| Deploy | Local dev | Vercel + Postgres + Redis + S3 (or Render + similar) |

**Effort:** 1 week (full CI/CD) + 1 week (monitoring + alerting).

---

## Summary timeline

| Item | Effort | Phase 12 priority |
| --- | --- | --- |
| Postgres + Prisma | 2 wks | **P0** (foundation) |
| S3 evidence | 1 wk | **P0** (W6/W8 need it) |
| Resend + email | 1 wk | **P0** (password reset blocked) |
| Sentry | 2 d | P0 (visibility) |
| Redis rate limit | 2 d | P0 (multi-instance) |
| CI/CD pipeline | 1 wk | P0 |
| Twilio SMS | 3 d | P1 |
| Redis dashboard cache | 1 wk | P1 (perf) |
| SSE live notifications | 1 wk | P1 |
| Email template library + i18n | 1 wk | P1 |
| Salesforce sync | 3 wks | **P2** (Year-2) |
| Audit archive | 1 wk | P2 |
| Lighthouse + uptime | 1 wk | P2 |

**P0 total: ~5 weeks** — minimum to leave mock-mode.
**P0 + P1 total: ~9 weeks** — production-ready feature parity.
**P0 + P1 + P2 total: ~14 weeks** — full Year-2 stack.

These overlap with the application-layer phases in the master plan
because most P0 items only require flipping a single file. The
biggest item (Salesforce) is genuinely sequential and should land
after the application layer is settled.

---

## Verification before deploy

1. **Backups:** automated nightly to a separate region; tested restore
   in staging at least monthly.
2. **Secret management:** all keys in AWS Secrets Manager (or Vercel
   env vars + Doppler). No keys in repo, ever.
3. **Database access:** Prisma client uses a connection pool (PgBouncer)
   with `?pgbouncer=true&connection_limit=1` per serverless function.
4. **Migration safety:** every Prisma migration is reviewed for table
   locks > 5 seconds; long migrations gated behind a feature flag.
5. **Auth invariant:** every server action calls `getCurrentUser()`
   first. CI grep guard: `^export async function \w+.*\)` files in
   `src/lib/actions/` must contain `getCurrentUser` or `Admin-only` in
   the first 5 lines.
6. **Audit invariant:** every server action calls `emitAudit` on the
   success path. CI grep guard: each `revalidatePath` call has a
   matching `emitAudit` in the same function.
7. **Rate limit:** Redis rate-limit live at `/api/auth/*`, `/api/demo/*`,
   and every evidence upload endpoint.
8. **Secrets-in-build check:** truffleHog in CI fails the build if any
   `AKIA` / `xoxb-` / `-----BEGIN` string slips into a commit.
