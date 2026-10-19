"""The Analytics entry is retired; its sections live in profiles and oversight.

Owner, 2026-10-19: "Remove the whole Analytics entry now. Send every
section's old link to the closest profile or oversight page, and give only
Reports, Decision Log and Closure Quality their own sidebar entries."
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import resolve

from apps.accounts.models import StaffProfile, User
from apps.core.navigation import build_sidebar_for_user
from apps.core.rbac import EdifyRole
from apps.frontend.views.analytics_retired import home


def _person(email, role):
    user = User.objects.create(
        email=email,
        name=email.split("@")[0],
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )
    StaffProfile.objects.create(user=user, title=role.value, country="Uganda")
    return user


class RetiredFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd = _person("ret-cd@t.test", EdifyRole.COUNTRY_DIRECTOR)
        cls.pl = _person("ret-pl@t.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        cls.cceo = _person("ret-cceo@t.test", EdifyRole.CCEO)
        cls.ia = _person("ret-ia@t.test", EdifyRole.IMPACT_ASSESSMENT)
        cls.hr = _person("ret-hr@t.test", EdifyRole.HUMAN_RESOURCES)
        cls.accountant = _person("ret-acc@t.test", EdifyRole.PROGRAM_ACCOUNTANT)


class OldLinksTest(RetiredFixture):
    def lands(self, user, url):
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302, url)
        return response["Location"]

    def test_the_overview_opens_the_reader_s_profile(self):
        for url in ("/analytics", "/analytics/country-director"):
            self.assertEqual(self.lands(self.cd, url), "/country-profile")
        self.assertEqual(
            self.lands(self.pl, "/analytics/program-lead"), f"/staff/{self.pl.id}"
        )
        self.assertEqual(self.lands(self.cceo, "/analytics"), "/cluster-oversight/")
        # A reader with no profile and no oversight of their own: HR lands on
        # the Dashboard, the Accountant on the Budget.
        self.assertEqual(self.lands(self.hr, "/analytics"), "/dashboard")
        self.assertEqual(self.lands(self.accountant, "/analytics"), "/budget")

    def test_each_section_opens_its_closest_page(self):
        cases = (
            (self.cd, "/ssa", "/country-profile?tab=ssa"),
            (self.pl, "/ssa", f"/staff/{self.pl.id}?tab=ssa"),
            (self.cceo, "/ssa", "/cluster-oversight/ssa"),
            (self.cd, "/analytics/visit-effectiveness", "/country-profile"),
            (self.ia, "/impact", "/cluster-oversight/impact"),
            (
                self.cd,
                "/declining-schools",
                "/country-profile?tab=schools&show=declined",
            ),
            (self.cd, "/core-school-health", "/core-schools-oversight/"),
            (self.cd, "/decisions", "/country-profile"),
            (self.cd, "/analytics/school-closures", "/schools/closed"),
            # Two tabs showed another module's page; they open that page.
            (self.cd, "/analytics/people", "/hr-analytics"),
            (self.cd, "/analytics/verification-quality", "/ia/dashboard/"),
        )
        for user, url, destination in cases:
            with self.subTest(url=url, role=user.active_role):
                self.assertEqual(self.lands(user, url), destination)

    def test_the_three_tools_stay_where_they_are(self):
        self.client.force_login(self.ia)
        for url in ("/decision-log", "/reports", "/analytics/closure-quality"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class SidebarTest(RetiredFixture):
    def entries(self, user):
        return {
            item["label"]
            for section in build_sidebar_for_user(user, "/dashboard")
            for item in section["items"]
        }

    def test_no_reader_has_an_analytics_entry(self):
        for user in (self.cd, self.pl, self.cceo, self.ia):
            with self.subTest(role=user.active_role):
                self.assertNotIn("Analytics", self.entries(user))

    def test_the_three_tools_have_entries_of_their_own(self):
        entries = self.entries(self.ia)
        for label in ("Reports", "Decision Log", "Closure Quality"):
            self.assertIn(label, entries)
        self.assertIn("Decision Log", self.entries(self.cceo))


class ToolPagesTest(RetiredFixture):
    """The three tools are pages of their own, not tabs of Analytics."""

    PAGES = (
        ("/reports", "Programme Output Reports"),
        ("/decision-log", "Decision Log"),
        ("/analytics/closure-quality", "Closure Quality"),
    )

    def test_each_page_is_headed_by_its_own_name(self):
        self.client.force_login(self.ia)
        for url, title in self.PAGES:
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertIn(f">{title}</h1>", body)
                self.assertNotIn(">Analytics</h1>", body)
                self.assertNotIn('aria-label="Analytics sections"', body)
                # The old Analytics page's tiles and its own actions.
                self.assertNotIn("analytics-executive-pulse", body)
                self.assertNotIn('hx-get="/analytics/customize-dashboard"', body)
                self.assertNotIn('hx-get="/analytics/schedule-report', body)


class OldLinksKeepTheirGuardTest(RetiredFixture):
    """An old address is still a page route: it answers only a reader its page
    admitted, so a redirect never shows anyone where a page they could not
    open went."""

    RETIRED = (
        ("/analytics", "analytics"),
        ("/analytics/program-lead", "pl_analytics"),
        ("/analytics/country-director", "cd_analytics"),
        ("/ssa", "ssa_performance"),
        ("/analytics/visit-effectiveness", "visit_effectiveness"),
        ("/analytics/school-closures", "closure_impact"),
        ("/analytics/people", "hr_analytics"),
        ("/analytics/verification-quality", "ia_dashboard"),
        ("/impact", "impact_analytics"),
        ("/decisions", "decision_intelligence"),
        ("/declining-schools", "declining_schools"),
        ("/core-school-health", "core_school_health"),
    )

    def test_each_old_address_declares_its_page_s_permission(self):
        for url, page_key in self.RETIRED:
            with self.subTest(url=url):
                self.assertEqual(resolve(url).func.page_permission, page_key)

    def test_a_reader_the_page_refused_is_still_refused(self):
        # A CCEO never could open Decision Intelligence: the refusal sends them
        # to the Dashboard with its message, not on to Cluster Oversight.
        self.client.force_login(self.cceo)
        response = self.client.get("/decisions")
        self.assertEqual(response["Location"], "/dashboard")
        self.assertIn(
            "Access Denied",
            " ".join(str(m) for m in response.wsgi_request._messages),
        )


class HomeTest(RetiredFixture):
    """A link that once opened Analytics opens the section's home for its
    reader, and says that page's name."""

    def test_each_reader_s_home_is_named(self):
        cases = (
            (self.cd, "overview", "/country-profile", "Country Profile"),
            (self.pl, "overview", f"/staff/{self.pl.id}", "My Profile"),
            (self.cceo, "overview", "/cluster-oversight/", "Cluster Oversight"),
            (self.hr, "overview", "/dashboard", "Dashboard"),
            (self.accountant, "overview", "/budget", "Budget"),
            (self.cd, "ssa", "/country-profile?tab=ssa", "Country Profile"),
            (self.cceo, "ssa", "/cluster-oversight/ssa", "Cluster Oversight"),
            (self.ia, "impact", "/cluster-oversight/impact", "Cluster Oversight"),
            (
                self.cd,
                "declining",
                "/country-profile?tab=schools&show=declined",
                "Country Profile",
            ),
            (
                self.cd,
                "core_school_health",
                "/core-schools-oversight/",
                "Core School Oversight",
            ),
            (self.cd, "closures", "/schools/closed", "Closed Schools"),
        )
        for user, section, href, label in cases:
            with self.subTest(section=section, role=user.active_role):
                self.assertEqual(home(user, section), {"href": href, "label": label})

    def test_the_country_director_s_dashboard_opens_the_country_profile(self):
        # /dashboard opens Country Oversight; the command dashboard answers
        # when a link names its view.
        self.client.force_login(self.cd)
        body = self.client.get("/dashboard?view=map").content.decode()
        self.assertIn('href="/country-profile"', body)
        self.assertIn("Open Country Profile", body)
        self.assertNotIn("CD Analytics", body)


