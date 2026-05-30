# Infra setup — flipping mock to production

This walks through provisioning each external service the app supports
and the env var that switches the adapter on. The adapter pattern
means each item is independently flippable: turn on Postgres without
turning on S3, turn on Sentry without turning on Twilio, etc.

Boot-time log confirms which adapter is live for each slot:

```
[edify-infra] storage=dev email=console sms=console obs=noop
              rate=memory cache=memory db=mock salesforce=mock
```

When everything is wired:

```
[edify-infra] storage=s3 (edify-evidence-prod · eu-west-1)
              email=resend sms=twilio obs=sentry (production)
              rate=upstash cache=upstash db=prisma salesforce=jsforce
```

---

## 1. Postgres + Prisma

**Provision**
- Pick a managed Postgres: Neon (recommended for serverless), Supabase,
  or RDS.
- Get the connection string. For serverless deploys, add the PgBouncer
  query params so each function reuses one pooled connection.

**Set**
```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DB?pgbouncer=true&connection_limit=1
```

**Apply schema**
```bash
npm run db:generate     # generates Prisma client from prisma/schema.prisma
npm run db:migrate      # creates tables (production: `migrate deploy`)
npm run db:seed         # populates demo users + cost settings
```

**Verify**
Boot log shows `db=prisma`. The Prisma client is reused across HMR
(stashed on globalThis), so dev hot-reloads don't exhaust the pool.

**Override**
Set `EDIFY_USE_PRISMA=0` to stay on mock-mode even with `DATABASE_URL`
set. Useful when running a dev session against a clone of prod data
without writing back.

---

## 2. S3 evidence storage

**Provision**
- Bucket `edify-evidence-<env>` in your AWS account.
- Block all public access (enforced at bucket level).
- Enable default encryption (SSE-KMS recommended).
- Lifecycle rule: transition to Glacier after 365 days.
- CORS policy to allow PUT from your origin (for direct-browser uploads).

**Set**
```env
AWS_S3_EVIDENCE_BUCKET=edify-evidence-prod
AWS_REGION=eu-west-1
# Either IAM creds, or rely on instance role / OIDC
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

**Install SDK**
```bash
npm i @aws-sdk/client-s3 @aws-sdk/s3-request-presigner
```

**Verify**
Boot log shows `storage=s3 (...)`. Upload an evidence file from the
partner UI — the URI stored on the entity should start with
`s3://edify-evidence-prod/`. Inspect in the AWS console to confirm
the object landed.

---

## 3. Email (Resend)

**Provision**
- Resend account + verified sender domain (`edify.app`).
- DNS records: SPF, DKIM, DMARC (Resend provides the exact values).
- API key with `emails.send` scope.

**Set**
```env
RESEND_API_KEY=re_...
EMAIL_FROM_ADDRESS=Edify <noreply@edify.app>
```

**Verify**
Boot log shows `email=resend`. Trigger a password-reset from the login
page — Resend's dashboard should show the delivery within seconds.

**Fallback in dev**
Without `RESEND_API_KEY` the adapter prints the email to stdout:

```
────────────── EMAIL (dev console) ──────────────
to:        paul.chinyama@edify.org
subject:   Your password reset link
template:  auth.passwordReset
...
```

---

## 4. SMS (Twilio)

**Provision**
- Twilio account + a sender number (E.164).
- Auth token (kept in Vault / Secrets Manager, never in code).
- Per-recipient consent record (compliance requirement).

**Set**
```env
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM=+14155551234
```

**Verify**
Boot log shows `sms=twilio`. Trigger a critical-priority notification
(e.g. fundPlan.urgentReturned). Twilio Console shows the delivery
status.

**Routing rules**
SMS only fires for `priority === "critical"` templates. See
`src/lib/infra/dispatch.ts` for the curated CRITICAL_TEMPLATES set.

---

## 5. Observability (Sentry)

**Provision**
- Sentry project (platform: javascript-node or javascript-nextjs).
- Copy the DSN.
- Set up environments (development / preview / production).

