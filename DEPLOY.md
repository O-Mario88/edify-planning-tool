# Deploying Edify Planning Tool to DigitalOcean App Platform

The repository supports both DigitalOcean buildpacks and its existing
Dockerfile. The Dockerfile is the recommended path for this application
because it also installs the system packages used by document rendering.

## 0. The fastest path: import the committed app spec

`.do/app.yaml` describes the whole application — web service, managed
PostgreSQL, the pre-deploy migration job, health probes, and every environment
variable the production settings require.

In the control panel: **Create App → Import from App Spec**, paste
`.do/app.yaml`, then replace every value marked `REPLACE_ME` before the first
deploy. Or from the command line:

```bash
doctl apps create --spec .do/app.yaml
doctl apps update <APP_ID> --spec .do/app.yaml   # subsequent changes
```

The spec deliberately contains no real secrets. It will not deploy successfully
until you supply them, which is the intended behaviour: production settings fail
closed rather than starting with a placeholder signing key.

The rest of this document explains what the spec sets up, and applies equally if
you configure the app by hand.

## 1. Create the App Platform resources

1. Create an App from the GitHub repository.
2. Keep the repository root as the source directory.
3. Use the root `Dockerfile` (auto-detected by App Platform).
4. Add a DigitalOcean Managed PostgreSQL database named `db`.
5. Create a **private** DigitalOcean Spaces bucket in the closest suitable
   region. Create a bucket-scoped access key with Read/Write/Delete permission.
   Do not enable the CDN for these restricted files.
6. Set the service HTTP port to `8080`. App Platform injects this as `PORT`;
   the image and Procfile both bind to the injected value.
7. Configure the readiness endpoint as `/api/health/ready` and the liveness
   endpoint as `/api/health/live`.
8. Size the web service at **1 vCPU / 2 GB** or larger. numpy, pandas, scipy and
   headless LibreOffice do not fit comfortably in 1 GB, and a DOCX→PDF rendition
   is the request most likely to hit the ceiling.

If you deliberately select the Python buildpack instead of the Dockerfile,
the root `requirements.txt`, `runtime.txt`, and `Procfile` are ready for it.
The Procfile uses Gunicorn with an ASGI worker so streaming endpoints continue
to work, and places Gunicorn's temporary heartbeat files in `/dev/shm` as
required on App Platform.

## 2. Configure environment variables

Store secret values using App Platform's encrypted-variable option.

| Variable | Value / source |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` |
| `DATABASE_URL` | `${db.DATABASE_PRIVATE_URL}` |
| `SECRET_KEY` | A new value from `openssl rand -hex 32` (production refuses to boot below 50 characters) |
| `FIELD_ENCRYPTION_KEY` | A separately generated 32-byte hex/base64 key |
| `SUPER_ADMIN_EMAIL` | The production administrator email |
| `SUPER_ADMIN_PASSWORD` | A strong bootstrap password |
| `DIGITALOCEAN_APP_DOMAIN` | `${APP_DOMAIN}` |
| `ALLOWED_HOSTS` | Any custom domains, comma-separated; may be blank when `DIGITALOCEAN_APP_DOMAIN` resolves |
| `CSRF_TRUSTED_ORIGINS` | Custom HTTPS origins, including `https://`; the App Platform domain is added automatically |
| `AUTHZ_MODE` | `enforce` |
| `ENABLE_MOCK_DATA` | `false` |
| `ENABLE_DEV_ENDPOINTS` | `false` |
| `ENABLE_DEV_SEED` | `false` |
| `ENABLE_DEV_IMPORTS` | `false` |
| `PARTNER_ROLE_BRIDGE` | `false` |
| `SPACES_BUCKET_NAME` | The private Spaces bucket name |
| `SPACES_REGION` | Bucket region, for example `nyc3`, `sfo3`, `fra1`, or `sgp1` |
| `SPACES_ACCESS_KEY_ID` | Bucket-scoped Spaces access key |
| `SPACES_SECRET_ACCESS_KEY` | Matching Spaces secret key (encrypted variable) |
| `SPACES_PREFIX` | `edify-production` (keeps environment keys isolated) |
| `SPACES_ENDPOINT_URL` | Optional; defaults to `https://REGION.digitaloceanspaces.com` |
| `RUN_MIGRATIONS` | `false` on the web service — the pre-deploy job owns migrations (see §3) |
| `RUN_SEED` | `true` for the **first deploy only** (creates the super-admin and reference data; idempotent), then back to `false` |
| `ENABLE_BACKGROUND_JOBS` | `false` on the web service; `true` only on a dedicated `runscheduler` worker |
| `SECURE_SSL_REDIRECT` | `true` |
| `SESSION_COOKIE_SECURE` | `true` |
| `CSRF_COOKIE_SECURE` | `true` |

