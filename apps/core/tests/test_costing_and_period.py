"""Costing, budget-line, and period-filter correctness for the Monday demo path.

Verifies the three things the audit flagged as fragile, through authenticated
API calls (the same path the frontend uses):
  1. Reschedule re-prices the activity against the current catalogue and
     replaces its budget lines (the budget line follows the activity, and the
     period fields move with the new schedule).
  2. A fund request total is provably the SUM of its persisted budget-line items
     (FundRequestItem.amount), and an activity with no lines blocks submission.
  3. My Plan honours the period (week/month/quarter/fy) instead of returning the
     whole fiscal year for every view.

Isolated test DB only — never touches the persistent/local database.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import ActivityScheduleCostLine
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import FundRequestItem
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class CostingBudgetPeriodTest(APITestCase):
    def setUp(self):
        # Scheduling has a deliberate published-catalogue gate. This suite
        # tests cost/period behaviour after that valid operational setup.
        CostCatalogue.objects.get_or_create(
            fy=get_operational_fy(),
            version=1,
            defaults={"label": "Costing period test catalogue"},
        )[0]
        self.region = Region.objects.create(name="Cost Region")
        # district_type is required for staff school-visit reschedule, which
        # now routes through Daily Visit Batch pricing (day-based, shared cost
        # across schools scheduled the same day) rather than a flat per-visit
        # rate — see apps.daily_visit_batches.
        self.district = District.objects.create(
            name="Cost District", region=self.region, district_type="primary"
        )
        self.sub_county = SubCounty.objects.create(
            name="Cost Sub", district=self.district
        )
        # Complete rate card so no scheduled activity is cost-missing. Legacy
        # keys price the initial /api/planning/schedule-school-visit create;
        # the Daily Visit Batch keys price any subsequent reschedule.
        for key, cost in [
            ("staff_visit_transport_primary", 15000),
            ("lunch", 8000),
            ("primary_transport_per_day", 15000),
            ("primary_lunch_per_day", 8000),
        ]:
            # update_or_create: primary_transport_per_day/primary_lunch_per_day
            # are seeded by a data migration (apps.budget.migrations.0005) onto
            # every environment including the test DB, so they may already exist.
            CostSetting.objects.update_or_create(
                key=key, defaults={"label": key, "unit_cost": cost, "version": 1}
            )

        self.cceo = User.objects.create_user(
            email="cost@cceo.test",
            name="Cost Cceo",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        # The mandatory Activity Catalogue makes a dated staff school visit a
        # CLIENT_SCHOOL_FOLLOWUP_VISIT, and that catalogue item is restricted
        # to client schools. It carries counts_toward_client_visit, so it
        # CONSUMES the one-visit-per-FY client entitlement — tests that need
        # more than one visit in a fiscal year must spread them across
        # distinct client schools.
        self.school = self._client_school("COST-SCH", "Cost Primary")
        self._as(self.cceo)

    def _client_school(self, school_id, name):
        school = School.objects.create(
            school_id=school_id,
            name=name,
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            current_fy_ssa_status="done",
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=school.id)
        # CLIENT_SCHOOL_FOLLOWUP_VISIT requires a current confirmed SSA —
        # scheduling intervention support is impossible without one.
        record = SsaRecord.objects.create(
            school=school,
            date_of_ssa=timezone.now(),
            fy=get_operational_fy(),
            quarter="Q1",
            average_score=7,
            verification_status="confirmed",
            uploaded_by="test",
        )
        for intervention, _label in SsaIntervention.choices:
            SsaScore.objects.create(
                ssa_record=record,
                intervention=intervention,
                score=3 if intervention == SsaIntervention.LEADERSHIP else 8,
            )
        return school

    # ── helpers ──────────────────────────────────────────────────────────────
    def _as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}"
        )

    def _post(self, path, data, expected):
        r = self.client.post(path, data, format="json")
        self.assertEqual(r.status_code, expected, r.content)
        return r.json()

    def _get(self, path, expected=200):
        r = self.client.get(path)
        self.assertEqual(r.status_code, expected, r.content)
        return r.json()

    def _make_visit(self, month=7, week=2, school_id="COST-SCH"):
        # Catalogue-mandatory contract: a dated staff school visit is the
        # CLIENT_SCHOOL_FOLLOWUP_VISIT catalogue item (workflow_kind
        # follow_up_visit); the focus intervention must be a canonical SSA
        # intervention. Each week gets its own day so the double-submit
        # duplicate guard (same type/target/day/owner) never fires on these
        # deliberately distinct visits. Days land Wed/Sat — never Sunday.
        day = 7 * week + 1
        return self._post(
            "/api/planning/schedule-school-visit",
            {
                "schoolId": school_id,
                "catalogueItemId": "CLIENT_SCHOOL_FOLLOWUP_VISIT",
                "scheduledDate": f"2026-0{month}-{day:02d}T09:00:00+03:00",
                "plannedMonth": month,
                "plannedWeek": week,
                "focusIntervention": "leadership",
            },
            201,
        )

    # ── 1. Reschedule re-prices + replaces budget lines ──────────────────────
    def test_reschedule_replaces_budget_lines_and_moves_period(self):
        a = self._make_visit(month=7, week=2)
        aid = a["id"]
        lines_before = list(ActivityScheduleCostLine.objects.filter(activity_id=aid))
        old_total = sum(l.amount for l in lines_before)
        self.assertGreater(len(lines_before), 0)
        self.assertEqual(a["plannedMonth"] if "plannedMonth" in a else 7, 7)

        # Raise the transport rate, then reschedule into a different month.
        # Reschedule prices via Daily Visit Batch (primary_transport_per_day),
        # not the legacy staff_visit_transport_primary key used at create time.
        CostSetting.objects.filter(key="primary_transport_per_day").update(
            unit_cost=99999
        )
        rescheduled = self._post(
            f"/api/activities/{aid}/reschedule",
            {
                "scheduledDate": "2026-09-15T09:00:00+03:00",
                "plannedMonth": 9,
                "plannedWeek": 3,
                "reason": "moved",
            },
            200,
        )

        lines_after = list(ActivityScheduleCostLine.objects.filter(activity_id=aid))
        new_total = sum(l.amount for l in lines_after)
        # Period moved with the new schedule.
        act = ActivityScheduleCostLine.objects.filter(activity_id=aid).first()
        from apps.activities.models import Activity

        refreshed = Activity.objects.get(id=aid)
        self.assertEqual(refreshed.planned_month, 9)
        self.assertEqual(refreshed.planned_week, 3)
        self.assertEqual(rescheduled["rescheduleCount"], 1)
        # Budget lines were replaced (old ids gone), and re-priced at the new rate.
        self.assertEqual(
            {l.id for l in lines_before} & {l.id for l in lines_after}, set()
        )
        self.assertGreater(
            new_total, old_total, "reschedule should re-price at the new rate"
        )

    # ── 2. Fund request total == sum of persisted budget-line items ──────────
    def test_fund_request_total_equals_line_item_sum(self):
        # One visit entitlement per client school per FY: the second visit
        # must target a second school, and the fund request still sums both
        # because it aggregates by owner and period, not by school.
        second = self._client_school("COST-SCH-2", "Cost Primary Two")
        a1 = self._make_visit(month=7, week=1)
        a2 = self._make_visit(month=7, week=2, school_id=second.school_id)
        # The fund REQUEST carries the staff-payable subset only: school-visit
        # transport is vendor-direct (paid to the transport company) and never
        # enters the owner's advance (fund_requests.fundable).
        expected = sum(
            l.amount
            for l in ActivityScheduleCostLine.objects.filter(
                activity_id__in=[a1["id"], a2["id"]]
            ).exclude(line_item_type="transport")
        )
        self.assertGreater(expected, 0)

        fr = self._post(
            "/api/fund-requests", {"fy": "2026", "period": "monthly", "month": 7}, 201
        )
        self.assertEqual(fr["status"], "submitted")
        self.assertEqual(fr["totalAmount"], expected)
        items = list(FundRequestItem.objects.filter(fund_request_id=fr["id"]))
        self.assertEqual(sum(i.amount for i in items), expected)
        self.assertTrue(all(i.activity_schedule_cost_line_id for i in items))

    def test_cost_missing_activity_blocks_fund_request(self):
        a = self._make_visit(month=7, week=1)
        # Strip the budget lines off the one activity → submission must be blocked.
        ActivityScheduleCostLine.objects.filter(activity_id=a["id"]).delete()
        r = self.client.post(
            "/api/fund-requests",
            {"fy": "2026", "period": "monthly", "month": 7},
            format="json",
        )
        self.assertEqual(r.status_code, 400, r.content)

    # ── 3. My Plan honours the period ────────────────────────────────────────
    def test_my_plan_period_narrows_the_window(self):
        # Distinct schools: each client school carries one visit per FY.
        second = self._client_school("COST-SCH-2", "Cost Primary Two")
        self._make_visit(month=7, week=1)
        self._make_visit(month=8, week=2, school_id=second.school_id)

        month7 = self._get("/api/my-plan?fy=2026&period=month&month=7")
        month8 = self._get("/api/my-plan?fy=2026&period=month&month=8")
        whole_fy = self._get("/api/my-plan?fy=2026&period=fy")

        self.assertEqual(month7["total"], 1)
        self.assertEqual(month7["items"][0]["month"], 7)
        self.assertEqual(month8["total"], 1)
        self.assertEqual(month8["items"][0]["month"], 8)
        # The FY view sees both; a month view does not leak across months.
        self.assertEqual(whole_fy["total"], 2)
        # Cost + evidence status surface on each item.
        self.assertIn("costCents", month7["items"][0])
        self.assertIn("evidenceStatus", month7["items"][0])
