# 43. The notification centre, read by Go, for the Next.js web app

Owner brief (2026-11-11): Go as the application backend, Next.js for web
browsers. The notification centre (`/notifications`,
`apps.frontend.views.staff_views.notifications_page_view`,
`templates/pages/notifications/index.html`) is the signed-in person's own
notifications with two figures, filters, pages, and "How you are told".
The app's page feed does not serve it (`notifications` is in neither
`CCEO_PAGES` nor `ROLE_PAGES`; reports/agent28_notifications.md), so there is
no feed answer to match: Go's answer is proved against the existing page's
own HTML.

| Piece | What moves | State |
|---|---|---|
| 1 | The page as it opens and under every filter, search and page: the figures, the filters and their choices, the notifications in order with every part the template draws, the pager, the delivery settings | Built and proved (this document); **not served by the gateway until a notice's words may be read** (43.5) |
| 1 | The Next.js page `/notifications` drawn from that answer | Built; typecheck, lint, tests and build pass; not looked at in a browser (43.4) |
| 2 | Mark read, Mark All Read, Archive, Archive All Read, the delivery settings' Save (`notifications_page_view` POST, `mark_notification_read`, `mark_all_notifications_read`, `notification_settings_view`) | Still the existing application's; BACKLOG `notifications-2` |
| — | The top-bar drawer (`/notifications/drawer`), `open_notification` | Not part of this item |

## 43.1 What was built

`NotificationCenterService.GetNotificationCenter`
(`platform/proto/edify/screens/v1/notification_center.proto`) is answered
by `platform/backend/internal/notificationcenter` (one line in
`internal/server/server.go`). A dedicated contract, like the School
Directory's (28.1), because the page is not one of the feed's pages.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("dashboard")` and `can_open_url`: every role but Cluster Leader (permission denied, the existing Access Denied). An acting appointment opens it in its acting role. The existing refusal writes an audit row; the comparison never renders a refused page (it records the refusal from the exported door) |
| The figures | Over the live notifications (`exclude(status="archived" \| resolved_at set)`): Action required (unread and needing a response) and Critical tasks (unread, urgent). The view's total and unread are not shown by the template and are not in the answer |
| Status | Absent = all live ones; any other value, an empty one too, is `status = value` (so "nonsense" and `status=` list nothing and select no option). `status` is `optional` in the contract to keep absent and empty apart |
| Priority, category, Action Required Only | `filter(priority=…)`, `filter(category=…)`, `action_required=true` exactly (`yes` is off) |
| Search (top bar, `q`) | `title icontains q OR body icontains q`, Django's PostgreSQL form: `UPPER(col::text) LIKE UPPER(%q%)` with `\`, `%`, `_` escaped |
| Order and pages | `-created_at, -id`; 50 a page (`TABLE_PAGE_SIZE`, the template comment's "25" is stale); the page read as `max(1, int(raw or 1))` (`1_0` is 10, `abc` and `-1` are 1), clamped to the last page; the pager only past one page, its numbers by `make_pagination_window(window_size=1)` (sent as `page_numbers`, 0 for a gap) |
| A notification | title; category and priority as `|title` words ("Critical" for urgent; Django's title filter, apostrophe and digit rules included); the Action Required badge only while unread; the body when not empty; `created_at|date:"M j, Y H:i"` in `Africa/Nairobi`; "From {name}" when the sender's `user.name` is found (any user row, deleted ones too, newest first, as the subquery reads it); "Link: TYPE (id)" when there is a context type, the id written "None" when missing; the record's button when there is a route, "Open Record" when it names no words; Mark read while unread; Archive unless archived |
| Category choices | `values_list("category").distinct()` under `Meta.ordering = ["-created_at"]`, which makes the statement distinct on (category, created_at): a category is listed again for each moment one was raised (43.3) |
| How you are told | the preference row (both on when there is none), the account's address, email set up only when `EMAIL_PROVIDER=resend` and `RESEND_API_KEY` is present (the mailer's `is_configured`, read from the same environment, the key's value never read), the "Don't email me about" boxes over the person's categories and those already muted, sorted, "Saved." after `settings=saved` |

The door, statuses, priorities, the priority the page calls Critical, the
default status, the page size and the email rule's names are exported to
`internal/notificationcenter/rules.json` by
`manage.py export_notification_center_rules`;
`apps/notifications/test_notification_center_rules_export.py` fails when they
differ, and checks the email rule against `MailerService` itself. Words that
live in the template are written in the web app (and in the comparison tool).

## 43.2 How it is proved

`platform/backend/cmd/notificationparity/django_reader.py` (run with
`manage.py shell`) renders `/notifications` with the existing view and
template, unmodified, called directly with the feed's own `_page_get`
request (no sign-in, session or middleware writes), for every account and
32 questions (each status, an empty and an unknown one, each priority and an
unknown one, three categories and an unknown one, `action_required=true` and
`=yes`, five searches including `%` and `_`, pages 2, 999, 0, -1, abc, 1_0,
`settings=saved`, two combinations), and reads the HTML into what a person
sees: the two figures, each select's chosen option, the box, the search,
the Category options in order, every notification in order (unread tint,
icon colour, title, pills, badge, body, time, sender, link, button and its
address, Mark read, Archive, its id where the row carries one), the empty
state, the pager (summary, numbers, current, Prev/Next) and the settings.
`go run ./cmd/notificationparity` asks Go the same questions (through a
gateway with `-gateway`, or the Go service over a database with `-db`), lays
the answer out as the template does, and compares key by key with rows,
categories and page numbers compared **in order** (no re-sorting).

Run on 2026-11-13, as printed:

```
# development database, Go service read directly (-db), all 29 accounts
928 compared, 4 differing
# the 4: admin@'s live incident notice "… seen 9192×" read by Django, "seen 9228×"
# by Go a moment later (the running system updates it); admin@ alone again:
32 compared, 0 differing

