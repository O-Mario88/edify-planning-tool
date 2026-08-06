"""Regression test: attendance and SSA evidence uploads must use real
EvidenceKind enum members. Both attendance_upload_action and
ssa_evidence_upload_action previously passed kind="attendance_sheet" /
kind="ssa_form" -- neither is a member of apps.core.enums.EvidenceKind, so
apps.evidence.services.record_upload always raised BadRequest and both
upload flows failed in production.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.evidence.models import EvidenceRecord
from apps.geography.models import Region, District
from apps.schools.models import School

User = get_user_model()


class AttendanceAndSsaUploadKindTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            id="cceo-evidence-kind-fix",
            email="cceo-evidence-kind-fix@edify.org",
            name="CCEO Evidence Kind Fix",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.user.set_password("pass123")
        self.user.save()
        profile = StaffProfile.objects.create(
            id="staff-cceo-evidence-kind-fix", user=self.user, title="CCEO"
        )
        region = Region.objects.create(name="Central Region")
        district = District.objects.create(name="Kampala", region=region)
        self.school = School.objects.create(
            name="Test School", region=region, district=district
        )
        # A real CCEO reaches these views via an assigned school portfolio
        # (apps.core.scoping resolves scope.school_ids from
        # StaffSchoolAssignment) -- both the view-level can_view_record()
        # check and the service-level _assert_activity_in_scope() check
        # agree once the activity's school is in that portfolio.
        StaffSchoolAssignment.objects.create(staff=profile, school_id=self.school.id)
        self.activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="cluster_training",
            status="in_progress",
            # apps/evidence/services.py::_assert_activity_in_scope resolves
            # scope via apps.core.scoping (staff_id = user.staff_profile_id,
            # the StaffProfile CUID) -- the dominant id space per project
            # convention -- unlike the view-level can_view_record() check,
            # which tolerates the raw User id as a profile-less fallback.
            responsible_staff_id=self.user.staff_profile_id,
            planned_date=date(2026, 7, 10),
        )
        self.client.force_login(self.user)

    def _jpeg(self, name):
        return SimpleUploadedFile(
            name, b"\xff\xd8\xff" + b"0" * 32, content_type="image/jpeg"
        )

    def test_attendance_upload_succeeds_and_records_attendance_form_kind(self):
        response = self.client.post(
            f"/activities/{self.activity.id}/attendance/action",
            {
                "teachers_attended": "5",
                "leaders_attended": "1",
                "attendance_file": self._jpeg("attendance.jpg"),
            },
        )
        self.assertIn(response.status_code, (200, 302))
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.evidence_status, "uploaded")
        record = EvidenceRecord.objects.filter(activity_id=self.activity.id).latest(
            "created_at"
        )
        self.assertEqual(record.kind, "attendance_form")

    def test_ssa_upload_succeeds_and_records_assessment_form_kind(self):
        response = self.client.post(
            f"/activities/{self.activity.id}/ssa-upload/action",
            {"ssa_file": self._jpeg("ssa.jpg")},
        )
        self.assertIn(response.status_code, (200, 302))
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.evidence_status, "uploaded")
        record = EvidenceRecord.objects.filter(activity_id=self.activity.id).latest(
            "created_at"
        )
        self.assertEqual(record.kind, "assessment_form")
