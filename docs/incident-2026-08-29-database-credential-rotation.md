# Production database credential rotation interruption — 2026-08-29

## Summary

During remediation of an exposed production database credential, an in-place
reset of DigitalOcean's `doadmin` password invalidated connections used by the
still-running App Platform instances. Production readiness returned HTTP 504
until the platform's automatically triggered replacement deployment became
active. No data was deleted, restored, or rolled back.

## Impact and timing

- Severity: SEV-2 availability interruption; no evidence of data loss or
  integrity damage.
- Rotation-triggered deployment created: 2026-08-29 06:39:02 UTC.
- Replacement deployment active: 2026-08-29 06:43:59 UTC.
- User-visible window: bounded by those timestamps; HTTP 504 was observed
  during the replacement and readiness was healthy immediately afterward.
- Deployment: `3db61995-c6b5-4d83-9193-e2bdba130f78`.

## Cause

The managed database reset changes the only administrative login in place.
App Platform injects the updated binding and starts a deployment, but old
instances keep the invalidated password until their replacements are ready.
The rotation procedure assumed the managed binding would provide overlap; it
does not.

## Resolution and verification

The automatically triggered deployment completed successfully. Both web
instances and the scheduler reconnected, `/api/health/ready` returned database
and cache `up`, and the database remained online throughout. The production
database and cache firewalls allow only the production App Platform app.

## Corrective actions

1. Use an additive rotation: create `edify_runtime`, grant least privilege,
   deploy its pooled binding, wait for all old instances to drain, then revoke
   the prior runtime login.
2. Keep `doadmin` for the direct pre-deploy migration job only; do not rotate it
   while live components depend on it.
3. Readiness now verifies pooled sessions have all three database timeout
   ceilings before admitting traffic.
4. `docs/runbooks.md` now explicitly forbids in-place rotation of a credential
   used by live database clients.