# shadow copy edify_shadow_s21_a with rows made for the comparison, all 29
# accounts, the 32 questions plus 14 (category follow_up / o'neil's / empty,
# priority weird, searches "<b>", "100%_", "  spaced", pages 3–5, read and
# archived page 2, a repeated status, urgent + action required)
1334 compared, 0 differing

# the same copy, two accounts, Django with EMAIL_PROVIDER=resend and a key set
64 compared, 0 differing      (Go with -email-configured)
64 compared, 64 differing     (Go without it: the comparison sees the notice)
```

An earlier run through the Go-only gateway on 8083 (before 43.5 was found,
with a `body` grant that has since been revoked) printed 592 "same" lines
and 16 differing, all admin@'s incident counter as above, before it was
stopped.

The shadow rows (`$SP/agent33_enrich.sql`, on the shadow copy only): 380
notifications for cceo@ (every priority including one the choices do not
have, every status, resolved ones, three to a moment so ties on
`created_at` reach the Category list, senders that exist, do not exist and
none, titles with markup, extra spaces and apostrophes, bodies empty, NULL
and multi-line, routes with `&`, routes and words missing, contexts with no
id, categories with underscores, an apostrophe, a digit and an empty one),
four read and archived for pl1@, three preferences (email or push off,
a muted category the person has no notification of), partner@'s all
resolved, ia@'s removed. No record was made on the development database.

## 43.3 Found by comparing

- **The Category list repeats categories** (existing behaviour, kept): the
  distinct runs over (category, created_at), so admin@'s select offered
  "Availability" 95 times among 96 options when compared. Go answers the same list; the web page draws each
  category once (the only place it departs from the answer; a select with one
  value twice is the bug). Fixing it in the view (`.order_by()` before
  `.distinct()`) is the owner's call.
- **Plan-dependent order among ties.** For categories raised at the same
  moment, PostgreSQL's order follows the plan: a cached generic plan (pgx's
  prepared statements, after five runs) groups by another key and lists them
  in another order than the existing application's client-bound statement.
  Go asks that statement unnamed (`pgx.QueryExecModeExec`) so it is planned
  as Django's is; the shadow run went from 46 differing to 0.
- A notification that is read and has no record shows no id at all on the
  existing page; the comparison compares ids only where the page shows one.

## 43.4 The web page

`platform/web/src/app/(app)/notifications/page.tsx`, `src/lib/notificationCenter.ts`,
`src/components/notifications/{NotificationList,DeliverySettings}.tsx`: the
header (Communication, Notifications, the line, Mark All Read and Archive All
Read), the two-figure strip, the Status / Priority / Category row (FilterBar,
the template's choices), Action Required Only and Reset Filters, the list,
the pager, "How you are told". The top-bar search is the page's ("Search
notifications…", `pageSearch.ts`). Each record's button opens the record on
the existing web. Mark read is the existing link; Archive, the two bulk
buttons and the settings' Change open the existing page, where they are
saved (piece 2). While the gateway refuses the page (43.5) the web page
says it has not moved and opens the existing one.

Checks: `npm run typecheck` clean, `npm run lint` clean, `npm test`
"Test Files 9 passed (9) / Tests 69 passed (69)" (the layout helpers and the
two components rendered to markup), `npm run build` "✓ Compiled successfully",
route `ƒ /notifications`. **Not looked at in a browser and no screenshots**:
a gateway that serves the page needs the decision in 43.5.

## 43.5 What is left

- **A notice's words.** The page shows and searches `notification.body`, and
  `TestGatewayRoleCanNeitherWriteNorReadSecrets` refuses that column to the
  gateway's role ("read a notice's words"). `roles.sql` grants the page's
  other columns only, and the Go service asks
  `has_column_privilege('notification', 'body', 'SELECT')` first: without it
  the gateway answers `unavailable` ("The notification centre is not served
  here yet.") rather than a page without bodies and with a search that
  fails. The coordinator's decision: a narrow view or grant for the reader's
  own notices, or keep the page on the existing application. The integration
  test lends the grant for one test and revokes it.
- Piece 2, the saves (BACKLOG `notifications-2`).
- The rows-per-page and the drawer are not part of the page.

## 43.6 Tests

- `internal/notificationcenter/page_test.go`: the title filter, the page
  number as `int()` reads it, the LIKE escaping, the time zone, the pager
  window, a notification's parts for each status, absent and empty status,
  every filter's clause, the door and the acting role, muted categories, the
  email rule.
- `internal/integration/notification_center_test.go`: refused without a
  notice's words under the shipped grants; with them, hr@'s own notices (live
  ones newest first, resolved and archived left out of the figures, the
  archived list, an empty status matching nothing, the sender, "None" and
  "Open Record", the preference with a muted category it has no notice of);
  a Cluster Leader is refused and no session is unauthenticated.
  `go test -tags integration -run 'TestTheNotificationCentre|TestGatewayRoleCanNeitherWriteNorReadSecrets'`: all pass.
- Checks: `gofmt -l .` empty, `go vet ./...` clean, `go test -race ./...`
  pass; `ruff check`, `ruff format --check`, `bandit -q -r` clean on the
  Python; the drift test "Ran 2 tests … OK".
