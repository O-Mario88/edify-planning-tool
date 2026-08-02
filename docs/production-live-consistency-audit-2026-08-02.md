# Edify live-production consistency audit — 2 August 2026

Status: **not production-certified**. The public production surface is stable and responsive, and the candidate source/artifact gates are green, but production is running an older release and authenticated role coverage could not be executed without authorized production sessions.

## Scope and evidence boundary

- Canonical production URL: `https://www.edifyplanning.app`
- Production checks were read-only. No live data was created, changed, or deleted.
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
| Live release provenance | **Fail** | `/api/health/build` returns 404 although the current source contains and tests this endpoint |
| Current candidate tests | Pass | 3,683 tests passed, 2 intentional skips, 0 failures, four parallel workers |
| Current candidate security | Pass | Bandit at CI thresholds: no medium/high findings; `pip-audit`: no known CVEs; `npm audit`: 0 vulnerabilities |
| Current candidate image | Pass | Non-root `edify`; image `sha256:c3b2052eb323ce78d448b68597887fb9bce7ce26968fa41c73abd8a2cff2acbd`; manifest `a22d4740a6ea6c02` |
| Authenticated production roles | **Blocked / unverified** | No authorized production session or safe role test accounts were available |
| Cross-browser authenticated production | **Blocked / unverified** | Only the Codex in-app browser was available, with no authenticated session |

## Live production findings

### Release drift — critical and open

`GET /api/health/build` returns 404 in production. The current repository contains a build-provenance endpoint and a release verifier that requires it. Consequently, production cannot prove its commit, release identifier, build time, or static manifest hash and cannot be certified as the current artifact.

Live static responses indicate an older build:

- Production static files report `Last-Modified: Sun, 02 Aug 2026 02:58:13 GMT`.
- The live service worker cache name is `edify-static-66c2483d236c`.
- The live login references hashed CSS/JS/font assets and those bytes match the repository's previously collected `staticfiles/` output.
- The newly built candidate artifact reports static manifest `a22d4740a6ea6c02`, which is not the live release's verifiable identity because the live endpoint is absent.

The timestamps strongly suggest that production was built around an earlier 2 August revision; this is an inference, not release proof.

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

- `python manage.py test --parallel 4 --keepdb`: 3,683 passed, 2 skipped
- `python manage.py check`: no issues
- `python manage.py makemigrations --check --dry-run`: no changes
- `ruff check .`: pass
- `ruff format --check .`: 1,136 files formatted
- `bandit -r apps config -ll -ii`: pass
- `pip-audit --strict --progress-spinner off`: no known vulnerabilities
- `npm ci`: pass
- `npm audit --audit-level=high`: 0 vulnerabilities
- canonical Tailwind rebuild: byte-stable SHA-256 `7eefc815aa1bfbe39b6e2cc45616633557e5eafc56a59794f1db4d219423a67f`
- production Docker image build: pass; runtime user `edify`
- 15,000-school scale gate: dashboard p95 148 ms, schools 171 ms, analytics 424 ms (other measured pages also remained below their test thresholds)

The generated inventory currently contains 469 routed product surfaces, 870 registered routes, 293 API routes, 11 roles, 66 permission keys, and 460 permission-gated surfaces. That matrix passed in the candidate test artifact; it has not been visually replayed behind each role in production.

## Remediation ledger

| ID | Finding | Severity | State | Repair/evidence |
|---|---|---:|---|---|
| PROD-REL-01 | Production lacks build-provenance endpoint and cannot identify its artifact | Critical | **Open; reproduced live** | Current source verifier and endpoint tests pass; candidate image embeds build info. Requires an authorized production deployment and post-deploy verification. |
| PROD-REL-02 | App Platform Dockerfile build cannot receive its commit bindable at build time | High | Source fixed | The service now injects `${_self.COMMIT_HASH}` as runtime `GIT_COMMIT`; the endpoint prefers an image-baked commit and otherwise reports the platform's exact deployed revision. |
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

Formal certification requires all of the following:

1. Authorized DigitalOcean App Platform access to inspect the failed/stale deployment, deploy the tested commit/artifact, verify migrations and startup, and confirm cache behavior.
2. A successful live `GET /api/health/build` response whose identity matches the deployed artifact and static manifest.
3. Production-safe test accounts or signed-in sessions for every role in the 11-role inventory, including valid empty/loading/error/populated data states.
4. Authenticated visual, DOM, computed-style, interaction, console, theme, responsive, accessibility, and cross-browser replay.
5. A decision on the typography conflict: the supplied brief names Inter while the current approved source contract and live implementation use Geist.

Until those steps are complete, the correct status is **candidate artifact green; production release stale; authenticated production consistency unverified**.
