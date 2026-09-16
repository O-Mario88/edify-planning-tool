"""The fiscal year boundary: what it still governs, and what it no longer does.

FY2027 runs 1 October 2026 – 30 September 2027. Nothing in it is delivered
before 1 October, and no FY2026 activity is carried into it by a reschedule —
its budget line, fund request and target credit belong to the year it was
planned in.

Two rules from the 2026-09-15 brief were lifted on 2026-09-16 at the owner's
request, because together they made every 1 October a wall:

- A date is plannable whenever it is not in the past. The year it falls in no
  longer has to be "opened" first, so a team can plan the term ahead.
- The cost catalogue is universal, not a fiscal year's. A year with no card of
  its own is priced by the Country Director's live one instead of showing
  "Ver: None active" and refusing every date in it.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.audit.models import AuditLog
from apps.budget.costing_service import active_catalogue
from apps.budget.governance_service import carry_forward_rate_card
from apps.budget.models import CostSetting
from apps.budget.reference import ensure_active_catalogue, ensure_cost_reference
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.planning import fy_policy
from apps.planning.test_standard_support_scheduling import StandardSupportBase

OCT_6_2026 = datetime.date(2026, 10, 6)  # a Tuesday in FY2027 Q1
SEP_29_2026 = datetime.date(2026, 9, 29)  # a Tuesday in FY2026 Q4


def _at(day):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(9)),
        timezone.get_current_timezone(),
    )


class FiscalYearBoundaryTest(TestCase):
    def test_fy2027_runs_october_to_september_with_q1_october_to_december(self):
        self.assertEqual(get_operational_fy(datetime.date(2026, 9, 30)), "2026")
        self.assertEqual(get_operational_fy(datetime.date(2026, 10, 1)), "2027")
        self.assertEqual(get_quarter_for_date(datetime.date(2026, 10, 1)), "Q1")
        self.assertEqual(get_quarter_for_date(datetime.date(2026, 12, 31)), "Q1")
        self.assertEqual(get_operational_fy(datetime.date(2027, 9, 30)), "2027")

    def test_fy2027_is_open_and_fy2026_still_available(self):
        at = timezone.make_aware(datetime.datetime(2026, 9, 20, 10))
        self.assertTrue(fy_policy.is_planning_open("2026", at=at))
        self.assertTrue(fy_policy.is_planning_open("2027", at=at))
        self.assertFalse(fy_policy.is_planning_open("2028", at=at))
        self.assertEqual(fy_policy.plannable_fys(at=at)[-2:], ["2026", "2027"])
        before = timezone.make_aware(datetime.datetime(2026, 9, 1, 10))
        self.assertFalse(fy_policy.is_planning_open("2027", at=before))

    def test_any_future_date_is_plannable_whatever_its_fiscal_year(self):
        """Scheduling is no longer gated on the year being opened.

        Owner, 2026-09-16: "people can schedule any date ahead ... irrespective
        of which FY". A team planning the term ahead was being told to ask the
        Country Director for a date four weeks away, because the year it fell
        in had not been opened. The year still governs delivery and pricing —
        those are asked elsewhere — but not whether a date may be chosen.
        """
        at = timezone.make_aware(datetime.datetime(2026, 9, 20, 10))
        fy_policy.assert_date_plannable(datetime.date(2026, 10, 1), at=at)
        fy_policy.assert_date_plannable(datetime.date(2026, 9, 20), at=at)
        # FY2028, which nobody has opened, and a year beyond that.
        fy_policy.assert_date_plannable(datetime.date(2027, 10, 4), at=at)
        fy_policy.assert_date_plannable(datetime.date(2031, 2, 3), at=at)

    def test_a_date_that_has_passed_is_refused(self):
        at = timezone.make_aware(datetime.datetime(2026, 9, 20, 10))
        with self.assertRaisesMessage(BadRequest, "has passed"):
            fy_policy.assert_date_plannable(SEP_29_2026.replace(day=19), at=at)
        # Today itself is not "past".
        fy_policy.assert_date_plannable(datetime.date(2026, 9, 20), at=at)

    def test_fy2027_work_cannot_start_before_1_october(self):
        activity = Activity(fy="2027", planned_date=OCT_6_2026)
        with self.assertRaisesMessage(BadRequest, "started from 1 October 2026"):
            fy_policy.assert_may_execute(activity, today=datetime.date(2026, 9, 25))
        fy_policy.assert_may_execute(activity, today=datetime.date(2026, 10, 6))

    def test_a_reschedule_never_crosses_the_fiscal_year(self):
        with self.assertRaisesMessage(BadRequest, "FY2026 work"):
            fy_policy.assert_same_fiscal_year(SEP_29_2026, OCT_6_2026)
        fy_policy.assert_same_fiscal_year(OCT_6_2026, datetime.date(2027, 3, 2))


class Fy2027CostingTest(StandardSupportBase):
    """Real pricing: no patched cost snapshot here."""

    def setUp(self):
        # Deliberately not calling StandardSupportBase.setUp (it patches the
        # cost snapshot away).
        ensure_cost_reference(ensure_active_catalogue())
        self.cd = User.objects.create_user(
            email="fy27-cd@edify.org",
            name="FY27 CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
        )
        self.fy26_card = active_catalogue("2026")

    def _visit_on(self, day):
        from apps.activities.services import create

        return create(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": self.item("STANDARD_SCHOOL_VISIT").id,
                "focusIntervention": "leadership",
                "scheduledDate": _at(day).isoformat(),
                "requireCatalogue": True,
                "activityPurposeText": "FY2027 planning",
                "ssaDeviationReason": "Planned for the new year.",
            },
            self.user,
        )

    def test_fy2027_is_costed_on_the_universal_catalogue(self):
        """A year with no card of its own still prices (owner, 2026-09-16).

        The catalogue is the Country Director's, not a fiscal year's, so
        October work is priced by the live card rather than refused with
        "Ver: None active" until someone publishes a year-stamped copy.
        """
        live = active_catalogue("2027")
        self.assertIsNotNone(live)
        self.assertEqual(live.id, self.fy26_card.id)
        activity = Activity.objects.get(id=self._visit_on(OCT_6_2026)["id"])
        self.assertEqual(activity.fy, "2027")
        self.assertFalse(activity.cost_missing)
        self.assertEqual(
            set(
                ActivityScheduleCostLine.objects.filter(activity=activity).values_list(
                    "catalogue_id", flat=True
                )
            ),
            {live.id},
        )

    def test_a_future_year_prices_every_kind_of_scheduling(self):
        """The surface the owner reported: "Cost Preview (Cluster Meeting)
        Ver: None active — that is why next FY or future months are not
        accepting to schedule activities". No card meant no version, which
        meant a blocker, which meant the date was refused. One universal
        catalogue answers for every year and every kind of work.
        """
        from apps.budget.costing_service import preview

        for activity_type in ("cluster_meeting", "cluster_training", "school_visit"):
            for fy in ("2027", "2031"):
                with self.subTest(activity_type=activity_type, fy=fy):
                    result = preview(
                        {
                            "activityType": activity_type,
                            "deliveryType": "staff",
                            "districtType": "primary",
                            "expectedParticipants": 20,
                            "fy": fy,
                        }
                    )
                    self.assertEqual(result["blockers"], [])
                    self.assertTrue(result["canSchedule"])
                    self.assertIsNotNone(result["catalogueVersion"])

    def test_only_the_cd_carries_forward_and_only_once(self):
        with self.assertRaises(Forbidden):
            carry_forward_rate_card(self.user, "2027")
        card = carry_forward_rate_card(self.cd, "2027", note="Opening FY2027.")
        self.assertEqual(card.fy, "2027")
        self.assertTrue(card.is_provisional)
        self.assertEqual(card.effective_from, datetime.date(2026, 10, 1))
        self.assertEqual(card.effective_to, datetime.date(2027, 9, 30))
        self.assertEqual(
            set(card.rates.values_list("key", flat=True)),
            set(self.fy26_card.rates.values_list("key", flat=True)),
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="rate_card.carried_forward", subject_id=card.id
            ).exists()
        )
        # FY2026's card is untouched.
        self.fy26_card.refresh_from_db()
        self.assertTrue(self.fy26_card.is_active)
        with self.assertRaisesMessage(BadRequest, "already has a published"):
            carry_forward_rate_card(self.cd, "2027")

    def test_october_2026_work_is_fy2027_and_priced_on_the_fy2027_card(self):
        card = carry_forward_rate_card(self.cd, "2027")
        # A higher FY2027 rate proves which card priced the work.
        CostSetting.objects.filter(catalogue=card).update(unit_cost=99_000)
        result = self._visit_on(OCT_6_2026)
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.fy, "2027")
        self.assertEqual(activity.quarter, "Q1")
        lines = ActivityScheduleCostLine.objects.filter(activity=activity)
        self.assertTrue(lines.exists())
        self.assertEqual(set(lines.values_list("catalogue_id", flat=True)), {card.id})

        # FY2026 still costs on its own card in the same session.
        fy26 = Activity.objects.get(id=self._visit_on(SEP_29_2026)["id"])
        self.assertEqual(fy26.fy, "2026")
        self.assertEqual(
            set(
                ActivityScheduleCostLine.objects.filter(activity=fy26).values_list(
                    "catalogue_id", flat=True
                )
            ),
            {self.fy26_card.id},
        )

    def test_a_fy2026_visit_cannot_be_rescheduled_into_fy2027(self):
        from apps.activities.services import reschedule

        carry_forward_rate_card(self.cd, "2027")
        fy26 = self._visit_on(SEP_29_2026)
        with self.assertRaisesMessage(BadRequest, "FY2026 work"):
            reschedule(
                fy26["id"],
                {"scheduledDate": _at(OCT_6_2026).isoformat(), "reason": "Moved"},
                self.user,
            )
        self.assertEqual(Activity.objects.get(id=fy26["id"]).fy, "2026")

    def test_my_plan_offers_fy2027_and_shows_october_work(self):
        from apps.my_plan.services import get_frontend_context

        carry_forward_rate_card(self.cd, "2027")
        result = self._visit_on(OCT_6_2026)
        context = get_frontend_context(
            self.user, {"fy": "2027", "month": "10", "week": "1", "period": "week"}
        )
        self.assertIn("2027", context["fy_options"])
        ids = {row["id"] for row in context["school_visits_all"]}
        self.assertIn(result["id"], ids)
        september = get_frontend_context(
            self.user, {"fy": "2026", "month": "10", "week": "1", "period": "week"}
        )
        self.assertNotIn(
            result["id"], {row["id"] for row in september["school_visits_all"]}
        )

    def test_the_planner_and_cd_to_dos_close_when_the_work_exists(self):
        from apps.planning.fy_todos import fy_planning_todos

        today = timezone.localdate()
        planner_rows = fy_planning_todos(self.user, "CCEO", today)
        cd_rows = fy_planning_todos(self.cd, "CountryDirector", today)
        if not fy_policy.next_open_fy():
            self.skipTest("FY2027 is already the operational year on this clock.")
        self.assertIn("fy-plan-2027", {r["id"] for r in planner_rows})
        self.assertIn("fy-rate-card-2027", {r["id"] for r in cd_rows})
        carry_forward_rate_card(self.cd, "2027")
        self._visit_on(OCT_6_2026)
        self.assertEqual(fy_planning_todos(self.user, "CCEO", today), [])
        self.assertEqual(fy_planning_todos(self.cd, "CountryDirector", today), [])


class FiscalYearPlanningPageTest(TestCase):
    def setUp(self):
        self.cd = User.objects.create_user(
            email="fypage-cd@edify.org",
            name="Page CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
        )
        self.cceo = User.objects.create_user(
            email="fypage-cceo@edify.org",
            name="Page CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
        )

    def test_the_cd_reads_the_policies_and_a_cceo_is_refused(self):
        self.client.force_login(self.cd)
        page = self.client.get("/planning/fiscal-years")
        self.assertContains(page, "Fiscal Year Planning")
        self.assertContains(page, "FY2027")
        self.client.force_login(self.cceo)
        refused = self.client.get("/planning/fiscal-years")
        self.assertRedirects(refused, "/dashboard", fetch_redirect_response=False)

    def test_opening_a_year_is_audited_and_announced(self):
        from apps.notifications.models import Notification

        with self.captureOnCommitCallbacks(execute=True):
            policy = fy_policy.open_fy_planning(
                "2028", self.cd, notes="Early planning for FY2028."
            )
        self.assertEqual(policy.execution_start, datetime.date(2027, 10, 1))
        self.assertEqual(policy.execution_end, datetime.date(2028, 9, 30))
        self.assertTrue(AuditLog.objects.filter(action="fy.planning_opened").exists())
        self.assertTrue(
            Notification.objects.filter(
                source_event_type="fy_planning_opened", recipient_id=self.cceo.id
            ).exists()
        )
        with self.assertRaises(Forbidden):
            fy_policy.open_fy_planning("2029", self.cceo)
