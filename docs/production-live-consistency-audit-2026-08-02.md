# Edify live-production consistency audit — 2 August 2026

Status: **public production artifact certified; authenticated role coverage incomplete**. The live site serves the tested static artifact and exact deployed revision, is stable and responsive across the public surface, and passes its release verifier. Production-safe sessions for all 11 roles were not available, so authenticated visual certification remains open.

## Scope and evidence boundary

- Canonical production URL: `https://www.edifyplanning.app`
- No live application data was created, changed, or deleted. The only production configuration mutation was adding the documented runtime `GIT_COMMIT=${_self.COMMIT_HASH}` binding to the web component so releases identify themselves.
- Live evidence covers the anonymous shell, login experience, static assets, health responses, headers, service worker, console, responsive behavior, and every concrete unauthenticated page route.
- Candidate-artifact evidence covers the current working tree, its full automated route/role matrix, security gates, CSS build, and Docker image.
- Local or source evidence is not treated as proof that production contains the same code.

## Executive result

| Area | Result | Evidence |
|---|---|---|
| Public production reachability | Pass | `/` and login load; `/api/health/ready` returns 200 |
| Live concrete page-route sweep | Pass for server stability | 210 routes: 3 × 200, 196 × 302 to authentication, 11 × 405, 0 transport/5xx failures |
| Live login responsive behavior | Pass | 1440, 1366, 1280, 1024, 768, 430, 390, and 360 px; no page-level horizontal overflow |
| Live login interaction/console | Pass | Show/hide password and forgot-password focus behavior work; no console errors or warnings |
| Live release provenance | Pass | `/api/health/build` returns the exact deployed SHA and canonical manifest `631bdab11312fe34`; the formal verifier passes |
| Current candidate tests | Pass | 3,688 tests passed, 2 intentional skips, 0 failures, four parallel workers |
| Current candidate security | Pass | Bandit at CI thresholds: no medium/high findings; `pip-audit`: no known CVEs; `npm audit`: 0 vulnerabilities |
| Current candidate image | Pass | Non-root `edify` (UID 10001); image `sha256:c7274cef004c3dc6d98de77d5a2fd5c103afc10b73e52d0d481e2063a1a4b734`; canonical manifest `631bdab11312fe34`; runtime-user settings import passes |
| Authenticated production roles | **Blocked / unverified** | No authorized production session or safe role test accounts were available |
| Cross-browser authenticated production | **Blocked / unverified** | Only the Codex in-app browser was available, with no authenticated session |

## Live production findings

### Release identity — resolved

`GET /api/health/build` now returns 200, the exact DigitalOcean source revision, image build time, canonical static-manifest identity, and critical hashed asset names. `verify_release` passes against production: the canonical manifest is `631bdab11312fe34`, and each reported CSS asset both matches the built image and returns 200 with a CSS content type.

Post-deploy live evidence:

- `/api/health/ready` returns 200 with the database up.
- The live service worker cache is versioned from the same canonical manifest and remains non-cacheable itself.
- Live `main.css` SHA-256 is `7eefc815aa1bfbe39b6e2cc45616633557e5eafc56a59794f1db4d219423a67f`, byte-identical to the committed compiled CSS.
- The four release-gated CSS assets have the same hashed names and bytes as the production image.
- The final 210-route anonymous replay returned 3 × 200, 196 × 302, 11 × 405, and zero transport/5xx failures.

### DigitalOcean deployment inspection

Authenticated inspection of App Platform found and repaired the release path:

- The initial healthy deployment was source revision `017c4fd`; the current production revision is exposed exactly by `/api/health/build` and matches the final deployed main revision.
- Revision `098f736` failed because DigitalOcean/Kaniko did not create `/app/build-info.json` from the inline Dockerfile heredoc. A portable Python module replaced it and was proven in DigitalOcean build logs and live deployment.
- The app has 27 app-level production variables, including encrypted signing, field-encryption, administrator, and Spaces credentials. The component-level `DATABASE_URL` overrides the app-level database binding, and the component now also carries the runtime commit binding.
- The active component still exposes port 8000, uses a 1 GB / 1 vCPU instance, runs migrations on web startup, and has no configured readiness check. This is operational drift from the committed target specification (port 8080, 2 GB, pre-deploy migration job, and `/api/health/ready`) and should be reconciled as a separate platform change.
- The Aug 1 deployment logs show a separate runtime failure: `RUN_SEED=true` imported production settings without the required Spaces variables, so the process exited before Daphne could bind port 8000. The later connection-refused readiness result was a consequence, not the root cause.
- The account contains the private `edify-planning-private-uploads` bucket in `sgp1` and a bucket-scoped Read/Write/Delete access key; current production settings import successfully with these encrypted app-level values.

### Public shell and login

- The root route redirects to `/login` successfully.
- Computed live typography is self-hosted Geist, body text 16 px.
- Desktop uses the navy brand pane and centered access card; tablet/mobile collapse cleanly to the single login card.
- Inputs and primary action are at least 48 px high on mobile and use a 16 px input font.
- One `h1`, one form, no duplicate IDs, and no unlabeled interactive controls were found. The only input without a visible label was the expected hidden CSRF field.
- Password visibility exposes the correct pressed state and accessible label.
- Empty submission uses native required-field focus behavior.
- No login-page console errors or warnings were observed.

Screenshots:

- `.deploy-verify/audit-2026-08-02/login-1440.png`
- `.deploy-verify/audit-2026-08-02/login-768.png`
- `.deploy-verify/audit-2026-08-02/login-390.png`

### Static delivery and headers

