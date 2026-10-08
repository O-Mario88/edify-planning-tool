# Session Lifetime and Two-Step Verification

Two controls that both answer the same question — *is the person at this
browser still the person who signed in?* — and that are documented together
because they fail in complementary ways. The idle timeout limits what an
unattended browser is worth. The second factor limits what a stolen password is
worth.

## 1. Sessions end after thirty minutes of inactivity

Thirty minutes of **inactivity**, not thirty minutes total. Someone working
through a long planning session is never signed out mid-task; a laptop left
open in a shared office stops being a way in after half an hour.

### Settings

| Setting | Value | Why |
|---|---|---|
| `SESSION_COOKIE_AGE` | `1800` (`SESSION_IDLE_TIMEOUT_SECONDS`) | The window. |
| `SESSION_SAVE_EVERY_REQUEST` | `False` | Deliberately off — see below. |
| `SESSION_ENGINE` | `cached_db` when Redis answered, else `db` | |

### Why the window slides on a throttle

`SESSION_SAVE_EVERY_REQUEST = True` is the obvious way to get a sliding
window: Django re-stamps the expiry on every response. It works, and it costs
an `UPDATE` on one hot `django_session` row for **every authenticated request
in the product** — every page, every htmx fragment, every background poll. The
IA dashboard query budget caught it immediately, going from 60 queries to 61.

`apps.core.middleware.SlidingSessionMiddleware` does the same job on a
throttle. It writes a `_last_touch` timestamp into the session at most once per
`refresh_interval`; touching the session is what marks it modified, which is
what makes `SessionMiddleware` save the row and re-send the cookie.

The interval is `SESSION_COOKIE_AGE // 30` — sixty seconds for a thirty-minute
window. The cost is bounded and one-directional: a session can end up to one
interval **early**, never late. That is 3.3% of the window whatever the window
is set to, and it errs on the safe side.

The middleware must be listed **after** `SessionMiddleware` in `MIDDLEWARE`.
Response phases run in reverse order, so "after" in the list means "before" at
response time — which is when the session has to be touched for
`SessionMiddleware` to notice and save it.

### What counts as activity (owner, 2026-10-08)

> "make sure the session expires after 30 minutes of idle"

Only a request a person makes slides the window. Until 2026-10-08 every
request did, and a page makes requests of its own: it listens to the live
stream, reads itself again whenever a colleague changes the plan, reports its
own script errors, and the browser fetches the service worker. A page left on
screen therefore kept its session for as long as the office was open, and the
timeout only ever ended the session of a closed laptop or a hidden tab.

| Request | Slides the window |
|---|---|
| A page opened, a link followed, a form saved, an htmx action | Yes |
| The activity heartbeat (`POST /staff-activity/beat`) | Yes, to the moment the page was last touched |
| A page re-reading itself (`X-Requested-With: EdifyLive`) | No |
| The live stream being opened (`/api/realtime/stream`) | No |
| An htmx request nobody triggered from a page untouched for five minutes (`X-Edify-Background: 1`) | No |
| The page asking whether it is still signed in (`/login/state`) | No |
| The defect beacon, the service worker, the manifest, the favicon | No |

Idle means untouched: no click or tap, no key, no scrolling. Moving the mouse
over a page is not a touch, and neither is reading it. Someone reading a long
page should scroll it; someone typing a long entry is never idle, because the
heartbeat tells the server so once a minute without their sending anything.

Three things enforce it:

1. **The rule is the last use, not the last save.** The middleware keeps the
   moment of the last request a person made (`_last_touch`, in the session)
   and, on the way in, ends a session whose last one is a window old. The
   row's own expiry cannot be the rule, because every save pushes it out and
   a view may save the session while answering a request the page made by
   itself.
2. **The heartbeat reports the touch, not itself.** It is sent for five
   minutes after the last touch (`STAFF_ACTIVITY_IDLE_SECONDS`) and carries
   how long ago that touch was. Counted as "now", each sitting would have
   ended thirty-five minutes after the person stopped.
3. **The stream ends with the session.** A live stream is admitted once and
   then runs by itself. It is closed when the session it was opened under
   would end if nobody used it again; the browser reconnects on its own and
   is admitted or refused like any other request.

### What the person sees

A page untouched for the window asks `GET /login/state`, which answers
`{"signedIn": false, "remaining": 0}` once the session has ended, and the page
shows the "Session paused: sign in to continue" dialog the shell already had
for a session that expired under an htmx request. The page and anything typed
on it stay where they are, behind the dialog.

The server answers, not the page's own clock, because the page cannot know
about the tab beside it that is still in use: with another tab at work the
answer is `{"signedIn": true, "remaining": N}` and the page asks again in N
seconds. A laptop that slept asks as soon as it wakes.

In the Staff Activity Log such a sitting reads "Timed out after …", as it
always has: nothing signs the person out, the session simply ends.

### A related fix

`SESSION_ENGINE` used to be selected on `_redis_url`, which has a default and
is therefore always truthy — so it read `cached_db` even when the cache had
fallen back to `LocMemCache`. `LocMemCache` is per-process: each worker would
have kept its own copy of every session, and a session ended or changed on one
worker would have stayed live in the others until their entries lapsed. The
condition is now `_use_redis` — whether a connection actually answered.

