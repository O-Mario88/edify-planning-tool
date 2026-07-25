# Pipeline and security audit — 25 July 2026

Audit of the build pipeline, GitHub Actions, security scanning, dependency
supply chain and container image, plus the defects those found in the
application itself.

The short version: **CI had been failing on every commit to `main` for weeks,
which meant the test suite had not run there at all** — the formatter check
failed first, and the job stopped. CodeQL had never been configured, so the
repository's first static analysis returned 100 open alerts. And the production
image could not be built, so `main` was undeployable.

---

## 1. Commit identity

| | |
|---|---|
| Repository | `O-Mario88/edify-planning-tool` (public) |
| Default branch | `main` |
| Audit start commit | `43310c07` |
| Audit end commit | see `git log` — every finding below was fixed on `main` |
| Working tree | clean at each recorded commit |
| Python | 3.13.12 local, 3.13.14 on CI |
| Django | 5.2.16 |
| Node | 24.14.0 local and CI |
| PostgreSQL | 16.13 local, `postgres:16` service on CI |
| Runner | `ubuntu-latest` |

---

## 2. CI failure ledger

| Workflow | Job | Step | Conclusion | Root cause | Fixed in |
|---|---|---|---|---|---|
| CI | Django Lint & Test | Ruff Formatter Check | failure | 30 files unformatted; local work ran `ruff check` only | `365eaf68` |
| CI | Django Lint & Test | Run Tests | **never reached** | the formatter failed first, so the suite had not run on `main` for weeks | `365eaf68` |
| CI | Security Scans | Static security analysis | failure | bandit B608: an UPDATE's SET clause built by string join in a migration test | `365eaf68` |
| CI | Security Scans | Static security analysis | failure | bandit B308 on a `mark_safe` introduced by the XSS fix | `5292f2be` |
| CI | Security Scans | Set up Node | failure | `package-lock.json` was gitignored, so `npm ci` had nothing to install from | `5292f2be` |
| CI | Security Scans | Build the production image | failure | `FIELD_ENCRYPTION_KEY` joined the prod required set after the Dockerfile's placeholder list was written — **the image could not be built at all** | `1335831c` |

Everything on `main` is green as of `1335831c`, including the Django suite
(11m10s), every security scan, the image build, the non-root assertion and the
Trivy image scan.

---

## 3. What the pipeline was missing

Added:

- **CodeQL** — was not configured at all. Now runs on pull requests, on pushes
  to `main` and weekly, over Python *and* JavaScript, with `security-extended`.
- **A scheduled security workflow** — the scans only ran on push, so a quiet
  repository could sit on a newly published CVE behind a green tick. Now daily.
- **Container scanning** — the image ships OS and Python packages the
  source-tree scans never see. Trivy runs on every push and nightly.
- **`zizmor`** — the workflows are as much a supply chain as the dependencies,
  and nothing was auditing them.
- **A CSS bundle drift gate** — see §5.
- **Dependabot** — alerts were disabled at the repository level (now enabled),
  and there was no update configuration (now pip, npm and github-actions,
  grouped monthly with a 7-day cooldown).

Hardened:

- `permissions: contents: read` at workflow level; `security-events: write`
  granted only to the CodeQL job that uploads a SARIF.
- Every third-party action pinned to a full commit SHA. A moving tag is a
  write-access grant to whoever can move it.
- `persist-credentials: false` on every checkout — otherwise the job's token
  sits in `.git/config`, where anything archiving the workspace carries it out.

---

## 4. Security findings

### CodeQL — 17 High, all fixed

