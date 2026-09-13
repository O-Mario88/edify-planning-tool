"""The CCE Regional Lead's records (owner, 2026-09-13).

The full role description gave the Regional Programme Lead work of their own
that is not planned work: coaching conversations, meetings with Country
Directors, the RVP and the VP of CCE, training observations with feedback a
Programme Lead acknowledges, and a monthly report the RVP reviews. These tests
hold the rules for each, who can read what, the handoffs between the three
roles, and the rhythm the dashboard checks.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffGeographyAssignment,
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden
from apps.geography.models import District, Region
from apps.schools.models import School

from . import services
from .cadence import CADENCE_RULES, Held, evaluate
from .models import EngagementKind, RegionalCceReport, RegionalEngagement, ReportStatus

TODAY = timezone.localdate()


def _person(uid, name, role, country="Uganda"):
    user = User.objects.create(
        id=uid,
        email=f"{uid}@edify.org",
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country=country, title=role
    )
    return user, profile


def _ratings(value=3):
    return {
        "rating_biblical_integration": value,
        "rating_need_alignment": value,
        "rating_facilitation": value,
        "rating_participation": value,
        "rating_application": value,
    }


class CceFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="CCE Region", country="Uganda")
        cls.other_region = Region.objects.create(name="CCE Other", country="Kenya")
        cls.district = District.objects.create(
            name="CCE District", region=cls.region, district_type="primary"
        )
        cls.other_district = District.objects.create(
            name="CCE Other District", region=cls.other_region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="CCE-SCH",
            name="Grace Primary",
            region=cls.region,
            district=cls.district,
        )
        cls.other_school = School.objects.create(
            school_id="CCE-OTHER",
            name="Faith Primary",
            region=cls.other_region,
            district=cls.other_district,
        )

        cls.lead, cls.lead_sp = _person(
            "cce-rpl", "Regional Lead", "RegionalProgramLead"
        )
        StaffGeographyAssignment.objects.create(
            staff=cls.lead_sp, region_id=cls.region.id
        )
        cls.pl, cls.pl_sp = _person("cce-pl", "Uganda Lead", "Program Lead")
        cls.cceo, cls.cceo_sp = _person("cce-cceo", "Uganda Officer", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        cls.kenya_pl, cls.kenya_pl_sp = _person(
            "cce-kenya-pl", "Kenya Lead", "Program Lead", country="Kenya"
        )
        cls.cd, cls.cd_sp = _person("cce-cd", "Uganda Director", "CountryDirector")
        cls.rvp, cls.rvp_sp = _person("cce-rvp", "Uganda RVP", "RegionalVicePresident")
        StaffGeographyAssignment.objects.create(
            staff=cls.rvp_sp, region_id=cls.region.id
        )
        cls.kenya_rvp, cls.kenya_rvp_sp = _person(
            "cce-kenya-rvp", "Kenya RVP", "RegionalVicePresident", country="Kenya"
        )
        StaffGeographyAssignment.objects.create(
            staff=cls.kenya_rvp_sp, region_id=cls.other_region.id
        )

        # In this month, so the monthly report's figures include it on any day.
        day = TODAY.replace(day=1) if TODAY.day <= 3 else TODAY - timedelta(days=3)
        cls.training = Activity.objects.create(
            activity_type="training",
            school=cls.school,
            fy="2026",
            quarter="Q4",
            delivery_type="staff",
            responsible_staff_id=cls.cceo_sp.id,
            status="completed",
            planned_date=day,
            scheduled_date=timezone.now() - timedelta(days=(TODAY - day).days),
            focus_intervention="leadership",
        )
        cls.kenya_training = Activity.objects.create(
            activity_type="training",
            school=cls.other_school,
            fy="2026",
            quarter="Q4",
            delivery_type="staff",
            status="completed",
            planned_date=day,
            scheduled_date=timezone.now() - timedelta(days=(TODAY - day).days),
        )

    def _observe(self, **extra):
        return services.record_engagement(
            self.lead,
            {
                "kind": EngagementKind.TRAINING_OBSERVATION,
                "held_on": TODAY.isoformat(),
                "activity_id": self.training.id,
                "recommendation": "strengthen",
                "feedback": "Model the lesson before asking teachers to practise it.",
                **_ratings(),
                **extra,
            },
        )


class EngagementRulesTest(CceFixture):
    def test_the_lead_records_a_coaching_conversation_with_a_lead_in_reach(self):
        engagement = services.record_engagement(
            self.lead,
            {
                "kind": EngagementKind.PL_COACHING,
                "held_on": TODAY.isoformat(),
                "program_lead_ids": [self.pl_sp.id],
                "notes": "Reviewed the CCE KPI report.",
            },
        )
        self.assertEqual(engagement.country, "Uganda", "taken from the Programme Lead")
        self.assertIn("Uganda Lead", engagement.subject)
        self.assertEqual(engagement.author_id, self.lead.id)

    def test_it_refuses_a_lead_outside_the_region_a_future_date_and_a_countryless_review(
        self,
    ):
        with self.assertRaisesMessage(BadRequest, "in your region"):
            services.record_engagement(
                self.lead,
                {
                    "kind": EngagementKind.PL_COACHING,
                    "held_on": TODAY.isoformat(),
                    "program_lead_ids": [self.kenya_pl_sp.id],
                },
            )
        with self.assertRaisesMessage(BadRequest, "once it has happened"):
            services.record_engagement(
                self.lead,
                {
                    "kind": EngagementKind.RVP_MEETING,
                    "held_on": (TODAY + timedelta(days=1)).isoformat(),
                },
            )
        with self.assertRaisesMessage(BadRequest, "Country Director"):
            services.record_engagement(
                self.lead,
                {
                    "kind": EngagementKind.CD_QUARTERLY_REVIEW,
                    "held_on": TODAY.isoformat(),
                },
            )

    def test_only_the_regional_lead_records_engagements(self):
        with self.assertRaises(Forbidden):
            services.record_engagement(
                self.pl,
                {"kind": EngagementKind.RVP_MEETING, "held_on": TODAY.isoformat()},
            )

    def test_an_observation_goes_to_the_lead_of_the_team_that_ran_the_training(self):
        observation = self._observe()
        self.assertEqual(observation.program_lead_ids, [self.pl_sp.id])
        self.assertEqual(observation.country, "Uganda")
        self.assertEqual(observation.average_rating, 3.0)

    def test_an_observation_needs_ratings_feedback_and_a_training_in_reach(self):
        with self.assertRaisesMessage(BadRequest, "from 1 to 4"):
            self._observe(rating_facilitation=5)
        with self.assertRaisesMessage(BadRequest, "Write the feedback"):
            self._observe(feedback="")
        with self.assertRaisesMessage(BadRequest, "in your region"):
            self._observe(activity_id=self.kenya_training.id)


class FeedbackHandoffTest(CceFixture):
    def test_shared_feedback_reaches_the_programme_lead_and_their_director_only(self):
        from apps.notifications.models import Notification

        observation = self._observe()
        self.assertFalse(
            services.feedback_visible_to(self.pl).exists(), "drafts stay private"
        )

        services.share_feedback(self.lead, observation.id)
        self.assertTrue(
            services.feedback_visible_to(self.pl).filter(id=observation.id).exists()
        )
        self.assertTrue(
            services.feedback_visible_to(self.cd).filter(id=observation.id).exists()
        )
        self.assertFalse(services.feedback_visible_to(self.kenya_pl).exists())
        notice = Notification.objects.get(recipient_id=self.pl.id)
        self.assertEqual(notice.target_route, "/cce-leadership/feedback")

        with self.assertRaisesMessage(Forbidden, "can no longer be changed"):
            services.update_engagement(
                self.lead, observation.id, {"feedback": "Changed"}
            )

    def test_the_programme_lead_acknowledges_with_a_response_once(self):
        from apps.notifications.models import Notification

        observation = self._observe()
        services.share_feedback(self.lead, observation.id)
        with self.assertRaisesMessage(BadRequest, "what you will change"):
            services.acknowledge_feedback(self.pl, observation.id, "")
        with self.assertRaises(Forbidden):
            services.acknowledge_feedback(self.cd, observation.id, "Noted")

        services.acknowledge_feedback(
            self.pl, observation.id, "Trainers will model first."
        )
        observation.refresh_from_db()
        self.assertEqual(observation.lead_response, "Trainers will model first.")
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.lead.id,
                source_event_type="cce_training_feedback_acknowledged",
            ).exists()
        )
        with self.assertRaisesMessage(BadRequest, "already acknowledged"):
            services.acknowledge_feedback(self.pl, observation.id, "Again")


class MonthlyReportTest(CceFixture):
    def test_one_report_a_month_and_never_a_future_month(self):
        first = services.start_report(self.lead, TODAY.isoformat()[:7])
        again = services.start_report(self.lead, TODAY.isoformat()[:7])
        self.assertEqual(first.id, again.id)
        self.assertEqual(first.countries, ["Uganda"])
        with self.assertRaisesMessage(BadRequest, "current month or an earlier one"):
            services.start_report(
                self.lead, (TODAY + timedelta(days=40)).isoformat()[:7]
            )

    def test_submit_freezes_the_figures_and_goes_to_the_rvp_of_its_countries(self):
        from apps.notifications.models import Notification

        report = services.start_report(self.lead, TODAY.isoformat()[:7])
        self.assertFalse(
            services.reports_visible_to(self.rvp).exists(), "drafts are the lead's"
        )
        with self.assertRaisesMessage(BadRequest, "executive summary"):
            services.update_report(self.lead, report.id, {}, submit=True)

        report = services.update_report(
            self.lead, report.id, {"executive_summary": "A strong month."}, submit=True
        )
        self.assertEqual(report.status, ReportStatus.SUBMITTED)
        self.assertEqual(report.metrics["trainings_delivered"], 1)
        self.assertTrue(
            services.reports_visible_to(self.rvp).filter(id=report.id).exists()
        )
        self.assertFalse(services.reports_visible_to(self.kenya_rvp).exists())
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.rvp.id, source_event_type="cce_report_submitted"
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(recipient_id=self.kenya_rvp.id).exists()
        )
        with self.assertRaisesMessage(Forbidden, "with the RVP"):
            services.update_report(self.lead, report.id, {"executive_summary": "Edit"})

    def test_the_rvp_returns_with_a_note_and_the_lead_resubmits(self):
        report = services.start_report(self.lead, TODAY.isoformat()[:7])
        services.update_report(
            self.lead, report.id, {"executive_summary": "Draft"}, submit=True
        )
        with self.assertRaisesMessage(BadRequest, "what the report needs"):
            services.review_report(self.rvp, report.id, "return")
        with self.assertRaises(Forbidden):
            services.review_report(self.pl, report.id, "acknowledge")

        report = services.review_report(
            self.rvp, report.id, "return", "Add the SSA results."
        )
        self.assertEqual(report.status, ReportStatus.RETURNED)
        report = services.update_report(
            self.lead, report.id, {"cce_impact": "SSA up in leadership."}, submit=True
        )
        report = services.review_report(self.rvp, report.id, "acknowledge")
        self.assertEqual(report.status, ReportStatus.ACKNOWLEDGED)

    def test_a_report_is_overdue_after_the_tenth_only_from_when_reporting_began(self):
        before = services.report_state(self.lead, today=date(2026, 9, 20))
        self.assertFalse(before["previous_overdue"], "August 2026 was never owed")
        after = services.report_state(self.lead, today=date(2026, 10, 11))
        self.assertTrue(after["previous_overdue"])
        RegionalCceReport.objects.create(
            author_id=self.lead.id,
            period=date(2026, 9, 1),
            fy="2026",
            status=ReportStatus.SUBMITTED,
        )
        self.assertFalse(
            services.report_state(self.lead, today=date(2026, 10, 11))[
                "previous_overdue"
            ]
        )


class CadenceTest(SimpleTestCase):
    leads = [{"staff_id": "pl-1", "name": "Lead One", "country": "Uganda"}]

    def _state(self, rows, label, subject=None):
        return next(
            r["state"]
            for r in rows
            if r["label"] == label and (subject is None or r["subject"] == subject)
        )

    def test_every_rule_names_a_real_engagement_kind(self):
        self.assertTrue(
            all(rule.kind in EngagementKind.values for rule in CADENCE_RULES)
        )

    def test_rolling_rules_are_done_due_soon_or_overdue(self):
        today = date(2026, 9, 13)
        held = [
            Held(
                EngagementKind.PL_COACHING,
                today - timedelta(days=40),
                "Uganda",
                ("pl-1",),
            ),
            Held(EngagementKind.VP_CCE_CHECKIN, today - timedelta(days=3), "", ()),
            Held(EngagementKind.RVP_MEETING, today - timedelta(days=27), "", ()),
        ]
        rows = evaluate(held, today=today, leads=self.leads, countries=["Uganda"])[
            "rows"
        ]
        self.assertEqual(
            self._state(rows, "Coaching conversation", "Lead One"), "overdue"
        )
        self.assertEqual(self._state(rows, "VP of CCE check-in"), "done")
        self.assertEqual(self._state(rows, "Meeting with the RVP"), "due_soon")
        self.assertEqual(
            self._state(rows, "Regional Leads and VP of CCE meeting"), "due_soon"
        )

    def test_quarterly_reviews_and_the_annual_budget_input(self):
        today = date(2026, 9, 13)
        held = [
            Held(EngagementKind.CD_QUARTERLY_REVIEW, date(2026, 7, 20), "Uganda", ())
        ]
        rows = evaluate(
            held,
            today=today,
            leads=[],
            countries=["Uganda", "Kenya"],
            budgets_submitted={"Kenya"},
        )["rows"]
        self.assertEqual(
            self._state(rows, "Country Director quarterly review", "Uganda"), "done"
        )
        self.assertEqual(
            self._state(rows, "Country Director quarterly review", "Kenya"), "due_soon"
        )
        self.assertEqual(
            self._state(rows, "Annual programming and budget input", "Kenya"), "missed"
        )
        self.assertEqual(
            self._state(rows, "Annual programming and budget input", "Uganda"),
            "due_soon",
        )
        early = evaluate([], today=date(2026, 1, 10), leads=[], countries=["Uganda"])[
            "rows"
        ]
        self.assertEqual(
            self._state(early, "Annual programming and budget input", "Uganda"), "open"
        )


class PagesTest(CceFixture):
    def test_the_lead_opens_the_log_the_drawers_and_records_from_them(self):
        self.client.force_login(self.lead)
        page = self.client.get("/cce-leadership/engagements")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "CCE Engagement Log")
        self.assertContains(page, "data-rpl-rhythm")
        self.assertContains(page, "Observe a training")
        for url in (
            "/cce-leadership/engagements/new",
            "/cce-leadership/engagements/new?kind=training_observation",
            "/cce-leadership/reports/new",
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url, HTTP_HX_REQUEST="true").status_code, 200
                )

        response = self.client.post(
            "/cce-leadership/engagements/record",
            {
                "kind": EngagementKind.PL_COACHING,
                "held_on": TODAY.isoformat(),
                "program_lead_ids": [self.pl_sp.id],
            },
        )
        self.assertEqual(response.status_code, 302)
        engagement = RegionalEngagement.objects.get(author_id=self.lead.id)
        self.assertEqual(
            self.client.get(f"/cce-leadership/engagements/{engagement.id}").status_code,
            200,
        )

    def test_who_opens_which_page(self):
        allowed = {
            "/cce-leadership/engagements": (self.lead,),
            "/cce-leadership/feedback": (self.pl, self.cd, self.lead),
            "/cce-leadership/reports": (self.lead, self.rvp),
        }
        refused = {
            "/cce-leadership/engagements": (self.pl, self.rvp, self.cceo),
            "/cce-leadership/feedback": (self.cceo, self.rvp),
            "/cce-leadership/reports": (self.pl, self.cceo, self.cd),
        }
        for url, users in allowed.items():
            for user in users:
                with self.subTest(url=url, role=user.active_role):
                    self.client.force_login(user)
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, "Access Denied")
        for url, users in refused.items():
            for user in users:
                with self.subTest(url=url, role=user.active_role, refused=True):
                    self.client.force_login(user)
                    response = self.client.get(url)
                    self.assertTrue(
                        response.status_code in (302, 403)
                        or b"Access Denied" in response.content
                    )

    def test_the_programme_lead_acknowledges_from_the_drawer(self):
        observation = self._observe()
        services.share_feedback(self.lead, observation.id)
        self.client.force_login(self.pl)
        drawer = self.client.get(f"/cce-leadership/feedback/{observation.id}")
        self.assertContains(drawer, "Acknowledge feedback")
        self.client.post(
            f"/cce-leadership/feedback/{observation.id}/acknowledge",
            {"response": "We will model first."},
        )
        observation.refresh_from_db()
        self.assertIsNotNone(observation.acknowledged_at)

    def test_the_rvp_reviews_from_the_report_drawer(self):
        report = services.start_report(self.lead, TODAY.isoformat()[:7])
        services.update_report(
            self.lead, report.id, {"executive_summary": "Good"}, submit=True
        )
        self.client.force_login(self.rvp)
        self.assertContains(
            self.client.get(f"/cce-leadership/reports/{report.id}"), "Record review"
        )
        self.client.post(
            f"/cce-leadership/reports/{report.id}/review", {"decision": "acknowledge"}
        )
        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.ACKNOWLEDGED)

    def test_the_dashboard_shows_the_new_sections(self):
        services.record_engagement(
            self.lead,
            {
                "kind": EngagementKind.PL_COACHING,
                "held_on": TODAY.isoformat(),
                "program_lead_ids": [self.pl_sp.id],
            },
        )
        self.client.force_login(self.lead)
        with patch(
            "apps.core.cache_utils.cached_role_dashboard",
            side_effect=lambda k, u, p, build: build(),
        ):
            page = self.client.get("/dashboard")
        self.assertEqual(page.status_code, 200)
        for marker in (
            "data-rpl-ssa-needs",
            "data-rpl-training-quality",
            "data-rpl-rhythm",
            "data-rpl-report",
            "data-rpl-networks",
            "Last coaching",
        ):
            with self.subTest(marker=marker):
                self.assertContains(page, marker)


class TodoHandoffTest(CceFixture):
    def test_each_role_is_asked_for_its_part(self):
        from apps.command_center.todo_service import _cce_leadership_todos

        observation = self._observe()
        services.share_feedback(self.lead, observation.id)
        report = services.start_report(self.lead, TODAY.isoformat()[:7])
        services.update_report(
            self.lead, report.id, {"executive_summary": "Good"}, submit=True
        )

        pl_titles = [
            t["title"] for t in _cce_leadership_todos(self.pl, "Program Lead", TODAY)
        ]
        self.assertIn("Acknowledge training feedback", pl_titles)
        rvp_titles = [
            t["title"]
            for t in _cce_leadership_todos(self.rvp, "RegionalVicePresident", TODAY)
        ]
        self.assertTrue(any(t.startswith("Review the ") for t in rvp_titles))
        kenya = _cce_leadership_todos(self.kenya_rvp, "RegionalVicePresident", TODAY)
        self.assertEqual(kenya, [])
        lead_titles = [
            t["title"]
            for t in _cce_leadership_todos(
                self.lead, "RegionalProgramLead", date(2026, 11, 20)
            )
        ]
        self.assertTrue(any("CCE report" in t for t in lead_titles), lead_titles)
