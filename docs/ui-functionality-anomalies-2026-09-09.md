# UI and functionality anomaly follow-up — 9 September 2026

The screenshots exposed states the earlier route audit did not validate: visible icon data, text escaping a status label, and an older cached offline page. This follow-up fixes the shared causes and adds checks for those states.

## Changes

- Empty states accept SVG path data through `icon_path` and render it inside an SVG. Projects, project impact, visit requests and the PL review queue use the corrected contract. Path commands no longer appear as visible text.
- Shared status badges wrap within their available width. The My Targets priority portfolio uses the full available width for a responsive card grid instead of four narrow columns with mostly empty groups. It renders every returned action: the former eight-row slice hid the ninth SSA action while still displaying a count of nine.
- Offline cache versions include the fallback template, base template and outbox script, including development builds without a static manifest. Template-only updates can replace the cached screen.
- The cached offline page includes its critical outbox code and fallback styling. Queue review, retry and discard do not require an uncached external script or stylesheet. Connection state updates on reconnect/disconnect, and a failed navigation is explicitly marked because `navigator.onLine` can remain true when the server is unreachable.
- Replay uses a cross-tab Web Lock so two open tabs cannot send the same queued entry concurrently. Browsers without Web Locks retain the existing per-page guard; this is not server-side exactly-once delivery.
- Charts waiting to enter the viewport now have a bounded idle callback delay so a busy browser cannot postpone a visible chart indefinitely.
- The shared HTMX filter hook retains the visible top-bar query when the search form includes a separate filter form. Changing a filter no longer silently drops that query. Forms using native `form=` association retain their existing behavior.

## Verification

- 268 related regression tests passed across page anomalies, PWA, priority portfolio, debriefs, filter contracts and the shared design system.
- The final outbox/source/priority subset passed all 50 tests after cross-tab locking was added.
- All 65 table, KPI, card and page inventory checks passed.
- The expanded authenticated audit passed all 14 roles and 1,051 permitted role/page combinations.
- All 26 applicable browser journeys passed across Chromium, Firefox, WebKit, Android, iPhone and tablet profiles. Four service-worker navigation cases are intentionally skipped outside Chromium; offline queue and cross-tab replay cases run in every profile.
- Lint, formatting, Django system checks and generated CSS reproducibility passed.

Browser regression coverage includes populated FY2026 Projects/My Targets/Debriefs, all priority actions, chart rendering on scroll, three themes and 390/768/1366 px widths; debrief advanced filters and the new-debrief form; combined search/filter changes on Debriefs, Planning, Special Projects Planning and Clusters; offline fallback navigation and recovery; and queued-action ordering across a temporary server failure, successful retry and an attention-item discard.

Outbox browser tests use isolated browser storage and intercepted synthetic action requests. They verify client behavior without submitting operational records. Backend debrief tests exercise service and permission behavior in the test database.

The role/page audit now checks visible empty-state icon text and overflowing status badges in addition to HTTP/runtime failures, document overflow, named controls and generated CSS coverage. Route coverage is not a claim that every possible production-data state or external integration has been exercised.