| Rule | Count | What it actually was |
|---|---|---|
| `py/reflective-xss` | 2 | The cluster staff picker built `<option>` markup with f-strings, so a staff name containing a quote broke out of its attribute. The message star button interpolated a thread id straight off the URL. Both now use `format_html`. |
| `py/redos` | 1 | A template-scanning regex nested `[^>]*` inside `class="[^"]*"`, which backtracks exponentially. |
| `py/polynomial-redos` | 1 | Salesforce id normalisation ran `\s*-\s*` over a raw form value — quadratic on a long run of spaces, and redundant, because the next line stripped all whitespace. 200k spaces went from a stall to 0.1ms. |
| `py/path-injection` | 13 | Every evidence and PD file operation joined a database column onto a storage directory. Both stores now resolve through a guard that validates the name against an allowlist and re-checks containment after symlink resolution. |
| `js/xss-through-dom` | 1 | The launch screen handed a DOM attribute straight to `location.replace()`, where a `javascript:` URL would execute. |

### CodeQL — Medium, fixed

- **`py/url-redirection` (29).** Two were genuinely exploitable: the finance
  receipt-confirmation and debrief action handlers took their redirect target
  wholesale from the POST body. On an authenticated app that is a phishing link
  that really does depart from the Edify domain. All interpolated redirects now
  pass through one guard built on `url_has_allowed_host_and_scheme`.
- **`py/stack-trace-exposure` (47).** Thirty-one views answered a failure by
  interpolating the exception into an HTML fragment — unescaped, and catching
  bare `Exception`, so an IntegrityError quoting a constraint reached the user.
  One helper now shows domain messages escaped and answers anything else
  generically while logging the traceback.
- **`py/log-injection` (4).** There was no `LOGGING` configuration at all, so a
  newline in a logged value split one event into two, the second spellable to
  look genuine. A filter now escapes line breaks on the way out.
- **`py/overly-large-range` (3).** An emoji regex built from astral escapes,
  which CodeQL reads as three overlapping U+FFFD ranges. Replaced with a
  code-point membership test.

### Other scanners

| Scan | Result |
|---|---|
| bandit (`-ll -ii`) | no issues |
| pip-audit (`--strict`) | no known vulnerabilities |
| npm audit (`--audit-level=high`) | 0 vulnerabilities |
| Trivy image scan (CRITICAL,HIGH) | pass |
| GitHub secret scanning | 0 alerts; push protection enabled |
| Dependabot alerts | 0 open (feature enabled during this audit) |
| zizmor | no findings |

### Alerts that remain open, and why

Three `py/log-injection` alerts stay open, at
`apps/audit/services.py`, and two in `apps/core_schools/core_planning_services.py`.

They are controlled, and the control is the reason CodeQL cannot see it. All
three already use lazy `%`-arguments, and a `SingleLineFilter` on the console
handler escapes line breaks in a record's message and arguments on the way out
— so a value carrying `\n` cannot end the line or begin a fabricated one. That
filter is a runtime logging configuration, not a data-flow barrier in the
source, so the taint path still reads as open to a static analyser.

The alternative would be escaping at each of these three call sites, which
would clear the alerts and leave the several hundred other logging calls
depending on the filter regardless. A filter that covers every call site,
including ones written next month, is the better control; three hand-escaped
call sites would be scanner appeasement.

`apps/core/tests/test_logging_filter.py` pins it: the escaping, the record's
message and both argument forms, and — separately — that the filter is actually
attached to the handler the root logger and `django.request` use. A filter
configured but not attached is no control at all.

Seven `py/stack-trace-exposure` alerts also remain — one in
`leave_views.py` and six in the DRF upload and health endpoints. Every one of
them is a domain exception being rendered: `raise BadRequest("...")` with an
authored sentence, or DRF's own error contract turning that into a response
body. Showing those is the point of having them.

Every case where an *arbitrary* exception's text escaped has been fixed: the
thirty-one HTML fragments, the four services that wrapped `str(exc)` into a
BadRequest, the JSON error field, the cluster drawer, the catch-up plan
handler. What is left is a domain error surface behaving as designed, with
escaped bodies.

**Final alert state on `main`: 0 Critical, 0 High, 11 Medium** — the three
log-injection and seven stack-trace-exposure described above, and one
url-redirection whose guard is Django's own `url_has_allowed_host_and_scheme`.
Down from 100 open alerts, 17 of them High, when CodeQL first ran.

### Suppressions