#: The addresses the redirects answer, and the Analytics page's own actions.
RETIRED_ADDRESS = re.compile(
    r"(?<![\w/.-])/(?:"
    r"analytics(?:/(?:program-lead|country-director|visit-effectiveness"
    r"|school-closures|people|verification-quality|export|schedule-report"
    r"|customize-dashboard))?/?"
    r"|ssa|impact|declining-schools|core-school-health|decisions"
    r")(?=[\"'`?#{])"
)

#: Files that may still name a retired address, and why.
NAMES_A_RETIRED_ADDRESS = {
    # The redirects themselves and the sidebar's record of what retired.
    "apps/frontend/urls.py": "routes the old addresses",
    "apps/frontend/views/analytics_retired.py": "answers the old addresses",
    "apps/core/navigation.py": "keeps each old address's page key",
    # Decision Intelligence stays as it is until the owner decides where the
    # leadership and budget review goes.
    "apps/frontend/views/decision_views.py": "Decision Intelligence's own form",
    # Who's Online names the part of the system a path belongs to; it links
    # nowhere.
    "apps/accounts/presence_labels.py": "labels a path, links nowhere",
}


def _is_test(path: Path) -> bool:
    return (
        path.name.startswith("test_")
        or path.name in {"tests.py", "conftest.py"}
        or "tests" in path.parts
        or "migrations" in path.parts
    )


class NoRetiredLinksTest(SimpleTestCase):
    """No page, partial or service links an address the redirects answer:
    each link names and opens the page its reading lives on now."""

    def test_nothing_links_a_retired_address(self):
        root = Path(settings.BASE_DIR)
        found = []
        for folder, suffixes in (
            ("templates", {".html"}),
            ("apps", {".py", ".html"}),
            ("static/js", {".js"}),
        ):
            for path in sorted((root / folder).rglob("*")):
                relative = path.relative_to(root).as_posix()
                if (
                    path.suffix not in suffixes
                    or _is_test(path)
                    or relative in NAMES_A_RETIRED_ADDRESS
                ):
                    continue
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    if RETIRED_ADDRESS.search(line):
                        found.append(f"{relative}:{number}: {line.strip()[:100]}")
        self.assertEqual(found, [], "\n".join(found))

    def test_the_scan_sees_a_retired_link(self):
        for line in (
            '<a href="/analytics">',
            '"href": "/ssa"',
            'f"/ssa?fy={fy}"',
            "'/analytics/country-director'",
            "/analytics{'?' + query}",
        ):
            with self.subTest(line=line):
                self.assertIsNotNone(RETIRED_ADDRESS.search(line))
        for line in (
            '<a href="/analytics/closure-quality">',
            '"/ssa/export?fy=1"',
            '"/ia/analytics/"',
            '"/api/analytics/map-subcounties"',
            '"/analytics/country-director/drilldown?drill=risk"',
        ):
            with self.subTest(line=line):
                self.assertIsNone(RETIRED_ADDRESS.search(line))
