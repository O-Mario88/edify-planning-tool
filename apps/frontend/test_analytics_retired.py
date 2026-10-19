"""The Analytics entry is retired; its sections live in profiles and oversight.

Owner, 2026-10-19: "Remove the whole Analytics entry now. Send every
section's old link to the closest profile or oversight page, and give only
Reports, Decision Log and Closure Quality their own sidebar entries."
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.navigation import build_sidebar_for_user
from apps.core.rbac import EdifyRole


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
        from django.urls import resolve

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
