"""Authenticated real-data workflow smoke test.

The test creates only isolated Django test-database records. It intentionally
uses API endpoints for the workflow handoffs so persistent/local databases keep
their honest empty-state behavior and never receive demo records.
"""

from __future__ import annotations

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.budget.models import CostSetting
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import FundRequest, FundRequestItem
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


INTERVENTION_SCORES = [
    {"intervention": "teaching_environment", "score": 7},
    {"intervention": "financial_health", "score": 6},
    {"intervention": "christlike_behaviour", "score": 8},
    {"intervention": "exposure_to_word_of_god", "score": 7},
    {"intervention": "government_requirement", "score": 5},
    {"intervention": "leadership", "score": 6},
    {"intervention": "enrolment", "score": 4},
    {"intervention": "learning_environment", "score": 7},
]


@override_settings(
    EVIDENCE_STORAGE_DIR=tempfile.mkdtemp(prefix="edify-evidence-smoke-")
)
class AuthenticatedWorkflowSmokeTest(APITestCase):
    """Proves the July 10 path against authenticated Django API calls."""

    def setUp(self):
        self.region = Region.objects.create(name="Smoke Region")
        self.district = District.objects.create(
            name="Smoke District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Smoke SubCounty", district=self.district
        )

        self.ia = self._user("ia@example.test", EdifyRole.IMPACT_ASSESSMENT.value)
        self.cceo = self._user("cceo@example.test", EdifyRole.CCEO.value)
        self.pl = self._user("pl@example.test", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.accountant = self._user(
            "accountant@example.test", EdifyRole.PROGRAM_ACCOUNTANT.value
        )

        self.cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.pl_staff = StaffProfile.objects.create(user=self.pl, title="PL")
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_staff, supervisor=self.pl_staff
        )

        CostSetting.objects.create(
            key="staff_visit_transport_primary", label="Transport", unit_cost=10000
        )
        CostSetting.objects.create(key="lunch", label="Lunch", unit_cost=5000)

    def test_school_to_accountability_workflow(self):
        self._as(self.ia)
        school_upload = self._post(
            "/api/schools/bulk",
            {
                "schools": [
                    {
                        "schoolId": "SMOKE-JUL10-1",
                        "name": "Smoke July 10 Primary",
                        "regionId": self.region.id,
                        "districtId": self.district.id,
                        "subCountyId": self.sub_county.id,
                        "schoolType": "client",
                        "enrollment": 240,
                    }
                ]
            },
            201,
        )
        self.assertEqual(school_upload["accepted"], 1)
        school = School.objects.get(school_id="SMOKE-JUL10-1")
        StaffSchoolAssignment.objects.create(staff=self.cceo_staff, school_id=school.id)

        ssa = self._post(
            "/api/ssa",
            {
                "schoolId": school.school_id,
                "dateOfSsa": "2026-07-01T09:00:00+03:00",
                "scores": INTERVENTION_SCORES,
            },
            201,
        )
        self.assertEqual(ssa["verificationStatus"], "confirmed")
        school.refresh_from_db()
        self.assertEqual(school.planning_readiness, "ready")

        self._as(self.cceo)
        cluster = self._post(
            "/api/clusters/from-school",
            {
                "schoolId": school.school_id,
                "name": "Smoke July Cluster",
                "clusterType": "mixed",
            },
            201,
        )
        self._post(
            "/api/clusters/assign",
            {"schoolId": school.school_id, "clusterId": cluster["id"]},
            200,
        )

        scheduled = self._post(
            "/api/planning/schedule-school-visit",
            {
                "schoolId": school.school_id,
                "scheduledDate": "2026-07-10T09:00:00+03:00",
                "plannedMonth": 7,
                "plannedWeek": 2,
                "purposeIntervention": "enrolment",
            },
            201,
        )
        activity_id = scheduled["id"]
        self.assertEqual(scheduled["status"], "scheduled")
        self.assertEqual(scheduled["estCostCents"], 15000)

        my_plan = self._get("/api/my-plan?fy=2026&period=month&month=7", 200)
        self.assertEqual(my_plan["total"], 1)
        self.assertEqual(my_plan["items"][0]["id"], activity_id)

        self._post(f"/api/activities/{activity_id}/start-completion", {}, 200)
        evidence = self._upload_evidence(activity_id)

        self._as(self.pl)
        reviewed = self._post(
            f"/api/evidence/{evidence['id']}/review", {"action": "accept"}, 200
        )
        self.assertEqual(reviewed["status"], "accepted")

        self._as(self.cceo)
        completed = self._post(
            f"/api/activities/{activity_id}/complete", {"salesforceId": "SV-JUL10"}, 200
        )
        self.assertEqual(completed["status"], "submitted_to_pl")

        self._as(self.pl)
        queue = self._get("/api/pl/review-queue", 200)
        self.assertTrue(any(row["id"] == activity_id for row in queue))
        pl_confirmed = self._post(
            f"/api/pl/review-queue/{activity_id}/confirm", {}, 200
        )
        self.assertEqual(pl_confirmed["status"], "awaiting_ia_verification")

        self._as(self.ia)
        ia_verified = self._post(f"/api/activities/{activity_id}/ia-confirm", {}, 200)
        self.assertEqual(ia_verified["status"], "ia_verified")
        self.assertEqual(ia_verified["iaVerificationStatus"], "confirmed")

        self._as(self.cceo)
        budget = self._get("/api/budget/from-schedule?fy=2026", 200)
        self.assertEqual(budget["activityCount"], 1)
        self.assertEqual(budget["total"], 15000)
        fund_request = self._post(
            "/api/fund-requests", {"fy": "2026", "period": "monthly", "month": 7}, 201
        )
        self.assertEqual(fund_request["periodKey"], "2026-M7")
        self.assertEqual(fund_request["totalAmount"], 15000)
        self.assertEqual(FundRequestItem.objects.count(), 2)

        self._as(self.pl)
        pl_requests = self._get("/api/fund-requests?fy=2026", 200)
        self.assertTrue(any(row["id"] == fund_request["id"] for row in pl_requests))
        approved = self._post(
            f"/api/fund-requests/{fund_request['id']}/approve",
            {"note": "Looks right"},
            200,
        )
        self.assertEqual(approved["status"], "approved")

        self._as(self.accountant)
        disbursed = self._post(
            f"/api/fund-requests/{fund_request['id']}/disburse",
            {"amount": 15000, "method": "mobile_money", "reference": "MM-JUL10"},
            200,
        )
        self.assertEqual(disbursed["status"], "disbursed")

        self._as(self.cceo)
        accounted = self._post(
            f"/api/fund-requests/{fund_request['id']}/account",
            {"amountSpent": 14000, "amountReturned": 1000, "netsuiteId": "EXP-1001"},
            200,
        )
        self.assertEqual(accounted["accountabilityStatus"], "submitted")

        self._as(self.accountant)
        closed = self._post(
            f"/api/fund-requests/{fund_request['id']}/account-approve", {}, 200
        )
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["accountabilityStatus"], "approved")

        Activity.objects.get(id=activity_id)
        FundRequest.objects.get(id=fund_request["id"])

    def _user(self, email: str, role: str) -> User:
        return User.objects.create_user(
            email=email,
            name=email.split("@")[0].title(),
            roles=[role],
            active_role=role,
            password="not-used",
            is_active=True,
        )

    def _as(self, user: User) -> None:
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}"
        )

    def _get(self, path: str, expected: int):
        response = self.client.get(path)
        self.assertEqual(response.status_code, expected, response.content)
        return response.json()

    def _post(self, path: str, data: dict, expected: int):
        response = self.client.post(path, data, format="json")
        self.assertEqual(response.status_code, expected, response.content)
        return response.json()

    def _upload_evidence(self, activity_id: str) -> dict:
        response = self.client.post(
            "/api/evidence/upload",
            {
                "activityId": activity_id,
                "kind": "visit_form",
                "file": SimpleUploadedFile(
                    "visit-form.pdf",
                    b"%PDF-1.4\n% smoke evidence\n",
                    content_type="application/pdf",
                ),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()