**Set**
```env
SENTRY_DSN=https://<key>@<host>/<projectId>
SENTRY_ENV=production
SENTRY_RELEASE=v0.1.0   # or use VERCEL_GIT_COMMIT_SHA
```

**Verify**
Boot log shows `obs=sentry (production)`. Trigger a known error from
the IA queue's reject-evidence handler with an invalid id — Sentry
should receive the event within a second.

**Implementation note**
The adapter uses Sentry's envelope HTTP API directly so no
`@sentry/nextjs` install is required. This keeps the bundle small
and Edge-runtime compatible.

---

## 6. Redis (Upstash) — rate limit + cache

**Provision**
- Upstash Redis database. Pick the region closest to your function
  region to minimise latency.
- Copy the REST URL and token.

**Set**
```env
UPSTASH_REDIS_REST_URL=https://<id>.upstash.io
UPSTASH_REDIS_REST_TOKEN=...
EDIFY_CACHE_PREFIX=edify:prod:
```

**Verify**
Boot log shows `rate=upstash cache=upstash`. The login route hits
the rate limiter — exceed 8 attempts in 10 minutes from one IP and
you should see HTTP 429.

**Why Upstash specifically**
The REST adapter works on Vercel Edge runtime and doesn't require
a long-lived TCP connection. If you prefer Redis Cloud / ElastiCache,
replace `makeUpstashAdapter` in `src/lib/infra/rate-limit.ts` and
`src/lib/infra/cache.ts` with an `ioredis`-based implementation.

---

## 7. SSE notification stream

**Nothing to provision** — works in mock mode and prod with no
external service. The hook `useNotificationStream` connects to
`/api/notifications/stream`, and the dispatcher publishes events
to the in-process bus.

**Caveat for multi-instance deploys**
The in-process bus is per-process. For multi-replica deploys, swap
`src/lib/infra/notification-bus.ts` for a Redis pubsub backend:
- `subscribe(userId, sub)` → Redis `SUBSCRIBE notif:${userId}`
- `publish(userId, event)` → Redis `PUBLISH notif:${userId} <json>`

The function signatures don't change; the SSE route + client hook
don't change.

---

## 8. Salesforce (jsforce)

**Provision**
- Salesforce Sandbox + production org.
- Connected App with `api`, `refresh_token`, `offline_access` scopes.
- Service account user with API-enabled profile.
- Custom object `Edify_Activity__c` with the fields the adapter
  upserts (Edify_Internal_Id__c, School__c, OwnerId, Activity_Kind__c,
  Activity_Date__c, Notes__c).

**Set**
```env
EDIFY_SALESFORCE_SYNC_ENABLED=1
SF_LOGIN_URL=https://login.salesforce.com   # or test.salesforce.com for sandbox
SF_USERNAME=sync@edify.app
SF_PASSWORD=...
SF_SECURITY_TOKEN=...
```

**Install**
```bash
npm i jsforce
```

**Verify**
Boot log shows `salesforce=jsforce`. Verify a PlannedActivity via the
IA queue — the activity row should get a real Salesforce id populated
from the upsert response.

---

## 9. Deploy

The app is a vanilla Next.js 16 build that runs anywhere:

- **Vercel** — `vercel link` + push to main. Set env vars in the
  Vercel project settings. Note that SSE notifications die after
  5 minutes on hobby tier (60s on free); upgrade to Pro for longer.
- **Render** — `render.yaml` + Postgres add-on. SSE works indefinitely
  on persistent web services.
- **Self-host** — `npm run build && npm run start` behind a reverse
  proxy. Use `pm2`/`systemd` to keep it running.

The Prisma migration step (`npm run db:migrate`) must run before the
first request hits the server. Vercel's `buildCommand` does this
automatically when you set:

```
buildCommand: "npm run db:generate && npm run build"
releaseCommand: "npm run db:migrate"
```

---

## 10. Health check

A future `/admin/health` page can read `bootSummary()` from
`@/lib/infra` and render the resolved adapter labels alongside live
"connected SSE users" + "outbound email last 5m" counters. This is
useful for ops dashboards — the kind of thing that goes in a 
StatusCake monitor and an internal Grafana board.
