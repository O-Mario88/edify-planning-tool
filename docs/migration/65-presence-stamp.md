# 65. The presence stamp for requests Go answers (`presence-stamp`)

Backlog item `presence-stamp` (found by reports/agent46_todo-unsnooze.md):
Django's middleware stamps the signed-in person's presence on every request;
a request Go answers never reaches it, so Staff Activity and Who's Online
would show people idle once Go serves them.

## 65.1 What the existing application stamps (read, then measured)

`apps.core.middleware.SlidingSessionMiddleware.__call__` calls
`apps.accounts.presence.touch_presence(user, request)` after the response when
the request is not background (`X-Requested-With: EdifyLive`, the live
stream, `X-Edify-Background: 1`) and either the session slid (once per
`refresh_interval`, `TOUCHED_AT`) or the request is an action (any method but
GET/HEAD/OPTIONS; an htmx GET at most every `ACTION_INTERVAL` = 15 s per
session). `touch_presence` → `_next_beat`:

| Write | When | Columns |
|---|---|---|
| guarded `UPDATE "user" … WHERE id = me AND last_seen_at = <the beat the request read>` | the request read a beat on a tracked page | `last_seen_at = now`; `online_since = now` when it was NULL or the last beat is older than `ONLINE_WINDOW` (10 min), else kept; `last_seen_path`, `last_seen_action` from `request_footprint` (page = HX-Current-URL's path for htmx, else the path; action = `"METHOD path"` for a write or an htmx request, else ""; nothing for an untracked path such as `/api/…`); `last_seen_login_id` from the session's `_edify_login_event` |
| plain `UPDATE "user"` | the guarded one lost, or no beat to credit | the same values |
| `credit_presence_time` | the guarded UPDATE won | `login_event.active_seconds += s`, `last_active_at = GREATEST(COALESCE(last_active_at, at), previous + s)` for the beat's sign-in; `presence_time` slot `(user, Kampala day of the previous beat, section, working_on)` `+= s` (created if absent), where `s` is the whole gap up to `IDLE_SECONDS` (300) or `FINAL_BEAT_SECONDS` (30) after it, and section/working_on are `presence_labels.describe(previous path, previous action)` |

Measured on a shadow copy (`edify_shadow_s21_a`, the probe
`$SP/agent49_probe.py`, Django's test client), per channel:

| Request | Stamp |
|---|---|
| the app's read through the feed (bearer `GET /api/mobile/v1/page`, `/navigation`) | **nothing** (no session to slide; `/api/` is untracked) |
| the app's save through the feed (bearer `POST /api/mobile/v1/drawer`) | `last_seen_at` (and `online_since` by its rule) only; path, action and sign-in kept; no credit (the person is an `AuthPrincipal`, which carries no beat, so the UPDATE is plain) |
| a web page (session GET `/clusters/`) | path `/clusters/`, action "" — and a second page within the minute: nothing |
| a web htmx GET with HX-Current-URL `/dashboard?x=1` | path `/dashboard`, action `GET /today/panel`; again within 15 s: nothing |
| a web htmx GET with `X-Edify-Background: 1` | nothing |

So the stamp depends on the channel the existing application would have
answered, and Go stamps what that request would have stamped:

- **Pages and screens Go answers for the app and the web** (`GetPage`,
  `GetNavigation`, the screens): the existing equivalent is a bearer GET of the
  feed, which stamps nothing. Go stamps nothing. 65.5 proves it.
- **The app's saves Go makes** (`EDIFY_GO_SAVES`: schedule, reschedule,
  cancel, edit, pair, group move/cancel, group training): each first POSTs
  the drawer `?form_only=1` to the existing feed with the person's bearer
  (`internal/screens/*_save.go`), and that POST is stamped by the middleware
  exactly as the forwarded save would be (`last_seen_at`, `online_since`).
  Go adds no stamp of its own, which would stamp twice. When the form_only
  read moves to Go, `presence.Stamper.Stamp(ctx, user, Request{Method:
  "POST", Path: <the feed path>, Bearer: true})` is the stamp to make
  (covered by the integration test).
- **Web saves Go makes for a session's post** (Today's Snooze and Undo,
  `/today/snooze`, `/today/unsnooze`, docs 50/63): Go stamps the whole beat,
  credit included, after the outcome (a refusal included; a handed-on post
  is stamped by the existing application).
- A session's *read* (page slide, htmx throttle) is not something Go answers
  today; its throttle lives in the Django session, so `presence.Touches`
  answers false for any read, and that is recorded here as left (65.7).

## 65.2 The coordinator's decision, as built

2026-11-13: "the gateway stamps exactly what the middleware stamps, with the
same throttle, path and action values, … through a narrow writer role or
function limited to those columns; secrets test and dbguard extended".

`platform/deploy/db/presence_roles.sql` (wired into `apply-roles.sh` after
`todo_unsnooze_roles.sql`, the integration TestMain, and `copies_test.sh`'s
owner check):

