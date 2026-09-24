"""Nobody accepts the evidence on their own work.

`evidence.review` is held by field officers, because they review the partner
evidence on work they monitor. The review itself checked only scope, so an
officer could accept the evidence on their own activity through
``POST /api/evidence/<id>/review`` — a self-decision the lead's review queue
and IA certification both refuse (2026-09-24 audit).
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.evidence import services
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.schools.models import School


def _staff(email, role):
    user = User.objects.create(
        email=email,
        name=email.split("@")[0],
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )
    return user, StaffProfile.objects.create(user=user, title=role.value)


class EvidenceSelfReviewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Self Review Region")
        district = District.objects.create(name="Self Review District", region=region)
        school = School.objects.create(
            school_id="SELF-1", name="Self Primary", region=region, district=district
        )
        cls.officer_user, officer = _staff("self-cceo@t.test", EdifyRole.CCEO)
        cls.lead_user, lead = _staff("self-pl@t.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        StaffSupervisorAssignment.objects.create(supervisee=officer, supervisor=lead)
        StaffSchoolAssignment.objects.create(staff=officer, school_id=school.id)
        activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="completion_started",
            fy="2026",
            school=school,
            responsible_staff_id=officer.id,
            planned_date=date.today(),
        )
        cls.record = EvidenceRecord.objects.create(
            activity=activity,
            kind="photo",
            uri="self-review.png",
            uploaded_by=cls.officer_user.id,
        )

    def test_the_officer_cannot_accept_their_own_evidence(self):
        with self.assertRaises(Forbidden):
            services.review(self.record.id, {"action": "accept"}, self.officer_user)
        self.record.refresh_from_db()
        self.assertNotEqual(self.record.status, "accepted")
        self.assertNotEqual(self.record.activity.evidence_status, "accepted")

    def test_their_lead_still_reviews_it(self):
        reviewed = services.review(self.record.id, {"action": "accept"}, self.lead_user)
        self.assertEqual(reviewed["status"], "accepted")
