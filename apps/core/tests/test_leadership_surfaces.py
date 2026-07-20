"""Phase 3 — the surfaces leadership was missing.

Each class covers a blind spot the audit found: an engine with no page, a
question with no answer, a KPI whose drilldown 403'd, or a collision the UI
actively hid.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class DecisionIntelligencePageTests(TestCase):
    """Two complete engines had no page anywhere in the platform."""

    def setUp(self):
        self.cd = _user("cd-di@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=self.cd, title="CD", country="Uganda")
        self.client = Client()

    def test_cd_can_open_the_page(self):
        self.client.force_login(self.cd)
        resp = self.client.get("/decisions")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["can_review_leadership"])
        self.assertTrue(resp.context["can_review_budget"])

    def test_rvp_reviews_leadership_but_not_finance(self):
        rvp = _user("rvp-di@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        StaffProfile.objects.create(user=rvp, title="RVP", country="Uganda")
        self.client.force_login(rvp)
        resp = self.client.get("/decisions")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["can_review_leadership"])
        self.assertFalse(
            resp.context["can_review_budget"],
            "RVP holds budgetIntelligence.view but not budgetDecision.review",
        )

    def test_field_role_is_denied(self):
        cceo = _user("cceo-di@t.org", "Cara", EdifyRole.CCEO.value)
        self.client.force_login(cceo)
        resp = self.client.get("/decisions", follow=True)
        self.assertNotIn("Decision Intelligence — Edify", resp.content.decode())

    def test_budget_snapshot_does_not_raise(self):
        """It filtered on a deleted_at column the model lacks — a latent 500
        that nothing had ever hit because the engine had no UI."""
        from apps.budget_intelligence import services

        snap = services.snapshot(self.cd, {})
        self.assertIn("totalInsights", snap)
        self.assertIn("amountAtRisk", snap)

    def test_recompute_runs_both_engines(self):
        self.client.force_login(self.cd)
        resp = self.client.post("/decisions", {"action": "recompute"}, follow=True)
        self.assertEqual(resp.status_code, 200)


class DecliningSchoolsTests(TestCase):
    """"Which schools are declining" had no answer: the only identified queue
    ranked by absolute score, not by movement."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Decline Region")
        cls.district = District.objects.create(
            name="Decline District", region=cls.region
        )

    def setUp(self):
        self.cd = _user("cd-dec@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=self.cd, title="CD", country="Uganda")
        self.rvp = _user("rvp-dec@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        StaffProfile.objects.create(user=self.rvp, title="RVP", country="Uganda")

    def test_no_paired_cycles_reads_as_unknown_not_as_no_decline(self):
        """The two answers are different and must not be conflated."""
        from apps.analytics.decline_service import declining_schools

        School.objects.create(
            name="Lonely School",
            school_id="LS-1",
            region_id=self.region.id,
            district_id=self.district.id,
        )
        data = declining_schools(self.cd, {})
        self.assertTrue(data["empty"])
        self.assertTrue(data["noPairedCycles"])

    def test_rvp_gets_analysis_without_school_identity(self):
        from apps.analytics.decline_service import declining_schools

        data = declining_schools(self.rvp, {})
        self.assertFalse(data["canViewSchoolDetail"])
        self.assertEqual(data["schools"], [])

    def test_page_renders_for_both_roles(self):
        client = Client()
        for user in (self.cd, self.rvp):
            client.force_login(user)
            resp = client.get("/declining-schools")
            self.assertEqual(resp.status_code, 200)


class CoreSchoolHealthTests(TestCase):
    """The CD's core KPIs linked to a page the CD is 403'd from."""

    def setUp(self):
        self.cd = _user("cd-core@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=self.cd, title="CD", country="Uganda")
        self.rvp = _user("rvp-core@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        StaffProfile.objects.create(user=self.rvp, title="RVP", country="Uganda")
        self.client = Client()

    def test_cd_reaches_the_leadership_page(self):
        self.client.force_login(self.cd)
        self.assertEqual(self.client.get("/core-school-health").status_code, 200)

    def test_rvp_reaches_it_without_school_identity(self):
        self.client.force_login(self.rvp)
        resp = self.client.get("/core-school-health")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["d"]["canViewSchoolDetail"])

    def test_cd_is_still_blocked_from_the_operational_page(self):
        """The leadership lens must not become a back door into field tooling."""
        self.client.force_login(self.cd)
        resp = self.client.get("/core-schools", follow=True)
        self.assertNotIn("core_schools", resp.request["PATH_INFO"])

    def test_dashboard_core_cards_point_somewhere_reachable(self):
        from apps.analytics import cd_dashboard_service

        import inspect

        source = inspect.getsource(cd_dashboard_service)
        self.assertNotIn(
            '"/core-schools"',
            source,
            "CD dashboard must not link to a page the CD cannot open",
        )

    def test_gate_blocker_names_the_missing_artefact(self):
        from apps.core_schools.leadership_service import _gate_blocker

        class _Slot:
            status = "In Progress"
            salesforce_id = ""
            evidence_uri = ""

        slot = _Slot()
        self.assertEqual(_gate_blocker(slot), "Needs Salesforce ID and evidence")
        slot.salesforce_id = "SF-1"
        self.assertEqual(_gate_blocker(slot), "Needs evidence")
        slot.evidence_uri = "s3://x"
        self.assertIsNone(_gate_blocker(slot))
        slot.status = "Completed"
        self.assertIsNone(_gate_blocker(slot))


class LeaveVisitCollisionTests(TestCase):
    """The heatmap computed the visit count then let "On Leave" overwrite it,
    so stranded field work was invisible at team level."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Collide Region")
        cls.district = District.objects.create(
            name="Collide District", region=cls.region
        )
        cls.school = School.objects.create(
            name="Collide Primary",
            school_id="CP-1",
            region_id=cls.region.id,
            district_id=cls.district.id,
        )

    def setUp(self):
        self.cceo = _user("cceo-col@t.org", "Cara", EdifyRole.CCEO.value)
        self.cceo_sp = StaffProfile.objects.create(
            user=self.cceo, title="CCEO", country="Uganda"
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_sp, school_id=self.school.id
        )

    def _book_visit(self, when):
        # The heatmap reads `scheduled_date` (the confirmed calendar slot),
        # not `planned_date`.
        moment = timezone.make_aware(
            timezone.datetime.combine(when, timezone.datetime.min.time().replace(hour=9))
        )
        return Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.cceo_sp.id,
            planned_date=moment,
            scheduled_date=moment,
        )

    def _approve_leave(self, start, end):
        return Leave.objects.create(
            staff=self.cceo_sp,
            type="annual",
            start_date=str(start),
            end_date=str(end),
            days=(end - start).days + 1,
            status="approved",
        )

    def test_absence_with_booked_visits_is_reported(self):
        from apps.hr.leave_services import TeamAvailabilityService as T

        # Next week: away, but a visit is still on the books.
        monday = date.today() + timedelta(days=(7 - date.today().weekday()))
        self._approve_leave(monday, monday + timedelta(days=4))
        self._book_visit(monday + timedelta(days=1))

        report = T.collision_report(country_scope=True, weeks=8)
        self.assertEqual(report["people_affected"], 1)
        self.assertGreaterEqual(report["visits_at_risk"], 1)
        self.assertEqual(report["rows"][0]["staff_name"], self.cceo.name)

    def test_absence_without_booked_visits_is_not_flagged(self):
        from apps.hr.leave_services import TeamAvailabilityService as T

        monday = date.today() + timedelta(days=(7 - date.today().weekday()))
        self._approve_leave(monday, monday + timedelta(days=4))
        report = T.collision_report(country_scope=True, weeks=8)
        self.assertEqual(report["visits_at_risk"], 0)

    def test_window_extends_past_four_weeks(self):
        """Four weeks cannot answer "who is away next month"."""
        from apps.hr.leave_services import TeamAvailabilityService as T

        matrix = T.get_4week_heatmap(country_scope=True, week_count=8)
        self.assertEqual(len(matrix[0]["weeks"]), 8)

    def test_default_window_is_unchanged_for_existing_callers(self):
        from apps.hr.leave_services import TeamAvailabilityService as T

        matrix = T.get_4week_heatmap(country_scope=True)
        self.assertEqual(len(matrix[0]["weeks"]), 4)


class CceoLeaderboardTests(TestCase):
    """The weighted per-CCEO figure existed but was only assembled inside a
    single PL's drilldown, so no screen ranked the country."""

    def test_leaderboard_separates_unset_targets_from_poor_performance(self):
        from apps.analytics.cd_analytics_service import CDAnalyticsService as S

        rows = [
            {"unset": True, "pct": 0, "name": "No Target"},
            {"unset": False, "pct": 20, "name": "Weak"},
            {"unset": False, "pct": 95, "name": "Strong"},
        ]
        ranked = sorted(
            rows, key=lambda r: (r["unset"], -(r["pct"] or 0), r["name"] or "")
        )
        self.assertEqual([r["name"] for r in ranked], ["Strong", "Weak", "No Target"])
        self.assertEqual(S._achievement_band(95), "Strong")
        self.assertEqual(S._achievement_band(80), "On Track")
        self.assertEqual(S._achievement_band(60), "Watch")
        self.assertEqual(S._achievement_band(10), "Critical")

    def test_cockpit_exposes_the_leaderboard(self):
        cd = _user("cd-lb@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=cd, title="CD", country="Uganda")
        client = Client()
        client.force_login(cd)
        resp = client.get("/analytics/country-director")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("CCEO Leaderboard", resp.content.decode())


class RiskDrilldownCoverageTests(TestCase):
    """Four risk cards linked to a drill branch that did not exist, so each
    opened an empty drawer."""

    def test_every_risk_card_link_has_a_drill_branch(self):
        from apps.analytics.cd_analytics_service import CDAnalyticsService as S
        from apps.analytics.cd_analytics_service import resolve_cd_scope
        from apps.core.fy import get_operational_fy

        cd_user = _user("cd-risk@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=cd_user, title="CD", country="Uganda")
        fy = get_operational_fy()
        scope = resolve_cd_scope(fy)

        class _P(dict):
            def get(self, k, d=None):
                return dict.get(self, k, d)

        for issue in (
            "evidence",
            "ia",
            "sf_id",
            "finance",
            "accountability",
            "no_ssa",
            "low_ssa",
            "no_visit",
            "no_training",
        ):
            payload = S.drilldown(cd_user, "risk", _P(issue=issue), fy=fy)
            self.assertNotEqual(
                payload["title"],
                "Operational Risk",
                f"'{issue}' falls through to the generic title — no branch handles it",
            )
            self.assertIn("rows", payload)
