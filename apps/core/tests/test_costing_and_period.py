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

from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import ActivityScheduleCostLine
from apps.budget.models import CostSetting
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import FundRequestItem
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class CostingBudgetPeriodTest(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Cost Region")
        self.district = District.objects.create(
            name="Cost District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Cost Sub", district=self.district
        )
        # Complete rate card so no scheduled activity is cost-missing.
        for key, cost in [
            ("staff_visit_transport_primary", 15000),
            ("lunch", 8000),
        ]:
            CostSetting.objects.create(key=key, label=key, unit_cost=cost, version=1)

        self.cceo = User.objects.create_user(
            email="cost@cceo.test",
            name="Cost Cceo",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.school = School.objects.create(
            school_id="COST-SCH",
            name="Cost Primary",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)
        self._as(self.cceo)

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

    def _make_visit(self, month=7, week=2):
        return self._post(
            "/api/planning/schedule-school-visit",
            {
                "schoolId": "COST-SCH",
                "scheduledDate": f"2026-0{month}-10T09:00:00+03:00",
                "plannedMonth": month,
                "plannedWeek": week,
                "purposeIntervention": "leadership",
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
        CostSetting.objects.filter(key="staff_visit_transport_primary").update(
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
        a1 = self._make_visit(month=7, week=1)
        a2 = self._make_visit(month=7, week=2)
        expected = sum(
            l.amount
            for l in ActivityScheduleCostLine.objects.filter(activity_id=a1["id"])
        ) + sum(
            l.amount
            for l in ActivityScheduleCostLine.objects.filter(activity_id=a2["id"])
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
        self._make_visit(month=7, week=1)
        self._make_visit(month=8, week=2)

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