`JWT_SECRET` remains supported for existing deployments. When it is omitted,
the JWT layer uses the strong `SECRET_KEY`.

DigitalOcean's managed database URL includes the connection details and TLS
parameters. The application parses it with `dj-database-url`, checks
connections before reuse, and applies bounded connection, statement, lock, and
idle-transaction timeouts.

All evidence, document-library files and previews, professional-development
files, leave attachments, and message attachments use Spaces in production.
Objects are private. Their bucket URLs are never sent to the browser: each
download continues through the application's existing object-level
authorization checks. ClamAV and PDF conversion download an object to an
isolated temporary directory, process it, upload the result, and remove the
temporary copy.

## 3. Build, migration, and process commands

For a Dockerfile deployment, leave the run command blank so the image's
entrypoint and ASGI command run normally.

For a Python buildpack deployment:

- Run command: use the `web` command in `Procfile`.
- Pre-deploy job: `python manage.py migrate --noinput`
- Optional scheduler worker: `python manage.py runscheduler` with
  `ENABLE_BACKGROUND_JOBS=true`. Keep this at exactly one instance — two
  replicas would double-fire every scheduled job.

### Who runs migrations

Migrations run **once**, in the `PRE_DEPLOY` job, before any new container takes
traffic.

`docker-entrypoint.sh` also migrates on container start, because docker-compose
has no pre-deploy hook and relies on it. That default is wrong on a
platform that can start several replicas simultaneously — they would each run
`migrate` against the same database at the same time. So the App Platform spec
sets `RUN_MIGRATIONS=false` on the web service, which makes the entrypoint skip
its migration step and log that it did.

If you configure the app by hand rather than from the spec, set
`RUN_MIGRATIONS=false` on the web service and keep the pre-deploy job. Leaving
it unset is only safe at exactly one instance.

### Static files

WhiteNoise serves the output of `collectstatic` from `STATIC_ROOT`. The
Dockerfile collects it during image construction, under
`config.settings.collectstatic` rather than `config.settings.prod`.

This matters if you change either module. `prod.py` fails closed at import
unless every secret and Spaces credential is present, and none of that exists at
build time. Satisfying that gate previously meant a list of placeholder
environment variables baked into the Dockerfile, which fell out of sync with the
gate twice and made the image unbuildable both times. `collectstatic` opens no
socket, reads no secret, and touches no database, so the gate was never
protecting anything there.

Both modules take the staticfiles backend from a single constant,
`STATICFILES_STORAGE_BACKEND` in `base.py`. Keep it that way: a manifest built by
one backend and served by another returns 500 for every asset.

A buildpack deployment must set `DJANGO_SETTINGS_MODULE=config.settings.collectstatic`
for its build phase, or otherwise make the full production environment available
at build time.

## 3a. Custom domain: edifyplanning.app

The canonical production hostname is the apex, `edifyplanning.app`; `www` is an
alias that redirects to it. DNS can remain at GoDaddy. DigitalOcean App Platform
publishes stable ingress A/AAAA records for externally managed DNS, so do not
use GoDaddy Domain Forwarding and do not move nameservers solely to support the
apex.

Use this order to avoid a certificate outage:

1. In App Platform, open **Settings → Domains**, add `edifyplanning.app`, and
   select **You manage your domain**.
2. Keep the existing working `www` domain attached. The apex will sit in a
   pending/unverified state — that is expected and is not something to wait
   out. Certificate issuance validates over the public hostname, so it cannot
   complete until step 4 makes the apex resolve to App Platform. Waiting for
   the certificate before changing DNS deadlocks: neither side can go first.
   Adding the domain here only teaches the shared ingress to answer for this
   Host; that is the whole prerequisite.
3. Remove GoDaddy Domain Forwarding and its parked apex A records. Forwarding
   locks the apex A record, so it has to go before step 4 is possible at all.
4. In GoDaddy DNS, create the records below. Leave the `zone:` lines in
   `.do/app.yaml` commented because GoDaddy remains authoritative.

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `@` | `162.159.140.98` | 600 |
| A | `@` | `172.66.0.96` | 600 |
| AAAA | `@` | `2606:4700:7::60` | 600 |
| AAAA | `@` | `2a06:98c1:58::60` | 600 |
| CNAME | `www` | `edify-planning-app-gu9a6.ondigitalocean.app.` | 600 |

