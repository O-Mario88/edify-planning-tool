from __future__ import annotations

from rest_framework.test import APITestCase
from django.utils import timezone
from datetime import datetime

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import StaffProfile, User
from apps.activities.models import ActivityScheduleCostLine, Activity
from apps.budget.models import CostSetting
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School
from apps.fund_requests.models import WeeklyFundRequest, WeeklyFundRequestLine


class WeeklyFundRequestsTest(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.sub_county = SubCounty.objects.create(name="Makindye", district=self.district)

        # Set up active Cost settings
        for key, cost in [
            ("school_visit_cost_per_school", 62000),
            ("school_visit_cost_per_school_primary", 50000),
            ("school_visit_cost_per_school_secondary", 66000),
            ("group_training_participant_meal_cost_per_head", 12000),
            ("group_training_venue_cost", 200000),
            ("group_training_facilitation_fee", 150000),
            ("cluster_meeting_participant_meal_cost_per_head", 8000),
            ("partner_visit_rate", 80000),
        ]:
            CostSetting.objects.create(key=key, label=key.replace("_", " ").title(), unit_cost=cost, version=1)

        self.cceo = User.objects.create_user(
            email="cceo@test.com", name="Field CCEO",
            roles=[EdifyRole.CCEO.value], active_role=EdifyRole.CCEO.value,
            password="x", is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")

        self.accountant = User.objects.create_user(
            email="finance@test.com", name="Finance Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value], active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x", is_active=True,
        )
        self.accountant_profile = StaffProfile.objects.create(user=self.accountant, title="Accountant")

        from apps.clusters.models import Cluster
        self.cluster = Cluster.objects.create(
            id="some-cluster", name="Makindye Cluster", region=self.region,
            district=self.district, sub_county=self.sub_county,
        )

        self.school = School.objects.create(
            school_id="S-123", name="Kampala Primary", region=self.region,
            district=self.district, sub_county=self.sub_county, cluster_id=self.cluster.id,
            current_fy_ssa_status="done", planning_readiness="ready",
        )
        from apps.accounts.models import StaffSchoolAssignment
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)

    def _as(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}")

    def _post(self, path, data, expected=201):
        r = self.client.post(path, data, format="json")
        self.assertEqual(r.status_code, expected, r.content)
        return r.json()

    def _get(self, path, expected=200):
        r = self.client.get(path)
        self.assertEqual(r.status_code, expected, r.content)
        return r.json()

    def test_weekly_fund_request_flow(self):
        self._as(self.cceo)

        # 1. Schedule a school visit (Primary district rate)
        # Week start: 2026-07-06 (Monday), Date: 2026-07-08 (Wednesday)
        sv = self._post("/api/activities/schedule-school-visit", {
            "schoolId": "S-123",
            "scheduledDate": "2026-07-08T09:00:00+03:00",
            "purposeIntervention": "leadership",
        }, 201)

        # Confirm budget lines exist and use primary visit rate (50,000)
        lines = ActivityScheduleCostLine.objects.filter(activity_id=sv["id"])
        self.assertEqual(lines.count(), 1)
        self.assertEqual(lines[0].amount, 50000)
        self.assertEqual(lines[0].week_start_date.isoformat(), "2026-07-06")

        # 2. Schedule a Cluster Meeting (10 participants, rate = 8000 each)
        cm = self._post("/api/activities/schedule-cluster-activity", {
            "activityType": "cluster_meeting",
            "clusterId": "some-cluster",
            "scheduledDate": "2026-07-09T10:00:00+03:00",
            "expectedParticipants": 10,
        }, 201)

        cm_lines = ActivityScheduleCostLine.objects.filter(activity_id=cm["id"])
        self.assertEqual(cm_lines.count(), 1)
        self.assertEqual(cm_lines[0].amount, 80000) # 10 * 8,000

        # 3. Schedule a Group Training (15 participants: meals=15*12000=180000, venue=200000, facilitation=150000)
        # Total = 530,000
        gt = self._post("/api/activities/schedule-cluster-activity", {
            "activityType": "cluster_training",
            "clusterId": "some-cluster",
            "scheduledDate": "2026-07-10T09:00:00+03:00",
            "expectedParticipants": 15,
        }, 201)

        gt_lines = ActivityScheduleCostLine.objects.filter(activity_id=gt["id"])
        self.assertEqual(sum(l.amount for l in gt_lines), 530000)

        # 4. Generate Weekly Fund Request (aggregates all 3 activities)
        # Total: 50,000 + 80,000 + 530,000 = 660,000 UGX
        wfr_data = self._post("/api/fund-requests/weekly/generate", {
            "weekStartDate": "2026-07-06",
            "responsibleUser": self.cceo.user_id,
        }, 200)

        self.assertEqual(wfr_data["totalAmount"], 660000)
        self.assertEqual(wfr_data["status"], "pending_responsible_confirmation")

        # 5. Retrieve weekly requests list and detail
        list_res = self._get("/api/fund-requests/weekly")
        self.assertEqual(len(list_res), 1)

        detail_res = self._get(f"/api/fund-requests/weekly/{wfr_data['id']}")
        self.assertEqual(len(detail_res["lines"]), 5) # 1 school visit, 1 cluster meeting, 3 group training lines

        # 6. Confirm Request Advance
        confirm_res = self._post(f"/api/fund-requests/{wfr_data['id']}/request-advance", {}, 200)
        self.assertEqual(confirm_res["status"], "confirmed_for_advance")

        # 7. Disburse as Accountant
        self._as(self.accountant)
        disburse_res = self._post(f"/api/fund-requests/{wfr_data['id']}/disburse", {
            "amount": 660000,
            "method": "Mobile Money",
            "reference": "TXN-9988",
        }, 200)

        self.assertEqual(disburse_res["status"], "disbursed")
        self.assertEqual(disburse_res["disbursedAmount"], 660000)
