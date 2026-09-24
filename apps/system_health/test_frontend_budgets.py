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
    RENDER_BLOCKING_STYLESHEETS = 17
    CSS_GZIP_KB = 200
    PARSER_BLOCKING_HEAD_SCRIPTS = 3
    JS_GZIP_KB = 115
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
    CCEO_PAGES = (
        ("/dashboard", 310, 1250),
        ("/my-plan", 265, 1760),
        ("/schools", 265, 2270),
        ("/planning", 175, 950),
        ("/notifications", 265, 1390),
        ("/todos", 230, 1380),
        ("/today/panel", 35, 320),
        ("/my-targets", 170, 940),
        ("/calendar", 285, 2210),
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
