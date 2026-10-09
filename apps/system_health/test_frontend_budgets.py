"""The weight of what a page sends may only go down.

Every page extends ``templates/base.html``. So every stylesheet it links, and
every script in its ``<head>``, is downloaded before a field officer's phone
paints anything on a first visit, over a mobile connection. And every byte a
page's HTML carries is rendered by the web process and parsed by the phone on
every visit. Nothing measured either, so both grew a file and a panel at a
time.

The 2026-09-24 audit measured them:

- The shell links 17 render-blocking stylesheets, 1.3 MB of CSS (194 KB
  gzipped), plus three parser-blocking scripts in ``<head>``. It also repeats
  39 KB of inline script on every page.
- A CCEO's notifications page was 557 KB of HTML, because it drew a hundred
  cards. It now pages them 25 at a time.

The ceilings below are those measurements, a ratchet and not a target. Lower
one when you cut; a change that has to raise one says here what it buys.

Run just these gates:

    python manage.py test apps.system_health.test_frontend_budgets
"""

from __future__ import annotations

import gzip
import os
import re
from datetime import date, timedelta

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase
from freezegun import freeze_time
from django.utils import timezone

BASE_TEMPLATE = settings.BASE_DIR / "templates" / "base.html"
STATIC_TAG = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]\s*%\}""")
PRINT = os.environ.get("EDIFY_PRINT_BUDGETS") == "1"


def _gzip_kb(data: bytes) -> float:
    return len(gzip.compress(data, 6)) / 1024


def shell_assets() -> dict:
    """What base.html makes every page load, from its source."""
    text = BASE_TEMPLATE.read_text()
    head_end = text.lower().index("</head>")
    stylesheets, scripts = [], []
    # Case-insensitive, as HTML is: <SCRIPT> is a script too.
    for match in re.finditer(r"<(link|script)\b[^>]*>", text, re.I):
        tag = match.group(0)
        kind = match.group(1).lower()
        found = STATIC_TAG.search(tag)
        if not found:
            continue
        path = finders.find(found.group(1))
        data = open(path, "rb").read() if path else b""
        entry = {
            "path": found.group(1),
            "bytes": len(data),
            "gzip_kb": _gzip_kb(data),
            "in_head": match.start() < head_end,
            "missing": path is None,
        }
        if kind == "link" and re.search(r'rel="stylesheet"', tag, re.I):
            entry["render_blocking"] = not re.search(r"\bmedia=", tag, re.I)
            stylesheets.append(entry)
        elif kind == "script":
            entry["parser_blocking"] = entry["in_head"] and not re.search(
                r"\b(defer|async)\b|type=\"module\"", tag, re.I
            )
            scripts.append(entry)
    inline = sum(
        len(m.group(1))
        for m in re.finditer(r"<script\s*>(.*?)</script\s*>", text, re.S | re.I)
    )
    return {"stylesheets": stylesheets, "scripts": scripts, "inline_bytes": inline}


class ShellAssetBudgetTest(SimpleTestCase):
    #: Measured 2026-09-24 (see the module docstring), plus 3 % for the
    #: gzip level and line endings; ratchet, not target.
    #:
    #: JS_GZIP_KB was 115. Raised to 124 on 2026-09-26 for one thing: the
    #: Edify calendar (static/js/date-picker.js, 8.4 KB gzipped), which the
    #: owner chose over the browser's own date picker on every date field.
    #: It is deferred, so it does not block a first paint. Its styles went
    #: into form-refinement.css rather than a sheet of their own, so the
    #: stylesheet count held at 17.
    RENDER_BLOCKING_STYLESHEETS = 17
    #: Raised to 202 on 2026-09-27 for the phone pass the owner asked for
    #: (199.0 to 201.0 KB, +1%): KPI strips as a grid on phones, a record's
    #: Actions beside its name, pinned selection columns, invisible 44px touch
    #: squares, drawers sized to the screen, blue title bands with white text
    #: on every table and heading rows that fit a phone.
    #:
    #: Raised to 203 on 2026-09-27 (201.0 to 202.6 KB, +0.8%) for the compact
    #: page chrome the owner asked for: phone controls and badges on a smaller
    #: step, rows that reach the screen's edge, one-row filters with an ×,
    #: School Directory rows like Planning's, and details that wrap.
    #:
    #: Raised to 204 on 2026-09-29 (203.0 to 203.05 KB) for Country Oversight:
    #: its five-part stacked bars' shared tooltip draws
    #: `apexcharts-tooltip-series-group-4`, which holds the legacy pattern
    #: "p-4", so the name joined that pattern's index in two shared sheets
    #: (the route audit checks every class on a page against the index).
    #:
    #: Raised to 205 on 2026-10-01 (203.6 to 204.2 KB, +0.3%) for the audit
    #: pass the owner asked for: the wide-screen frame and 144rem canvas, the
    #: sidebar's group disclosures and Find a page, disabled primaries that
    #: look disabled, cluster facts in columns and HR Today's folded rows. Dead
    #: sidebar rules and comments were cut first; this is what was left.
    #:
    #: Raised to 206 on 2026-10-02 (204.8 to 205.85 KB, +0.5%) for what the
    #: owner asked for that day: "fix all the padding on every card so that
    #: everything is well aligned ... tabs inside the cards should be aligned
    #: with the content inside the cards". Measured on 324 pages, a card's
    #: title sat on the 16px line in 160 of 532 cards and a table's first
    #: column in none of 232; the rules that put them there (consistency.css,
    #: ONE CONTENT LINE), the tab strips that scroll sideways, and KPI figures
    #: on one row are 1.06 KB. They add one `!important` between them: the
    #: rest hand existing rules a variable. The script that marks the cards
    #: fitted inside the JavaScript ceiling with its comments cut.
    #:
    #: Raised to 246 on 2026-10-05 (205.8 to 245.8 KB) for one thing: the
    #: build now writes each long `:is()` list out as one selector per
    #: alternative (scripts/split_selector_lists.cjs). They are the same
    #: rules, matching the same elements at the same weight — 365 page states
    #: compared value by value — and 40 KB heavier gzipped, downloaded once
    #: and then served from the cache. In exchange a browser files each rule
    #: under its class instead of trying the whole list against every
    #: element: 49-64 % less style recalculation on every page load, at every
    #: width (docs/performance-forensic-audit-2026-10-05.md, F16). This is
    #: the one case where the ceiling is the wrong measure of the cost; it
    #: stays a ratchet for everything else.
    #:
    #: Raised to 246.5 the same day (245.8 to 246.19 KB) for one more: five
    #: rules ask their question of the element they style instead of an
    #: ancestor with `:has()` — a hand-written page header's last child, a
    #: school row's icons, a title beside one action, a KPI caption — or read
    #: an attribute the template writes (the search box), and the pinned
    #: table column reads one the shell script keeps on the row's box cell.
    #: The selectors are 0.4 KB longer; one element added to a page restyles
    #: 2-4 % of it at every width, where it was a fifth to a quarter (the
    #: same report, F19 and F20).
    #:
    #: Raised to 247 on 2026-10-09 (246.497 to 246.508 KB). Two pull requests
    #: merged twelve minutes apart on 2026-10-08, each inside the ceiling on
    #: its own: #240 added one declaration to drawers.css, the scroll padding
    #: that keeps a field a drawer brings into view clear of its pinned
    #: footer (0.011 KB), and #239 its table and link rules. Together they
    #: were eight bytes over, main's suite failed and nothing deployed. Half
    #: a kilobyte, as the script budget moves: this is a ratchet.
    CSS_GZIP_KB = 247
    PARSER_BLOCKING_HEAD_SCRIPTS = 3
    #: platform-status.js also lets the upload drawer's request through
    #: offline (2026-09-26), so the service worker can open it without signal:
    #: 89 bytes, inside the calendar's allowance.
    #:
    #: Raised to 130 on 2026-09-27 for static/js/top-layer.js (5.9 KB gzipped,
    #: deferred): every dropdown opens down from its button and every overlay
    #: covers the window, in the browser's top layer, after the Core Schools
    #: Actions menu opened "fixed in one position and hidden" (owner). It
    #: replaced rowMenu's, the rail menu's and the calendar's own placement
    #: code, so the net growth is 5.5 KB (123.9 to 129.4).
    #:
    #: Raised to 131 on 2026-09-27 (129.4 to 130.8 KB, +1.1%) for micro-ux.js
    #: giving every small control an invisible 44px touch square and letting a
    #: table's title bar keep its count and buttons (and an empty table region)
    #: take the blue band.
    #:
    #: Raised to 134 on 2026-09-27 (130.8 to 133.2 KB, +1.8%) for micro-ux.js
    #: filling a phone's rows of controls, indenting a heading's wrapped
    #: caption, filter slots from the row's width with an × Clear, and pinning
    #: a table's identity at its measured tick column.
    #:
    #: Raised to 136 on 2026-09-28 (133.7 to 135.3 KB, +1.2%) for
    #: drawer-background.js opening every drawer's frame on the click, with a
    #: loading body, instead of showing nothing until the server answers
    #: (owner: "even loading is very slow"). Comments were cut to fit.
    #:
    #: Raised to 138 on 2026-09-29 (135.9 to 137.1 KB, +0.9%) for
    #: staff-activity-beat.js (1.1 KB gzipped, deferred): the Staff Activity
    #: Log counts active time only while a page is visible, focused and in
    #: use, which needs a beat from the page itself (owner: replace Who's
    #: Online with an accurate activity log). Its comments were cut to fit.
    #:
    #: Raised to 138.5 on 2026-10-02 (137.98 to 138.27 KB, +0.2%) for the
    #: table scroll hint leaving by itself (owner: "remove the sticky swipe to
    #: view column black pill and make it appear temporarily"). The first wide
    #: table is usually below the fold, so its seconds start when it is on
    #: screen: one observer and a timer in micro-ux.js, 0.29 KB gzipped, with
    #: the reasoning kept in responsive-system.css. Half a kilobyte, not a
    #: whole one: the ceiling had 0.02 KB left and this is a ratchet.
    #: Raised again to 140 the same day (+1.3 KB) for micro-ux.js
    #: letting a record table's long text and long headings wrap on a desktop
    #: when that makes it fit its card, instead of scrolling sideways (owner:
    #: Work Plan and My Plan still scrolled on a 2560px monitor). Its
    #: rationale lives in interactions.css, which is minified.
    #:
    #: Raised to 141.5 on 2026-10-05 (139.98 to 141.42 KB, +1%) for
    #: group-select.js (1.44 KB gzipped, deferred), which the owner asked for
    #: across the platform: "all the places with checkboxes can you add Select
    #: All Checkbox", and tick boxes on planned activities with a bar that
    #: reschedules or cancels the ticked ones together. It is in the shell
    #: because a list of tick boxes can arrive in a drawer on any page. It
    #: adds no stylesheet: the bar is the Planning page's own, and the tick
    #: column uses the classes selection tables already had.
    #:
    #: Raised to 143.5 the same day (141.46 to 143.3 KB) for live-regions.js
    #: (1.9 KB gzipped, deferred), after the owner asked that "every event
    #: should update ... in real time and fast": a page that shows the plan
    #: listens to the stream the server already had and reads its marked
    #: regions again when the plan changes. It opens a stream only on a page
    #: that has such a region, and closes it while the tab is hidden.
    #:
    #: Raised to 144 the same day (143.3 to 143.8 KB) for group-select.js
    #: reading a ticked school as well as a ticked activity, after the owner
    #: asked that the lists the summaries open take the group actions too:
    #: the bar's Assign to partner for the ticked schools, and Reschedule and
    #: Cancel for the staff work planned at them.
    #:
    #: Raised to 146 on 2026-10-06 (143.8 to 145.50 KB) when the
    #: performance audit's branch joined these. It adds three things, in
    #: date-picker.js and micro-ux.js, with their comments cut
    #: (docs/performance-forensic-audit-2026-10-05.md):
    #:
    #: - date-picker.js measures the fields of one scan together, and only
    #:   those that are drawn. A field in a closed row has no box, and asking
    #:   for its width made the browser lay that row out: on Strategic
    #:   Priorities (98 date fields in closed rows) that was 10 of the page's
    #:   11.4 seconds of main-thread time, and it is 1.3 seconds now (F1).
    #:   0.32 KB.
    #: - A phone's page is fitted once. A phone reports the viewport it
    #:   settled on as a resize event with its first frame, and every rail
    #:   and table was measured and fitted again 150ms later: three of the
    #:   ten whole-page style and layout passes of opening My Plan on a
    #:   phone. When no resize has arrived since the page was fitted, that
    #:   one re-measures nothing (F17).
    #: - Five facts are kept as attributes — a table's rows start with a
    #:   selection box, a row's first cell holds one, a heading row holds no
    #:   block, an action sits beside a tab rail, the search box holds its
    #:   submit button — which the stylesheets used to ask of the table,
    #:   cell, row, rail or box with `:has()`. Asked that way they made a
    #:   browser restyle a whole phone page whenever anything was added to
    #:   it: 2,201 elements for one <span>, about 50 now, and a fifth of a
    #:   desktop page, 2-4 % now (F18, F19, F20).
    #:   e2e/maintained-facts.spec.js holds each attribute to the selector
    #:   it replaced while the page changes under it.
    #:
    #: Raised to 146.5 on 2026-10-08 (145.82 to 146.08 KB) for the session
    #: ending after thirty minutes without a touch (owner: "make sure the
    #: session expires after 30 minutes of idle"). staff-activity-beat.js
    #: already knew when its page was last touched; it now tells the server
    #: with each beat, and a page untouched for the window asks whether it is
    #: still signed in and says so when it is not. 0.26 KB gzipped, no new
    #: file and no stylesheet: the notice is the session dialog the shell
    #: already had. Half a kilobyte, not a whole one: this is a ratchet.
    #:
    #: Raised to 147.5 the same day (146.08 to 147.43 KB) for click-feedback.js
    #: (1.35 KB gzipped, deferred), after the owner reported that on the live
    #: site "it takes too long to switch from the current page to the page
    #: clicked from the side bar menu" and asked for every click's response to
    #: be looked at. Measured: a link that leaves the page changed nothing on
    #: screen until the next page was ready, one to three seconds on the live
    #: site (three to five on its heaviest pages). The script answers a link,
    #: a browser-submitted form and a click-started htmx GET in the frame
    #: after the click with a line across the top of the window, and gives the
    #: sidebar entry pressed the chosen look. It is in the shell because every
    #: page has links that leave it. Its rationale is in base.html and
    #: docs/ui-components.md, not in the file.
    #:
    #: Raised to 148 the same day (147.43 to 147.97 KB) for four faults
    #: the nightly Browser Matrix had been showing in Safari's engine since
    #: 1 October, each fixed where it was:
    #:
    #: - chart-standard.js (+0.36 KB) draws a chart that was asked for
    #:   before the chart library had run. The library is a deferred script
    #:   after Alpine, so a chart an Alpine component draws as it starts
    #:   could ask too soon; it was given up without a word and its card
    #:   stayed empty, on a slow first visit in any browser
    #:   (e2e/chart-library-late.spec.js). alpine-components.js (+0.06 KB)
    #:   has its two charts that checked for the library themselves wait
    #:   the same way.
    #: - date-picker.js (+0.06 KB) leaves a date field that is not drawn on
    #:   its size watch instead of taking it off and putting it back, which
    #:   Safari answered on every frame for as long as the page was open
    #:   (e2e/date-picker.spec.js).
    #: - live-regions.js (+0.06 KB) opens its stream only once the page has
    #:   stayed a second and a half, a section that settles sooner included
    #:   (tests/js/live-regions.test.cjs).
    JS_GZIP_KB = 148
    INLINE_SCRIPT_KB = 40

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.assets = shell_assets()
        if PRINT:
            css = cls.assets["stylesheets"]
            js = cls.assets["scripts"]
            print(
                f"\nshell: {sum(s['render_blocking'] for s in css)} blocking css, "
                f"css gzip {sum(s['gzip_kb'] for s in css):.1f} KB, "
                f"{sum(s['parser_blocking'] for s in js)} blocking head scripts, "
                f"js gzip {sum(s['gzip_kb'] for s in js):.1f} KB, "
                f"inline script {cls.assets['inline_bytes'] / 1024:.1f} KB"
            )

    def test_every_linked_asset_exists(self):
        missing = [
            a["path"]
            for a in self.assets["stylesheets"] + self.assets["scripts"]
            if a["missing"]
        ]
        self.assertEqual(missing, [], "base.html links files the build lacks")

    def test_render_blocking_css_does_not_grow(self):
        blocking = [s for s in self.assets["stylesheets"] if s["render_blocking"]]
        self.assertLessEqual(len(blocking), self.RENDER_BLOCKING_STYLESHEETS)
        weight = sum(s["gzip_kb"] for s in blocking)
        self.assertLessEqual(
            weight,
            self.CSS_GZIP_KB,
            f"render-blocking CSS is {weight:.0f} KB gzipped (ceiling "
            f"{self.CSS_GZIP_KB} KB): every first visit waits for all of it",
        )

    def test_no_new_parser_blocking_script_in_head(self):
        blocking = [s["path"] for s in self.assets["scripts"] if s["parser_blocking"]]
        self.assertLessEqual(
            len(blocking),
            self.PARSER_BLOCKING_HEAD_SCRIPTS,
            f"parser-blocking scripts in <head>: {blocking}. Add `defer`.",
        )

    def test_shell_javascript_does_not_grow(self):
        weight = sum(s["gzip_kb"] for s in self.assets["scripts"])
        self.assertLessEqual(weight, self.JS_GZIP_KB)

    def test_inline_script_every_page_repeats_does_not_grow(self):
        """Inline script is re-sent with every page and never cached."""
        self.assertLessEqual(self.assets["inline_bytes"] / 1024, self.INLINE_SCRIPT_KB)


# The ceilings below were measured on 24 September 2026, and the pages are
# "deterministic up to dates": on the first day of a fiscal year /my-targets
# alone drew 988 elements against a 940 ceiling. The class runs on the day it
# was measured, so a breach means the page grew, not that the calendar moved.
@freeze_time("2026-09-24 09:00:00")
class PagePayloadBudgetTest(TestCase):
    """HTML bytes and element count of the pages a field team lives in.

    The fixture is fixed, so the numbers are deterministic up to dates; the
    margin absorbs those. A page drawing every row of a growing table, or a
    shell that gains a panel on every page, breaks its ceiling here before it
    reaches a phone.
    """

    SCHOOLS = 30
    VISITS = 60
    NOTIFICATIONS = 60

    #: (url, max KB of HTML, max elements). Measured 2026-09-24 on this
    #: fixture plus ~10 %; ratchet, not target.
    #:
    #: /dashboard was 310 KB / 1250. Raised on 2026-09-26 (measured 333 KB /
    #: 1590) for the officer's This Week: the week's own visits drawn in the
    #: page — where the Today view drew a loader and then fetched /today/panel
    #: (287 elements) — and the Salesforce ID, Evidence and Discuss cells on
    #: every past-due row. Empty week tables are not drawn.
    #:
    #: Raised on 2026-10-02 for the pages whose tables now hold fifty rows
    #: where they held ten, fifteen, twenty or twenty-five (owner: "All table
    #: in the platform should hold 50 records in each page"). This fixture's
    #: officer has 60 visits, 30 schools and 60 notifications, so each of
    #: these pages draws a fuller first page: /dashboard was 365 KB / 1750
    #: (measured 485 / 2512), /my-plan 265 / 1760 (262 / 1787), /schools
    #: 265 / 2270 (329 / 3088) and /notifications 265 / 1390 (331 / 1706).
    #: The rows are the cost; nothing else on these pages grew.
    CCEO_PAGES = (
        ("/dashboard", 535, 2765),
        ("/my-plan", 290, 1970),
        ("/schools", 362, 3400),
        ("/planning", 175, 950),
        ("/notifications", 365, 1880),
        ("/todos", 230, 1380),
        # Was 35 KB / 320: each Today row's decisions became one Actions
        # menu (owner, 2026-09-26), carrying its forms and snooze choices
        # inside the row. Measured 44 KB / 335 on this fixture.
        # Elements were 350 (measured 335). Identical To-Dos became one entry
        # (owner, 2026-09-30): a heading row with its count, its first rows
        # and a link to the rest. Measured 45 KB / 362 on this fixture; the
        # rows drawn are no more than before, so the bytes did not move.
        ("/today/panel", 46, 385),
        ("/my-targets", 170, 940),
        # Was 285 KB / 2210. Raised on 2026-10-05 (measured 287 / 2248) for
        # the tick box on each calendar entry the officer may move or cancel
        # (owner: "add checkboxes to the calendar entry so people can
        # reschedule from the calendar direct"), a box for a day that holds
        # several, Select all, and the bar they open. An entry is drawn in
        # the month grid and in both agendas, so each box is drawn three
        # times; it is named by its label attribute rather than a hidden
        # span to keep that to one element.
        ("/calendar", 290, 2270),
    )

    @classmethod
    def setUpTestData(cls):
        from apps.accounts.models import (
            StaffProfile,
            StaffSchoolAssignment,
            StaffSupervisorAssignment,
            User,
        )
        from apps.activities.models import Activity
        from apps.core.fy import get_operational_fy, get_quarter_for_date
        from apps.geography.models import District, Region
        from apps.notifications.models import Notification
        from apps.schools.models import School

        region = Region.objects.create(name="Budget Region")
        district = District.objects.create(name="Budget District", region=region)
        cls.cceo = User.objects.create(
            email="budget-cceo@edify.org",
            name="Budget Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        officer = StaffProfile.objects.create(
            user=cls.cceo, title="CCEO", country="Uganda"
        )
        lead_user = User.objects.create(
            email="budget-pl@edify.org",
            name="Budget Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
            status="active",
        )
        lead = StaffProfile.objects.create(user=lead_user, title="PL", country="Uganda")
        StaffSupervisorAssignment.objects.create(supervisee=officer, supervisor=lead)
        schools = School.objects.bulk_create(
            School(
                school_id=f"BUD-{n:03d}",
                name=f"Budget Hill Primary {n:03d}",
                region=region,
                district=district,
                account_owner_id=officer.id,
            )
            for n in range(cls.SCHOOLS)
        )
        StaffSchoolAssignment.objects.bulk_create(
            StaffSchoolAssignment(staff=officer, school_id=s.id) for s in schools
        )
        fy = str(get_operational_fy())
        today = date.today()
        statuses = ("scheduled", "planned", "in_progress", "completed")
        for n in range(cls.VISITS):
            planned = today + timedelta(days=(n % 40) - 20)
            Activity.objects.create(
                activity_type="school_visit",
                activity_purpose_text=f"Budget visit {n:03d}",
                school=schools[n % cls.SCHOOLS],
                responsible_staff_id=officer.id,
                delivery_type="staff",
                status=statuses[n % len(statuses)],
                planned_date=planned,
                fy=fy,
                quarter=get_quarter_for_date(planned),
            )
        now = timezone.now()
        Notification.objects.bulk_create(
            Notification(
                recipient_id=cls.cceo.id,
                title=f"Budget notice {n:03d}",
                body="A school visit changed. Open it to see what moved.",
                category="activity",
                priority=("normal", "high", "urgent")[n % 3],
                status="unread" if n % 2 else "read",
                action_required=n % 5 == 0,
                target_route="/my-plan",
                created_at=now - timedelta(hours=n),
            )
            for n in range(cls.NOTIFICATIONS)
        )

    def _measure(self, user, url):
        self.client.force_login(user)
        response = self.client.get(url, HTTP_ACCEPT="text/html")
        self.assertEqual(response.status_code, 200, url)
        html = response.content
        return len(html) / 1024, len(re.findall(rb"<[a-zA-Z][a-zA-Z0-9-]*", html))

    def test_field_officer_pages_stay_inside_their_budgets(self):
        breaches, measured = [], []
        for url, max_kb, max_elements in self.CCEO_PAGES:
            kb, elements = self._measure(self.cceo, url)
            measured.append(f"{url} {kb:.0f} KB {elements} elements")
            if kb > max_kb or elements > max_elements:
                breaches.append(
                    f"{url}: {kb:.0f} KB / {elements} elements "
                    f"(ceilings {max_kb} KB / {max_elements})"
                )
        if PRINT:
            print("\n" + "\n".join(measured))
        self.assertEqual(breaches, [], "\n".join(breaches))
