# Background Job Scheduler — Deployment Guide

Resolves the audit finding: **`ENABLE_BACKGROUND_JOBS=False` everywhere,
silently, with no scheduler process actually provisioned.** The Target
Achievement Ledger, PD reminders, Field Debrief recurring-issue detection,
weekly fund requests, monthly work-plan envelopes, notification escalation,
and the daily digest all depend on this being running.

> The current deployment is a single Django monolith (see `Dockerfile`) with
> **two processes**: the web app and this scheduler worker. Both are declared
> in `.do/app.yaml` — the web app as a `service`, this one as a `worker`.

## Why a second process, not a background thread in the web app

`apps/realtime/apps.py`'s `AppConfig.ready()` used to start the APScheduler
instance directly — which runs once per Django process. On any deployment
with more than one web worker/replica (the normal case), that meant N
identical schedulers, each firing every job N times: N weekly fund requests,
N duplicate digests, N ledger rebuilds racing each other. That's exactly why
`ENABLE_BACKGROUND_JOBS` was never safe to turn on. The fix removes the
scheduler from the web process entirely — it now runs in exactly one
dedicated process, started explicitly via:

```
python manage.py runscheduler
```

This process registers all 8 jobs (see `apps/realtime/registry.py`
`JOB_REGISTRY` for the authoritative list) and blocks in the foreground
until terminated — a normal long-running service, not a side effect of
importing Django.

Every job additionally acquires a DB-backed lock (`ScheduledJobLock`) before
running and records a `ScheduledJobExecution` row — so even if a second
scheduler process is ever accidentally started (e.g. a deploy misconfigured
to scale the worker service to 2 replicas), the second one's job triggers
are skipped rather than double-executing.

## App Platform setup (2 components from 1 repo)

Both components are already declared in `.do/app.yaml`; this section explains
what they are and how to change them. **Do not apply that file to the running
app** — see the banner at the top of it and `.do/README.md`.

1. **Web service** (`services: - name: web`): uses the repo's `Dockerfile` and
   the default start command (`daphne ...`, from `CMD` / `Procfile`'s `web:`
   line). Leave `ENABLE_BACKGROUND_JOBS` **unset/false** here — the web process
   never runs jobs regardless of this flag now, so there is no benefit to
   setting it, but it costs nothing either way.

2. **Scheduler worker** (`workers: - name: scheduler`): same repo, same
   Dockerfile, with

   ```
   run_command: python manage.py runscheduler
   ```

   and `ENABLE_BACKGROUND_JOBS=true` in its own env. The flag is read per
   process, so setting it anywhere else does nothing.

   A worker has no public port and no domain, which is what you want: it
   serves no HTTP traffic. For its own health probe — separate from the web
   service's `/api/health` — run

   ```
   python manage.py scheduler_health_check
   ```

   from a scheduled check or an external uptime monitor. It exits non-zero
   when unhealthy (a job failed, is overdue, or the scheduler process itself
   has not run anything recently).

## Deliberate design decision: this does NOT hard-block web boot

Django's production settings (`config/settings/prod.py`) already fail closed
on unsafe config (mock data, weak secrets, etc.). We deliberately did **not**
add `ENABLE_BACKGROUND_JOBS=false` to that same hard-fail gate, because that
setting is read by the *web* process too (via the shared settings module) —
hard-failing web boot on a background-automation flag would mean forgetting
to provision the worker service takes down the entire product for end
users, not just the automation. That's a worse failure mode than the one
being fixed.

Instead:
- `runscheduler` itself refuses to start without `ENABLE_BACKGROUND_JOBS=true`
  (loud `CommandError`, non-zero exit) — the one process whose entire job is
  running background jobs correctly refuses to silently be a no-op.
- System Health (`/system-health`) shows a **critical**-severity, human-visible
  check ("Scheduler Disabled") whenever jobs are off in a production
  deployment, and per-job overdue/failed/never-run checks once enabled.
- `scheduler_health_check` gives ops an explicit, scriptable non-zero-exit
  signal for the worker service's own monitoring.

If your organization's policy is that the web app *should* refuse to boot
without background automation, that's a one-line addition to
`config/settings/prod.py`'s existing `_issues` list — deliberately left as a
policy decision rather than assumed.

## Local development

```
ENABLE_BACKGROUND_JOBS=true python manage.py runscheduler
```

runs the same 8 jobs against your local database. Use `--allow-disabled` to
start the process without the flag for debugging the command itself (jobs
will still no-op, matching production's "disabled" behavior).

The eighth job is `analytics_report_delivery`, retained for a future opt-in
scheduled-delivery release. It is not required by the current Analytics UI:
“Send to Inbox” creates the scoped Message and Notification synchronously.
No worker or outbound email provider is involved in that user action.

## Job inventory

See `apps/realtime/registry.py::JOB_REGISTRY` — the single source of truth
for job name, cadence, expected runtime, idempotency notes, and retry
policy. Do not add a new periodic task anywhere else; add one `JobSpec`
entry there and a function in `apps/realtime/jobs.py`.
