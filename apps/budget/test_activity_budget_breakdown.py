"""The activity page shows how its cost is made up.

Owner, 2026-10-05: "make sure the activity profile shows the budget breakdown
for that activity for the team to make sure it is the right cost."

What is pinned here: the rows are the stored budget lines and add up to the
activity's cost; the working beside each amount reproduces it (the day's rate
divided between the activities sharing the day, or a quantity times a rate);
a line the page cannot reproduce shows no arithmetic rather than a wrong one;
and the page and its drawer both draw the table.
"""

from __future__ import annotations

from datetime import date

from django.db.models import F
from django.test import Client
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import StaffSchoolAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.breakdown import activity_budget_breakdown
from apps.budget.costing_service import planned_minimum_amounts
from apps.budget.models import ActivityCostSnapshot, CostSetting
from apps.daily_visit_batches.tests import (
    PRIMARY_RATES,
    SECONDARY_RATES,
    DailyVisitBatchTestCase,
)
from apps.schools.models import School

TRANSPORT = dict(PRIMARY_RATES)["primary_transport_per_day"]
LUNCH = dict(PRIMARY_RATES)["lunch_per_day"]
MON, TUE, WED = date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)


@freeze_time("2026-07-27")
class ActivityBudgetBreakdownTest(DailyVisitBatchTestCase):
    def _visits(self, school_ids, day):
        result = self._schedule(school_ids, day, reason="as planned")
        return [
            Activity.objects.select_related("school", "cluster").get(id=row["id"])
            for row in result["activities"]
        ]

    def _breakdown(self, activity, **kwargs):
        activity = Activity.objects.select_related("school", "cluster").get(
            id=activity.id
        )
        return activity_budget_breakdown(activity, staff_name="Batch Staff", **kwargs)

    def _secondary_school(self, n):
        school = School.objects.create(
            school_id=f"BRK-{n}",
            name=f"Breakdown Away School {n}",
            region=self.region,
            district=self.secondary_district_a,
            sub_county=self.sub_county,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.staff_profile, school_id=school.id
        )
        return school

    # ── The rows are the budget ──────────────────────────────────────────────
    def test_a_lone_visit_carries_the_whole_day(self):
        (visit,) = self._visits(["BATCH-P-1"], MON)
        budget = self._breakdown(visit)

        self.assertEqual(
            [(row["key"], row["amount"]) for row in budget["rows"]],
            [("primary_transport_per_day", TRANSPORT), ("lunch_per_day", LUNCH)],
        )
        self.assertEqual(
            [row["basis"] for row in budget["rows"]],
            [f"1 × UGX {TRANSPORT:,} per day", f"1 × UGX {LUNCH:,} per day"],
        )
        self.assertEqual(budget["total"], TRANSPORT + LUNCH)
        self.assertEqual(budget["total"], visit.est_cost_cents)
        self.assertEqual(budget["day"]["count"], 1)
        self.assertIn("the only activity Batch Staff has", budget["day"]["sentence"])
        self.assertIn("Monday 3 August 2026", budget["day"]["sentence"])
        self.assertEqual(budget["day"]["others"], [])
        self.assertEqual(budget["empty_note"], "")

    def test_a_shared_day_shows_the_rate_and_how_many_share_it(self):
        visits = self._visits(["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], MON)
        budgets = [self._breakdown(visit) for visit in visits]

        for visit, budget in zip(visits, budgets):
            with self.subTest(school=visit.school.school_id):
                self.assertEqual(
                    [row["basis"] for row in budget["rows"]],
                    [
                        f"UGX {TRANSPORT:,} per day ÷ 3 activities",
                        f"UGX {LUNCH:,} per day ÷ 3 activities",
                    ],
                )
                self.assertEqual(budget["total"], visit.est_cost_cents)
                self.assertEqual(
                    budget["total"],
                    sum(
                        line.amount
                        for line in ActivityScheduleCostLine.objects.filter(
                            activity=visit
                        )
                    ),
                )
                self.assertIn("has 3 activities on Monday", budget["day"]["sentence"])
                self.assertIn(
                    "transport and lunch are paid once", budget["day"]["sentence"]
                )
                self.assertEqual(
                    {other["id"] for other in budget["day"]["others"]},
                    {other.id for other in visits} - {visit.id},
                )
        # The three shares are the whole day, to the shilling.
        self.assertEqual(sum(b["total"] for b in budgets), TRANSPORT + LUNCH)
        self.assertEqual(
            {other["place"] for other in budgets[0]["day"]["others"]},
            {visit.school.name for visit in visits[1:]},
        )

    def test_a_day_away_shows_the_night_and_the_day_home_says_why_it_has_none(self):
        first, second = self._secondary_school(1), self._secondary_school(2)
        (away,) = self._visits([first.school_id], TUE)
        (home,) = self._visits([second.school_id], WED)

        away_budget = self._breakdown(away)
        rates = dict(SECONDARY_RATES)
        self.assertEqual(
            {row["key"]: row["basis"] for row in away_budget["rows"]},
            {
                "secondary_transport_per_day": (
                    f"1 × UGX {rates['secondary_transport_per_day']:,} per day"
                ),
                "lunch_per_day": f"1 × UGX {rates['lunch_per_day']:,} per day",
                "secondary_breakfast_per_day": (
                    f"1 × UGX {rates['secondary_breakfast_per_day']:,} per day away"
                ),
                "secondary_overnight_dinner_per_day": (
                    f"1 × UGX {rates['secondary_overnight_dinner_per_day']:,} "
                    "per day away"
                ),
                "secondary_accommodation_per_night": (
                    f"1 × UGX {rates['secondary_accommodation_per_night']:,} per night"
                ),
            },
        )
        self.assertEqual(away_budget["total"], sum(rates.values()))
        self.assertEqual(away_budget["notes"], [])

        home_budget = self._breakdown(home)
        self.assertEqual(
            [row["key"] for row in home_budget["rows"]],
            [
                "secondary_transport_per_day",
                "lunch_per_day",
                "secondary_breakfast_per_day",
            ],
        )
        self.assertEqual(len(home_budget["notes"]), 1)
        self.assertIn("day home", home_budget["notes"][0])
        self.assertIn("no accommodation and no dinner", home_budget["notes"][0])

    # ── The working never contradicts the amount ─────────────────────────────
    def test_a_line_changed_behind_its_snapshot_shows_no_arithmetic(self):
        """A repair that rewrites a line leaves the snapshot behind; the row
        then says what it is rather than a sum that does not add up."""
        first, _second = self._visits(["BATCH-P-1", "BATCH-P-2"], MON)
        ActivityScheduleCostLine.objects.filter(
            activity=first, cost_setting_key="lunch_per_day"
        ).update(amount=1, unit_cost=1)

        rows = {row["key"]: row for row in self._breakdown(first)["rows"]}
        self.assertEqual(rows["lunch_per_day"]["basis"], "Share of the day's cost")
        self.assertEqual(rows["lunch_per_day"]["amount"], 1)
        self.assertIsNone(rows["lunch_per_day"]["minimum"])
        self.assertEqual(
            rows["primary_transport_per_day"]["basis"],
            f"UGX {TRANSPORT:,} per day ÷ 2 activities",
        )

    def test_every_basis_reproduces_its_amount(self):
        """Read the arithmetic back off the page text: rate ÷ n, or n × rate."""
        visits = self._visits(["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], MON)
        visits += self._visits([self._secondary_school(3).school_id], WED)
        for visit in visits:
            for row in self._breakdown(visit)["rows"]:
                with self.subTest(activity=visit.id, key=row["key"]):
                    figures = [
                        int(word.replace(",", ""))
                        for word in row["basis"].replace("UGX ", "").split()
                        if word.replace(",", "").isdigit()
                    ]
                    if "÷" in row["basis"]:
                        rate, share = figures
                        self.assertIn(row["amount"], (rate // share, rate // share + 1))
                    else:
                        quantity, rate = figures
                        self.assertEqual(row["amount"], quantity * rate)

    # ── Minimum viable rates ─────────────────────────────────────────────────
    def test_the_minimum_column_appears_only_when_a_minimum_differs(self):
        # The Country Director has set no lower floor: each rate is its own.
        CostSetting.objects.filter(catalogue=self.catalogue).update(
            approved_minimum=F("unit_cost")
        )
        visits = self._visits(["BATCH-P-1", "BATCH-P-2"], MON)
        budget = self._breakdown(visits[0])
        self.assertFalse(budget["show_minimum"])
        self.assertEqual(budget["minimum_total"], budget["total"])

        CostSetting.objects.filter(
            catalogue=self.catalogue, key="lunch_per_day"
        ).update(approved_minimum=LUNCH - 10_000)

        for visit in visits:
            with self.subTest(school=visit.school.school_id):
                budget = self._breakdown(visit)
                self.assertTrue(budget["show_minimum"])
                # Line by line it is the figure the plan tables show.
                self.assertEqual(
                    budget["minimum_total"],
                    planned_minimum_amounts([visit])[visit.id],
                )
                self.assertEqual(budget["minimum_total"], budget["total"] - 10_000 // 2)
                # The budget itself is untouched by the minimum.
                self.assertEqual(budget["total"], visit.est_cost_cents)

    # ── In-school training: one cost, on the visit ───────────────────────────
    def test_an_in_school_training_points_at_the_visit_that_carries_its_cost(self):
        (visit,) = self._visits(["BATCH-P-1"], MON)
        training = Activity.objects.create(
            school_id=visit.school_id,
            activity_type="in_school_training",
            status="scheduled",
            responsible_staff_id=visit.responsible_staff_id,
            fy=visit.fy,
            quarter=visit.quarter,
            planned_date=visit.planned_date,
            paired_school_visit=visit,
        )

        training_budget = self._breakdown(training)
        self.assertEqual(training_budget["rows"], [])
        self.assertEqual(
            training_budget["empty_note"], "UGX 0 (captured in the school visit cost)"
        )
        self.assertEqual(
            training_budget["empty_link"],
            {"id": visit.id, "label": "Open the school visit"},
        )

        visit_budget = self._breakdown(visit)
        self.assertEqual(visit_budget["total"], TRANSPORT + LUNCH)
        self.assertEqual(len(visit_budget["notes"]), 1)
        self.assertIn("in-school training", visit_budget["notes"][0])

    def test_an_activity_with_no_lines_says_so(self):
        activity = Activity.objects.create(
            school_id=self.schools["p1"].id,
            activity_type="school_visit",
            status="planned",
            responsible_staff_id=self.staff_user.id,
            fy=self.catalogue.fy,
            quarter="Q4",
        )
        budget = self._breakdown(activity)
        self.assertEqual(budget["rows"], [])
        self.assertEqual(
            budget["empty_note"],
            "No budget has been worked out for this activity yet.",
        )
        self.assertIsNone(budget["empty_link"])
        self.assertIsNone(budget["day"])

    # ── A rate the card does not carry ───────────────────────────────────────
    def _hand_priced(self, breakdown, *, missing=(), **activity_fields):
        activity = Activity.objects.create(
            school_id=self.schools["p2"].id,
            status="scheduled",
            responsible_staff_id=self.staff_user.id,
            fy=self.catalogue.fy,
            quarter="Q4",
            planned_date=MON,
            **activity_fields,
        )
        for line in breakdown:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key=line["key"],
                label=line["label"],
                unit_cost=line["unit"] or 0,
                quantity=line["qty"],
                amount=line["amount"],
                catalogue_id=self.catalogue.id,
                catalogue_version=self.catalogue.version,
                line_item_type=line.get("lineItemType"),
            )
        ActivityCostSnapshot.objects.create(
            activity=activity,
            operational_rate_card=self.catalogue,
            operational_cost=sum(line["amount"] for line in breakdown),
            operational_breakdown=breakdown,
            missing_configuration=list(missing),
            calculated_at=timezone.now(),
        )
        return activity

    def test_a_missing_rate_is_named_not_priced_at_nothing(self):
        activity = self._hand_priced(
            [
                {
                    "key": "group_training_venue_cost",
                    "label": "Venue Fee",
                    "unit": None,
                    "qty": 1,
                    "amount": 0,
                    "missing": True,
                },
                {
                    "key": "cluster_meetings_trainings_meals",
                    "label": "Cluster Meeting - Participant Meals",
                    "unit": 5000,
                    "qty": 12,
                    "amount": 60000,
                    "missing": False,
                },
            ],
            missing=["group_training_venue_cost"],
            activity_type="cluster_meeting",
        )
        budget = self._breakdown(activity)
        rows = {row["key"]: row for row in budget["rows"]}

        self.assertTrue(rows["group_training_venue_cost"]["missing"])
        self.assertEqual(
            rows["group_training_venue_cost"]["basis"],
            "Rate not set in the Cost Catalogue",
        )
        self.assertEqual(
            rows["cluster_meetings_trainings_meals"]["basis"],
            "12 × UGX 5,000 per participant per day",
        )
        self.assertIn("Cost setup required", budget["missing_note"])
        self.assertIn("so this total is incomplete", budget["missing_note"])
        self.assertFalse(budget["show_minimum"])

    # ── A partner reads what it is paid ──────────────────────────────────────
    def test_a_partner_sees_its_rate_and_never_the_staff_day(self):
        partner_visit = self._hand_priced(
            [
                {
                    "key": "client_partner_visit",
                    "label": "Client Partner Visit [Rate basis: per activity]",
                    "unit": 40000,
                    "qty": 1,
                    "amount": 40000,
                    "missing": False,
                    "lineItemType": "lump_sum",
                }
            ],
            activity_type="school_visit",
            delivery_type="partner",
        )
        budget = self._breakdown(partner_visit, partner_view=True)
        self.assertEqual(
            [(row["basis"], row["amount"]) for row in budget["rows"]],
            [("1 × UGX 40,000 per visit", 40000)],
        )
        self.assertNotIn("Rate basis", budget["rows"][0]["label"])
        self.assertIsNone(budget["day"])

        (staff_visit,) = self._visits(["BATCH-P-1"], TUE)
        staff_budget = self._breakdown(staff_visit, partner_view=True)
        self.assertEqual(staff_budget["rows"], [])
        self.assertIsNone(staff_budget["day"])

    # ── The page and the drawer ──────────────────────────────────────────────
    def test_the_activity_page_and_its_drawer_draw_the_breakdown(self):
        visits = self._visits(["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], MON)
        visit = visits[0]
        client = Client()
        client.force_login(self.staff_user)

        for label, headers in (("page", {}), ("drawer", {"HTTP_HX_REQUEST": "true"})):
            with self.subTest(surface=label):
                response = client.get(f"/my-plan/{visit.id}", **headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["budget"]["total"], visit.est_cost_cents
                )
                html = response.content.decode()
                self.assertIn("Budget breakdown", html)
                self.assertIn('data-budget-line="primary_transport_per_day"', html)
                self.assertIn(f"UGX {TRANSPORT:,} per day ÷ 3 activities", html)
                self.assertIn(f"Total UGX {visit.est_cost_cents:,}", html)
                self.assertIn("data-budget-day", html)
                for other in visits[1:]:
                    self.assertIn(f'href="/activities/{other.id}"', html)

        # The full page answers at /activities/<id> too, where the links go.
        response = client.get(f"/activities/{visits[1].id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Budget breakdown", response.content.decode())

    def test_an_uncosted_training_page_shows_the_note_and_the_link(self):
        (visit,) = self._visits(["BATCH-P-1"], MON)
        training = Activity.objects.create(
            school_id=visit.school_id,
            activity_type="in_school_training",
            status="scheduled",
            responsible_staff_id=visit.responsible_staff_id,
            fy=visit.fy,
            quarter=visit.quarter,
            planned_date=visit.planned_date,
            paired_school_visit=visit,
        )
        client = Client()
        client.force_login(self.staff_user)
        response = client.get(f"/my-plan/{training.id}")
        html = response.content.decode()
        # The headline is UGX 0 with where the cost is, never "not configured".
        self.assertEqual(response.context["activity_cost"]["amount"], 0)
        self.assertEqual(
            response.context["activity_cost"]["note"],
            "Captured in the school visit cost",
        )
        self.assertNotIn("Minimum viable cost not configured", html)
        self.assertIn("data-budget-empty", html)
        self.assertIn("UGX 0 (captured in the school visit cost)", html)
        self.assertIn(f'href="/activities/{visit.id}"', html)
        self.assertNotIn("data-budget-line", html)