### "Remember me"

Prefills the email address next time, in a cookie holding nothing but that
address. It does not, and can no longer, extend how long an unattended session
lives.

## 2. Two-step verification

After the password, a single-use code is sent to the person's email or phone.
All policy lives in `apps.accounts.mfa_service`; the views are about screens.

### What it guards against

| Threat | Control |
|---|---|
| Stolen password | A correct password reaches a code prompt, not a session |
| Guessed code | `MAX_ATTEMPTS = 5`, then the challenge is dead — the correct code stops working too |
| Grinding the code space | `MAX_CHALLENGES_PER_WINDOW = 10` per hour per account |
| Replayed code | Single-use; spent the moment it is used |
| Leaked database | Only the SHA-256 hash of the code is stored |
| The form used to bombard a phone | `MAX_DELIVERIES = 4`, `RESEND_INTERVAL = 30s`, and resending never extends the deadline |
| Enrolment as a lockout | A channel that cannot deliver is not offered, and the account falls back to email |

`MAX_ATTEMPTS` alone is not enough, and that is worth stating plainly: it kills
one challenge, which on its own only forces an attacker holding a stolen
password to open another — five fresh guesses per round, for as many rounds as
they like. `MAX_CHALLENGES_PER_WINDOW` is what turns that into a wall.

### Both login surfaces

There are two ways into this product and the factor holds on both. Enforcing it
only on the web sign-in would have left `POST /api/auth/login` issuing a full
token pair for a password alone — a code prompt beside an open window.

**Web** (`apps/frontend/views/auth_views.py`) — between the password and a
session there is a waiting room: three values in the session saying which user
passed the password check, which challenge they must answer, and when the
attempt started. It is not a login. `request.user` is still anonymous and no
permission check anywhere consults those keys. The session key is cycled on
entering the waiting room and again by `django_login` on leaving it, so a
planted cookie never becomes a live session.

    POST /login          → 302 /login/verify
    POST /login/verify   → 302 /dashboard
    POST /login/resend-code

**Token API** (`apps.accounts.auth_services`) — no session, so the client is
handed an opaque `mfaToken` (32 random bytes, stored hashed) to present back
with the code.

    POST /api/auth/login         → {"mfaRequired": true, "mfaToken": "...", ...}
    POST /api/auth/login/verify  → {"accessToken": "...", ...}

Every rejection on the API is the same generic `401`: an expired challenge, an
unknown token and a wrong code must be indistinguishable to whoever is holding
a stolen password. The real reason goes to the audit log.

### Enrolment

Per user, from **Settings → Two-step verification**, plus
`MFA_REQUIRED_FOR_ALL` to require it across the estate (in which case nobody
can turn it off, but everyone can still choose the channel).

Email is always available. SMS needs both a number on the account and a
configured provider; when it is unavailable the option says which of the two is
missing and whether the person can fix it themselves.

### SMS delivery

`apps.core.sms` mirrors `apps.core.email`: console by default, Africa's Talking
when `SMS_PROVIDER=africastalking` with `SMS_API_KEY` and `SMS_USERNAME`.

A 200 from the provider is not delivery. Africa's Talking answers 200 with a
per-recipient status, and an invalid number comes back inside that envelope —
so the response body is read rather than the status code. `send` never raises:
a provider outage degrades into "we could not send the code", not a stack trace
on the sign-in page.

### Housekeeping

`mfa_challenge_purge` (daily 03:20) deletes challenges dead longer than
`MFA_CHALLENGE_RETENTION` (7 days). A row is written for every sign-in by every
enrolled account, and each spent row holds the hash of what was briefly a
credential.

### Local development

Neither the console mailer nor the console SMS sender writes the message body
to the log by default — the body carries a live code, which outlives the
message in a log stream. Set `EMAIL_LOG_BODIES=1` or `SMS_LOG_BODIES=1` in a
local `.env` to read them; both are refused in production regardless.

(`EMAIL_LOG_BODIES` had been read by `apps.core.email` since the log-leak fix
but was never defined as a setting, so the opt-in was unreachable and there was
no way to see an invitation link or a sign-in code locally.)

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `SESSION_IDLE_TIMEOUT_SECONDS` | `1800` | Idle window |
| `MFA_REQUIRED_FOR_ALL` | `false` | Require the second factor on every account |
| `SMS_PROVIDER` | `console` | `console` or `africastalking` |
| `SMS_API_KEY`, `SMS_USERNAME` | — | Both required for the live provider |
| `SMS_SENDER_ID` | `""` | Optional alphanumeric sender |
| `SMS_LOG_BODIES` | `false` | Log SMS bodies (non-production only) |
| `EMAIL_LOG_BODIES` | `false` | Log email bodies (non-production only) |

## Tests

- `apps/accounts/test_session_idle_timeout.py` — the sliding window, idle
  expiry, what the throttle costs and saves, that the cache copy never
  outlives the window, that only a person slides it, what `/login/state`
  answers, and when a stream is closed
- `apps/accounts/test_mfa.py` — written from the attacker's side: what a
  stolen password reaches, guessing, replay, session fixation, the resend
  ceiling, the challenge rate limit, and the token API
- `apps/core/tests/test_sms.py` — provider selection, the body-logging gate,
  and that a 200 with a refused recipient is not reported as delivered