| Object | Rights |
|---|---|
| `edify_presence_owner` (NOLOGIN, NOINHERIT, nobody a member) | UPDATE `"user"(last_seen_at, online_since, last_seen_path, last_seen_action, last_seen_login_id)`; UPDATE `login_event(active_seconds, last_active_at)`; INSERT `presence_time(id, user_id, day, section, working_on, seconds)`, UPDATE `presence_time(seconds)`; the SELECTs its filters read; no whole-table right, no DELETE |
| schema `gateway_presence` | owned by that role; no PUBLIC rights; USAGE to `edify_presence_rw` |
| `gateway_presence.beat(target_user, page, action, login_id, previous_seen, previous_login, previous_section, previous_working_on, new_slot_id, idle_seconds, final_seconds, online_window_seconds, time_zone) RETURNS integer` | SECURITY DEFINER, `search_path = pg_catalog, pg_temp`; `_next_beat` and `credit_presence_time` in one call, at the database's own clock (`clock_timestamp()`: a beat cannot be dated); the guard is the beat the caller read, so only time that really passed since a real beat is credited, bounded by the thresholds (out-of-range thresholds raise); returns the seconds credited. EXECUTE to `edify_presence_rw` only (granted to `edify_gateway`), revoked from PUBLIC |

What a slot is called (`describe` of the earlier beat) is computed in Go and
passed in; the function cuts it to the columns' lengths.

The gateway holds no UPDATE of those tables itself. The secrets test now
refuses, as the gateway: stamping `last_seen_at` or renaming
`last_seen_path` directly, crediting/inventing/removing `presence_time`,
lengthening a `login_event`, and `SET ROLE edify_presence_owner`.
`internal/dbguard` lists `presence_time` as undeletable and the beat,
slot and sign-in-time columns as protected (a role that can UPDATE them is
refused in staging).

**Production needs the owner's approval at cutover** (new role, schema and
function).

## 65.3 Go

- `internal/presence`: `rules.json` from `manage.py export_presence_rules`
  (`apps/accounts/management/commands/export_presence_rules.py`, drift test
  `apps/accounts/test_presence_rules_export.py`): untracked prefixes, read
  methods, action verbs, the id-segment pattern, online window, idle and
  final-beat seconds, the action interval, the background header, the column
  lengths, the time zone, plus 15 `request_footprint` and 18 `describe`
  samples computed by the existing functions, which the Go tests are held to.
  `Footprint` (request_footprint), `Describe` (presence_labels.describe, its
  section from the Staff Activity Log's port through
  `internal/staffactivity/export_presence.go`), `Touches` (the middleware's
  decision for what Go answers), `Stamper.Stamp` (reads the person's last
  beat with the read-only grants roles.sql already gives, decides the call,
  asks the function in one read-write transaction).
