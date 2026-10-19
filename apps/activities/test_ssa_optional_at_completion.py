"""The SSA is optional at completion; the Salesforce ID is not (owner,
2026-10-19).

"Adding SSA scores can be optional but Salesforce ID is A MUST." A visit
planned to collect the SSA completes with its Salesforce ID whether or not
the scores, or a reason none were taken, are recorded. Scores the officer does
enter are kept as before. Without the Salesforce ID nothing completes.

Pinned here, at every door completion has: the service (`complete`), the
staged Submit (`submit_for_review`), the Complete drawer, and the My Plan
action that offers Submit.
"""

from __future__ import annotations

import datetime

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities import services
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="SSA-OPT Region")
        cls.district = District.objects.create(
            name="SSA-OPT District", region=cls.region, district_type="primary"
        )
        cls.cceo = User.objects.create_user(
            email="ssa-opt-cceo@edify.org",
            name="SSA-OPT CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.cceo_staff = StaffProfile.objects.create(
            user=cls.cceo, staff_number="ST-SSA-OPT", country="Uganda"
        )
        cls.school = School.objects.create(
            school_id="SSA-OPT-001",
            name="SSA-OPT School",
            region=cls.region,
            district=cls.district,
            school_type="client",
            account_owner_id=cls.cceo_staff.id,
            enrollment=200,
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo_staff, school_id=cls.school.id
        )

    def setUp(self):
        case = self.id().rsplit(".", 1)[-1].replace("_", "-").upper()
        self.sf_id = f"SVE-OPT-{case[:40]}"

    def _visit(self, *, status="completion_started", sf=None) -> Activity:
        day = timezone.localdate() - datetime.timedelta(days=2)
        return Activity.objects.create(
            school=self.school,
            activity_type="school_visit_ssa_collection",
            purpose_type="ssa_support",
            status=status,
            fy=get_operational_fy(),
            planned_date=day,
            actual_delivery_date=day,
            salesforce_activity_id=sf,
            responsible_staff_id=str(self.cceo_staff.id),
            ssa_collection_expected=True,
        )


class TheServiceCompletesWithoutTheSsa(_Fixture):
    def test_the_salesforce_id_alone_completes_it(self):
        visit = self._visit()
        services.complete(visit.id, {"salesforceId": self.sf_id}, self.cceo)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "submitted_to_pl")
        self.assertEqual(visit.salesforce_activity_id, self.sf_id)
        self.assertFalse(SsaRecord.objects.filter(school=self.school).exists())

    def test_without_the_salesforce_id_nothing_completes(self):
        visit = self._visit()
        with self.assertRaises(BadRequest):
            services.complete(
                visit.id,
                {"ssaNotCollectedReason": "School closed for a funeral."},
                self.cceo,
            )
        visit.refresh_from_db()
        self.assertEqual(visit.status, "completion_started")

    def test_submit_hands_it_in_without_the_ssa(self):
        visit = self._visit(sf=self.sf_id)
        services.submit_for_review(visit.id, self.cceo)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "submitted_to_pl")

    def test_submit_still_needs_the_salesforce_id(self):
        visit = self._visit()
        with self.assertRaises(BadRequest):
            services.submit_for_review(visit.id, self.cceo)


class TheCompleteDrawer(_Fixture):
    def _post(self, visit, **fields):
        client = Client()
        client.force_login(self.cceo)
        return client.post(
            f"/my-plan/{visit.id}/complete",
            {
                "salesforce_id": self.sf_id,
                "actual_delivery_date": visit.planned_date.isoformat(),
                **fields,
            },
            headers={"HX-Request": "true"},
        )

    def test_not_collected_needs_no_reason(self):
        visit = self._visit()
        response = self._post(visit, ssa_collected="no")
        self.assertNotIn(b"reason why SSA", response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "submitted_to_pl")

    def test_leaving_the_scores_blank_completes_it(self):
        visit = self._visit()
        self._post(visit, ssa_collected="yes")
        visit.refresh_from_db()
        self.assertEqual(visit.status, "submitted_to_pl")
        self.assertFalse(SsaRecord.objects.filter(school=self.school).exists())

    def test_a_part_filled_score_sheet_is_still_refused(self):
        visit = self._visit()
        response = self._post(visit, ssa_collected="yes", score_leadership="6")
        self.assertIn(b"Missing score", response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "completion_started")

    def test_without_the_salesforce_id_it_is_refused(self):
        visit = self._visit()
        response = self._post(visit, ssa_collected="no", salesforce_id="")
        self.assertGreaterEqual(response.status_code, 400)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "completion_started")


class MyPlanOffersSubmit(_Fixture):
    def test_submit_is_offered_once_the_id_is_in_whatever_the_ssa(self):
        from apps.my_plan.services import compute_next_action

        # A staged row with its ID in: Submit used to wait for the school's SSA.
        visit = self._visit(status="completed", sf=self.sf_id)
        action = compute_next_action(visit, timezone.localdate())
        self.assertEqual(action["action"], "submit")
