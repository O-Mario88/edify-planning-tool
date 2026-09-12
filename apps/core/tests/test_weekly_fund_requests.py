from __future__ import annotations

from datetime import date

from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class WeeklyFundRequestsTest(APITestCase):
    def setUp(self):
        CostCatalogue.objects.get_or_create(
            fy=get_operational_fy(),
            version=1,
            defaults={"label": "Weekly fund request test catalogue"},
        )
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.sub_county = SubCounty.objects.create(
            name="Makindye", district=self.district
        )

        # Set up active Cost settings
        for key, cost in [
            ("school_visit_cost_per_school", 62000),
            ("school_visit_cost_per_school_primary", 50000),
            ("school_visit_cost_per_school_secondary", 66000),
            ("primary_transport_per_day", 50000),
            ("lunch_per_day", 12000),
            ("tot_trainings_meals", 12000),
            ("group_training_venue_cost", 200000),
            ("group_training_facilitation_fee", 150000),
            ("partner_visit_rate", 80000),
        ]:
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key.replace("_", " ").title(),
                    "unit_cost": cost,
                    "version": 1,
                },
            )

        self.cceo = User.objects.create_user(
            email="cceo@test.com",
            name="Field CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")

        # The CCEO's supervising PL — their weekly requests route here.
        self.pl = User.objects.create_user(
            email="pl@test.com",
            name="Team PL",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            password="x",
            is_active=True,
        )
        self.pl_staff = StaffProfile.objects.create(user=self.pl, title="PL")
        from apps.accounts.models import StaffSupervisorAssignment

        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_staff, supervisee=self.staff
        )

        self.accountant = User.objects.create_user(
            email="finance@test.com",
            name="Finance Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x",
            is_active=True,
        )
        self.accountant_profile = StaffProfile.objects.create(
            user=self.accountant, title="Accountant"
        )

        from apps.clusters.models import Cluster

        self.cluster = Cluster.objects.create(
            id="some-cluster",
            name="Makindye Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
        )

        self.school = School.objects.create(
            school_id="S-123",
            name="Kampala Primary",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_id=self.cluster.id,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        from apps.accounts.models import StaffSchoolAssignment

        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)

        # The mandatory Activity Catalogue gates scheduling on a current
        # confirmed SSA. Enrolment (2) is the weakest intervention and
        # financial_health (3) the second-weakest, which makes
        # FEES_ENROLMENT_MARKETING (cluster_meeting) and
        # ACCOUNTING_FINANCIAL_MANAGEMENT (cluster_training) primary cluster
        # recommendations for this suite's member school.
        from django.utils import timezone

        from apps.core.enums import SsaIntervention
        from apps.ssa.models import SsaRecord, SsaScore

        record = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.now(),
            fy=get_operational_fy(),
            quarter="Q1",
            average_score=7,
            verification_status="confirmed",
            uploaded_by="test",
        )
        scores = {
            SsaIntervention.ENROLMENT: 2,
            SsaIntervention.FINANCIAL_HEALTH: 3,
        }
        for intervention, _label in SsaIntervention.choices:
            SsaScore.objects.create(
                ssa_record=record,
                intervention=intervention,
                score=scores.get(intervention, 8),
            )

    def _as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}"
        )

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
        # Catalogue-mandatory: a dated staff school visit is the
        # CLIENT_SCHOOL_FOLLOWUP_VISIT item (workflow_kind follow_up_visit).
        # Without a source training, a dynamic follow-up must target the
        # school's current weakest unresolved SSA intervention (enrolment).
        sv = self._post(
            "/api/activities/schedule-school-visit",
            {
                "schoolId": "S-123",
                "catalogueItemId": "CLIENT_SCHOOL_FOLLOWUP_VISIT",
                "scheduledDate": "2026-07-08T09:00:00+03:00",
                "focusIntervention": "enrolment",
            },
            201,
        )

        # Confirm the governed transport + lunch split is persisted and that
        # a staff visit carries nothing else (owner, 2026-09-12).
        lines = ActivityScheduleCostLine.objects.filter(activity_id=sv["id"])
        self.assertEqual(lines.count(), 2)
        self.assertEqual(
            set(lines.values_list("cost_setting_key", "amount")),
            {
                ("primary_transport_per_day", 50000),
                ("lunch_per_day", 12000),
            },
        )
        self.assertEqual(
            set(lines.values_list("week_start_date", flat=True)),
            {date(2026, 7, 6)},
        )

        # 2. Schedule a Cluster Meeting (10 participants, rate = 8000 each).
        # FEES_ENROLMENT_MARKETING is the cluster_meeting item for enrolment,
        # the member school's weakest verified intervention → primary
        # recommendation, no override reason needed.
        cm = self._post(
            "/api/activities/schedule-cluster-activity",
            {
                "activityType": "cluster_meeting",
                "catalogueItemId": "FEES_ENROLMENT_MARKETING",
                "clusterId": "some-cluster",
                "scheduledDate": "2026-07-09T10:00:00+03:00",
                "expectedParticipants": 10,
            },
            201,
        )

        # A cluster meeting (2026-09-06 catalogue): its own rate, the venue,
        # printing and photocopying (all 0 until the CD sets them) and the
        # staff day. Nobody is fed at a meeting.
        cm_lines = ActivityScheduleCostLine.objects.filter(activity_id=cm["id"])
        self.assertEqual(cm_lines.count(), 6)
        self.assertEqual(sum(l.amount for l in cm_lines), 262000)
        self.assertEqual(
            cm_lines.get(cost_setting_key="group_training_venue_cost").amount, 200000
        )

        # 3. Schedule a Group Training (15 participants: venue=200000,
        # facilitation=150000, materials 0, staff day 62000). Total = 412,000
        # ACCOUNTING_FINANCIAL_MANAGEMENT is the cluster_training item for
        # financial_health, the second-weakest verified intervention →
        # also a primary cluster recommendation.
        gt = self._post(
            "/api/activities/schedule-cluster-activity",
            {
                "activityType": "cluster_training",
                "catalogueItemId": "ACCOUNTING_FINANCIAL_MANAGEMENT",
                "clusterId": "some-cluster",
                "scheduledDate": "2026-07-10T09:00:00+03:00",
                "expectedParticipants": 15,
            },
            201,
        )

        gt_lines = ActivityScheduleCostLine.objects.filter(activity_id=gt["id"])
        self.assertEqual(sum(l.amount for l in gt_lines), 412000)
        self.assertEqual(
            Activity.objects.get(id=gt["id"]).expected_participants,
            15,
        )
        self.assertEqual(
            {line.cost_setting_key for line in gt_lines},
            {
                "cluster_meetings_trainings",
                "group_training_facilitation_fee",
                "group_training_venue_cost",
                "printing_training_materials",
                "photocopying_training_materials",
                "primary_transport_per_day",
                "lunch_per_day",
            },
        )

        # 4. Generate Weekly Fund Request (aggregates all 3 activities)
        # 62,000 visit + 262,000 meeting + 412,000 training = 736,000 UGX, less
        # the visit's 50,000 vendor-direct transport.
        wfr_data = self._post(
            "/api/fund-requests/weekly/generate",
            {
                "weekStartDate": "2026-07-06",
                "responsibleUser": self.cceo.user_id,
            },
            200,
        )

        self.assertEqual(wfr_data["totalAmount"], 686000)  # transport is vendor-direct
        self.assertEqual(wfr_data["status"], "pending_responsible_confirmation")

        # 5. Retrieve weekly requests list and detail
        list_res = self._get("/api/fund-requests/weekly")
        self.assertEqual(len(list_res), 1)

        detail_res = self._get(f"/api/fund-requests/weekly/{wfr_data['id']}")
        # Every staff-payable component of the three activities: vendor-direct
        # transport stays out of the request, and so does a line worth nothing.
        from apps.fund_requests.fundable import vendor_direct_filter

        payable = (
            ActivityScheduleCostLine.objects.filter(
                activity_id__in=[sv["id"], cm["id"], gt["id"]]
            )
            .exclude(vendor_direct_filter())
            .exclude(amount=0)
        )
        self.assertEqual(len(detail_res["lines"]), payable.count())
        descriptions = {line["description"] for line in detail_res["lines"]}
        self.assertTrue(
            {"Facilitation Fee", "Venue Fee", "Lunch"}.issubset(descriptions)
        )

        # 6. CCEO submits — the request routes to their PL for approval;
        # submission alone must NOT put it in the accountant's queue.
        confirm_res = self._post(
            f"/api/fund-requests/{wfr_data['id']}/request-advance", {}, 200
        )
        self.assertEqual(confirm_res["status"], "submitted_to_pl")

        # 6b. Accountant cannot disburse an unapproved request (LAW 15).
        self._as(self.accountant)
        self._post(
            f"/api/fund-requests/{wfr_data['id']}/disburse",
            {"amount": 586000, "method": "Mobile Money", "reference": "TXN-9988"},
            400,
        )

        # 6c. The supervising PL approves → confirmed_for_advance.
        from apps.fund_requests.weekly_service import approve_weekly_request

        approved = approve_weekly_request(wfr_data["id"], self.pl)
        self.assertEqual(approved["status"], "confirmed_for_advance")

        # 7. Disburse as Accountant
        disburse_res = self._post(
            f"/api/fund-requests/{wfr_data['id']}/disburse",
            {
                "amount": 586000,
                "method": "Mobile Money",
                "reference": "TXN-9988",
            },
            200,
        )

        self.assertEqual(disburse_res["status"], "disbursed")
        self.assertEqual(disburse_res["disbursedAmount"], 586000)