- Hashed static assets use long-lived public immutable caching and correct MIME types.
- HTML is private and Cloudflare reports `BYPASS`, avoiding stale shared HTML.
- `/sw.js` is non-cacheable, handles same-origin `/static/` GETs only, and removes old caches.
- HSTS, frame denial, referrer policy, and a Content Security Policy are present.
- The CSP still permits `unsafe-inline` and `unsafe-eval` for scripts. This is pre-existing hardening debt, not a new release blocker discovered by this consistency audit.

## Candidate artifact verification

The following passed against the current working tree:

- `python manage.py test --parallel 4 --keepdb`: 3,688 passed, 2 skipped
- `python manage.py check`: no issues
- `python manage.py makemigrations --check --dry-run`: no changes
- `ruff check .`: pass
- `ruff format --check .`: 1,136 files formatted
- `bandit -r apps config -ll -ii`: pass
- `pip-audit --strict --progress-spinner off`: no known vulnerabilities
- `npm ci`: pass
- `npm audit --audit-level=high`: 0 vulnerabilities
- canonical Tailwind rebuild: byte-stable SHA-256 `7eefc815aa1bfbe39b6e2cc45616633557e5eafc56a59794f1db4d219423a67f`
- production Docker image build: pass; runtime user `edify`; runtime settings import passes
- 15,000-school scale gate: dashboard p95 148 ms, schools 171 ms, analytics 424 ms (other measured pages also remained below their test thresholds)

The generated inventory currently contains 469 routed product surfaces, 870 registered routes, 293 API routes, 11 roles, 66 permission keys, and 460 permission-gated surfaces. That matrix passed in the candidate test artifact; it has not been visually replayed behind each role in production.

## Remediation ledger

| ID | Finding | Severity | State | Repair/evidence |
|---|---|---:|---|---|
| PROD-REL-01 | Production lacked a build-provenance endpoint and could not identify its artifact | Critical | Fixed and verified live | The endpoint returns 200 and the formal release verifier passes against the canonical manifest and critical assets. |
| PROD-REL-02 | App Platform Dockerfile build cannot receive its commit bindable at build time | High | Fixed and verified live | The web component injects `${_self.COMMIT_HASH}` as runtime `GIT_COMMIT`; the live endpoint reports the platform's exact deployed revision. |
| PROD-BUILD-01 | DigitalOcean/Kaniko did not execute the Dockerfile provenance heredoc; the following `chmod` failed because `/app/build-info.json` did not exist | Critical | Fixed and verified live | Replaced builder-specific heredoc syntax with the `scripts.write_build_info` module and added a subprocess regression test plus a Dockerfile contract test. DigitalOcean built and promoted commit `ba8abbc`; the live provenance and readiness endpoints return 200. |
| PROD-REL-03 | Raw manifest-byte hashes differed between local Docker and Kaniko for the same asset mapping because JSON key order is not stable | High | Fixed and verified live | Manifest identity is calculated from canonical, sorted JSON. Production and the local image both report `631bdab11312fe34`; the formal verifier passes. |
| PROD-IMG-01 | A local Docker context preserved owner-only source modes, so the configured non-root user could not import settings | High | Fixed and verified | The image normalizes application read/traversal permissions before switching users; both the locally built image and CI start Python as the actual runtime user and import application settings. |
| PROD-CONFIG-01 | Active App Platform topology differs from `.do/app.yaml` in port, resource size, readiness probe, and migration ownership | High | **Open; decision required** | Reconcile through a separately reviewed platform update; applying the committed spec changes cost and migration ownership and was not bundled into this release repair. |
| CI-SEC-01 | Bandit B310 rejected unrestricted verifier URLs | High | Source fixed | Verifier now accepts only absolute HTTP(S) base URLs, rejects credentials/query/fragment, and has regression tests. CI-threshold Bandit passes. |
| CI-AUTH-01 | Parallel auth tests collided on one shared throttle IP | Medium | Source fixed | Each test now uses a deterministic documentation-only IPv6 address and clears only its own throttle key. Parallel regression matrix and full suite pass. |
| CI-UI-01 | Compiled CSS lacked `pr-9` and other current utilities | High | Source fixed | Canonical CSS rebuilt; UI lint and full suite pass; rebuild is byte-stable. |
| CI-TEST-01 | Planning assertions described a removed recommendation UI and could not parse nested label markup | Medium | Source fixed | Assertions now follow the approved Purpose of Visit / Goal contract and strip nested label markup. Full suite passes. |
| DEP-NPM-01 | Unused `geist` React package pulled vulnerable Next/PostCSS/Sharp packages | High | Source fixed | Unused dependency removed; self-hosted committed font remains; npm audit reports 0 vulnerabilities. |
| LIVE-PUB-01 | Public route/server consistency | High | Verified live | 210 concrete page routes swept with zero 5xx/transport failures. |
| LIVE-AUTH-01 | All authenticated role/page/theme/viewport states | Critical | **Blocked / unverified** | Requires authorized production-safe sessions for all 11 roles. |
| LIVE-XB-01 | Chrome/Firefox/Safari/Edge production parity | High | **Blocked / unverified** | Current environment exposed only the Codex in-app browser. |
| DESIGN-FONT-01 | Attached brief says Inter; current source/tests and live production enforce Geist | High | **Decision required** | Do not mass-migrate typography until the authoritative approved design is clarified. |

## Required production follow-through

Remaining certification and platform work:

1. Production-safe test accounts or signed-in sessions for every role in the 11-role inventory, including valid empty/loading/error/populated data states.
2. Authenticated visual, DOM, computed-style, interaction, console, theme, responsive, accessibility, and cross-browser replay.
3. A decision on the typography conflict: the supplied brief names Inter while the current approved source contract and live implementation use Geist.
4. A separately approved App Platform topology reconciliation for the remaining port, resource, readiness, and migration-ownership drift.

Until the role sessions and cross-browser coverage are available, the correct status is **public production artifact certified; authenticated production consistency unverified**.