The tree has no `continue-on-error`, no `|| true`, no skipped or xfailed tests,
and no disabled workflows. Every `# nosec` carries a written reason. One was
unqualified; qualifying it by rule id revealed a **second finding (B703) the
blanket form had been hiding**, which is the argument against blanket
suppressions in one line.

---

## 5. Defects found in the application

Beyond the scanner findings, the pipeline work surfaced these:

- **The committed CSS bundle had fallen behind its source.**
  `static/css/main.css` is generated from `assets/css/tailwind.source.css` and
  checked in, and nothing verified the two agreed. Four classes used in live
  templates — `max-w-[1400px]` on the activity detail page, `gap-[3px]` and a
  teal background in the core planning queue, an alignment on the debrief form
  — were absent from the bundle, so those templates rendered them as nothing.
  CI now fails if the bundle drifts.

  One wrinkle worth knowing: the Tailwind CLI's first build after a source
  change can lag by a pass — it dropped the `.text-red-500` utility but kept
  the `--color-red-500` theme variable, and a second build removed that too.
  So `npm run build:css` should be run until it produces no diff, which is
  exactly what the gate enforces.

- **`package-lock.json` was gitignored.** Without it `npm ci` cannot run and
  every install resolves the tree afresh, so the bundle CI verifies was not
  necessarily the one anyone else would produce.

- **Reference data did not survive a database flush.** The five official
  `TargetArea` rows, the active cost catalogue and its twelve canonical rate
  keys, and the geography sub-regions were all created by data migrations,
  which a flushed database never replays. Nothing raised: HR approval resolves
  priorities through `TargetArea.key`, found no areas, wrote zero rows and
  reported success — leaving My Targets blank after an approval that said it
  had been populated. That is what the long-failing
  `test_hr_approval_locks_the_agreement_and_writes_targets` had been reporting
  all along. All three are now restored on `post_migrate`, which Django emits
  after `flush` as well as after `migrate`, and only ever create — a rate the
  Country Director has changed is not something a deploy may reset.

- **Sixteen domain refusals were bare `ValueError`s.** "Partner payment
  requires a NetSuite Expense ID", "Activity does not meet final closure
  checklist requirements" — messages written for a user, raised as the
  exception type that means "bug". They now raise `BadRequest`.

- **Six templates were painting their own tab strips.** Rewriting the ReDoS
  regex exposed that the old one only matched when `class=` followed `role=`,
  so it had never seen them.

- **The service worker cached `/static/` forever.** The cache name was built
  from a `STATIC_VERSION` setting that was never defined, so it was permanently
  `edify-static-1`; since `activate` only deletes caches that are not the
  current one, nothing was ever evicted. Any asset URL without a `?v=` token
  was frozen for returning users across every deploy. This was not theoretical
  — it served a stale `pages.css` during this session's CSS work.

- **The production image ran as root.** Now uid 10001, with only the upload and
  media directories writable, asserted by CI.

---

## 6. Test suite

| Run | Database | Ordering | Result |
|---|---|---|---|
| 1 | fresh (`--create-db`) | fixed (`-p no:randomly`) | **1851 passed**, 0 failed, 22m12s |
| 2 | reused | randomised | see the run recorded alongside this commit |

One note on method, because it cost time: running two `pytest` processes
against the same test database deadlocks the teardown `TRUNCATE` against the
other process's read lock, and the failure then cascades into every test after
it. It looks exactly like a concurrency defect in the application and is not
one.

---

## 7. Not fixed — repository settings, which are the owner's call

These are governance settings rather than code, and two of them would change
how the owner works day to day. They are listed so the decision is explicit.

1. **No branch protection on `main`.** Anyone with write access can push
   directly and no status check is required to merge. §16 of the audit brief
   asks for required pull requests, required checks, and no force-push.
   Applying it would immediately stop direct pushes to `main` — including the
   ones this audit has been making — so it is left to the owner.
2. **The repository is public.** Worth a deliberate decision for an internal
   planning tool holding school and staff data.
3. **Secret scanning non-provider patterns and validity checks are off.** Both
   are additive and cheap to enable.