- `internal/todosnooze`: `Service.WithPresence(stamper, logger)`; `Snooze` and
  `Unsnooze` stamp `POST /today/snooze` / `/today/unsnooze` (paths exported in
  todosnooze's rules.json as `posts`) as htmx posts from `Request.Page` /
  `UnsnoozeRequest.Page` (the HX-Current-URL; empty means the post's own
  path), after the outcome, refusals included, never for a handed-on post.
  A failed stamp is logged and never changes the answer (touch_presence
  swallows database errors).
- The undo's redraw (the Today panel the existing application draws) is the
  gateway's own read: it is fetched with `X-Edify-Background: 1`
  (`presence.BackgroundHeader()`), so it does not overwrite the person's
  stamp with `GET /today/panel` (agent 46's difference (a)).

## 65.4 Harness changes

- `cmd/shadow/todoplay` gives the service the stamper and reads the redraw
  in the background (`"background": true` on the runner's `get` step).
- `cmd/shadow/django_runner.py`: the `get` step sends
  `X-Edify-Background: 1` when asked; and the runner no longer writes
  `last_login` on its per-step `force_login` (`update_last_login` is
  disconnected). Each step stands for a request in the session the person
  already has; the stand-in sign-in wrote `last_login` on copy A for every
  step, which a person's post never does, and which a Go save cannot match
  (run 1 below: the one remaining difference). This changes copy A of every
  scenario the runner plays the same way and only removes that artefact.

## 65.5 Proof

Copies `edify_shadow_s21_*`: base from `copies.sh base`, `apply-roles.sh` on
that base only, then `presence_roles.sql` on the base; `copies.sh fresh` before
each run. Copy A through the existing application (`django_runner.py`), copy B
through Go (`cmd/shadow/todoplay`), then `go run ./cmd/shadow` (and `-all`).

**Steps Go itself took:** unsnooze scenario 18 of 20 (10 undos, 8 snoozes;
the 2 handed on are CD and BT, whom the page refuses); snooze scenario 17 of
19. Every beat on copy B for those steps was written by Go's stamp; the undo
redraws were read in the background and stamped nothing.

| Run | Scenario | Answers | `go run ./cmd/shadow` (as printed) |
|---|---|---|---|
| 1 | unsnooze_todo, before the last_login fix | 0 of 20 differently | `user DIFFERS: 1 rows only in a, 1 only in b` / `1 of 4 changed tables differ` — IA's row, column `last_login` only (the runner's force_login) |
| 2 | unsnooze_todo | 0 of 20 differently | `user same (7 rows written on each)`; `4 of 6 changed tables differ`: one slow-request incident Django raised on A (`/today/unsnooze` 4572 ms over the 3000 ms SLO under load: admin_system_incident, its two audit rows, two events, one notification) — timing, not the save |
| 3 | unsnooze_todo | `18 of 20 steps made by Go, 2 handed on` / `0 of 20 steps answered differently` | `366 tables, 4 changed by the runs` / `user same (7 rows written on each)` / `0 of 4 changed tables differ` |
| 4 | snooze_todo | `17 of 19 steps made by Go, 2 handed on` / `0 of 19 steps answered differently` | `366 tables, 4 changed by the runs` / `user same (8 rows written on each)` / `0 of 4 changed tables differ` |

With `-all`, runs 3 and 4 differ only in the request-noise tables
(django_session, interaction_event, login_event, presence_time): the seconds
credited are wall-clock gaps two runs cannot share. Compared by key instead
(`$SP/agent49_slots.sh`, run 4): `presence_time slots credited: a 14, b 14,
same keys: yes`; `login_event sign-ins credited: a 8, b 8, same ids: yes`.
Agent 46's run showed 5 differing user rows (doc 63); none remain.

**A page view Go serves leaves the same stamp as the existing feed's.**
`$SP/agent49_pageview.sh`: fresh copies; the existing application on copy A
(127.0.0.1:8221), a Go-only gateway on copy B (127.0.0.1:8721); `cmd/parity`
for all 29 seed accounts over `/staff-activity` (every period, filter and
page: 1371 answers, Go answering on B, the feed on A) and `/clusters/` (29,
an error on both sides: not a feed path, so no view; it proves nothing);
then an md5 of every person's beat columns, of every presence_time slot and of
every pre-existing sign-in's credited time, before and after, on both copies:
all six digests identical before and after on A and on B
(`ccc3f7d2…`, `17515461…`, `a8fb4eb9…`). Neither side stamps a page read by
the app, as 65.1 measured. Parity itself printed `1371 answers compared, 58
differing`: 40 are Admin's and CD's sign-in counts one higher on B (the
parity tool signs in through the gateway, which records the sign-in on B
only) and 18 are Staff Activity's known hand-ons ("This screen is not
available here yet"); none is presence.

## 65.6 Tests

- `internal/presence` unit tests: the 15 footprint and 18 describe samples
  the existing functions computed; `Touches`; the call planned for a beat on
  a page, no beat, a beat with no page, an untracked page, a bearer, a long
  sign-in id; the thresholds.
- Integration (`edify_gorn_a21_test`): `TestPresenceStampIsTheMiddlewaresBeat`
  (a read, a background read and a background post write nothing; a post
  writes the page from HX-Current-URL and the action, credits the 100 s since
  the beat before to its slot and sign-in; a second post at once credits
  nothing; a bearer post moves only the time; nobody else's row changes),
  `TestThePresenceFunctionIsNarrow` (owner, its exact column writes, no
  whole-table right, EXECUTE held by edify_presence_rw and edify_gateway, not
  edify_gateway_ro, edify_todos_rw or PUBLIC; out-of-range thresholds
  raise), and the extended `TestGatewayRoleCanNeitherWriteNorReadSecrets`;
  the todosnooze tests still pass.

## 65.7 What is left

- **The sign-in id of a beat.** The middleware writes the session's
  `_edify_login_event` into `last_seen_login_id`; a Go save carries no Django
  session, so Go leaves the column as it is (the sign-in the person's own
  sign-in already wrote there). The gateway's own sign-ins (signin/store.go)
  record a login_event but put nothing on the person's row, and Django's web
  sign-in (`record_login`) puts the person on `/dashboard` with that sign-in:
  when Go serves the web's sign-in, that beat is still to be made.
- **A session's reads.** Go answers no web-session read today; if it does,
  the slide (once per `refresh_interval`) and the htmx throttle (15 s) live in
  the Django session and need a home (the access token's session, say) before
  `Touches` can answer true for a read.
- **The app's saves** are stamped by their form_only POST to the existing
  feed (65.1); when that read moves to Go, stamp the bearer post with
  `presence.Stamper`.
- Nothing calls the Today saves from a client yet (doc 63): the caller must
  pass HX-Current-URL as `Page` and fetch the redraw with
  `X-Edify-Background: 1`.
- **Production needs the owner's approval at cutover** for the new role,
  schema and function.