Add the AAAA pair in the same change as the A pair, not later. `www` already
answers over IPv6 through its CNAME; once the apex becomes canonical, an apex
with A records only would leave IPv6-first mobile clients unable to reach the
canonical host — and the redirect from `www` would send them there anyway.
These are DigitalOcean's published static ingress addresses, the same ingress
the A records reach, so they add no new failure surface.

5. Watch for the certificate to be issued — this is the step that takes time,
   typically minutes once resolvers return the new records. Until then the apex
   is unreachable rather than wrong: `.app` is HSTS-preloaded, so browsers
   refuse the plain-HTTP fallback. A blank apex during this window is expected.

6. Verify both hosts serve the same release with valid TLS.
7. Change `.do/app.yaml` to `edifyplanning.app` = `PRIMARY` and
   `www.edifyplanning.app` = `ALIAS`, deploy, then set
   `CANONICAL_HOST=edifyplanning.app` on the web service.
8. Confirm `https://www.edifyplanning.app/<path>?<query>` reaches the equivalent
   apex URL in exactly one permanent redirect.

Verify each stage with:

```bash
dig +short A edifyplanning.app; dig +short AAAA edifyplanning.app
curl -sS -I https://edifyplanning.app/
curl -sS https://edifyplanning.app/ | grep -c lander
curl -sS -o /dev/null -L --max-redirs 10 -w 'final=%{url_effective} redirects=%{num_redirects}\n' https://www.edifyplanning.app/
```

Pass: the A/AAAA pairs match the table; the apex returns the Edify application;
`grep -c lander` prints `0`; `www` reaches the apex in exactly one redirect.

DigitalOcean issues and renews the certificate after domain validation. Because
`.app` is HSTS-preloaded, there is no usable HTTP fallback while certificate
issuance is pending; valid apex TLS is a hard prerequisite for the DNS cutover.
`SECURE_HSTS_PRELOAD` is already on in `prod.py`, which is correct here.

The matching application settings are in the spec: `ALLOWED_HOSTS` (without it
Django returns `DisallowedHost` for every request), `CSRF_TRUSTED_ORIGINS`
(without it every login POST fails CSRF, which presents as "login is broken"
rather than anything mentioning CSRF), and `APP_BASE_URL`, which is what
invitation and password-reset emails build their links from.

## 4. Storage verification and recovery

The production settings fail closed when any required Spaces setting is
missing. The System Health page performs a small write/read/delete probe against
the private backend, so invalid credentials, permission changes, and endpoint
failures surface as a critical check.

Before onboarding real data:

1. Deploy with a new, empty private bucket.
2. Upload and retrieve one file in each restricted workflow.
3. Confirm the resulting objects are under
   `SPACES_PREFIX/private/...` or `SPACES_PREFIX/media/...` and are not public.
4. Rotate the initial key once to validate the credential runbook.
5. Configure an independent backup/export process. DigitalOcean Spaces does
   not include built-in backups; object versioning is useful protection but is
   not a separate backup.

Local development remains on `uploads/` and `media/`. Local files are not
silently copied to production. This is intentional: test/demo uploads should
not enter the real bucket. Any approved historical files must be migrated
through a separately reviewed, checksum-verified data-migration run.

## 5. Pre-push and post-deploy verification

Before pushing:

```bash
python manage.py check
python manage.py test \
  apps.core.tests.test_digitalocean_deployment_contract \
  apps.core.tests.test_private_storage
DJANGO_SETTINGS_MODULE=config.settings.collectstatic \
  python manage.py collectstatic --noinput
```

Build the image too. CI does this on every push, and it is the only check that
catches a Dockerfile that cannot build — a failure the deployment tests above
cannot see:

```bash
docker build -t edify-preflight .
```

After deployment:

```bash
curl -fsS https://YOUR-DOMAIN/api/health/live
curl -fsS https://YOUR-DOMAIN/api/health/ready
curl -I https://YOUR-DOMAIN/login
curl -I https://YOUR-DOMAIN/dashboard
```

The login page should return `200`; the unauthenticated dashboard request
should redirect to login. Confirm migrations completed before sending traffic,
verify the System Health storage check is green, and verify the scheduler worker
separately if scheduled jobs are enabled.
