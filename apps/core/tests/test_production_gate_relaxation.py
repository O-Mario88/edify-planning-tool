"""The four production business rules that switch themselves OFF under test.

apps/ssa/services.py and apps/activities/services.py each detect the test
runner (`"test" in sys.argv or "pytest" in sys.modules`) and skip a real
production gate. That means the suite's green status did not, on its own,
say anything about whether those gates work — and one of them
(submit_for_review's per-activity-type evidence requirement) had no opt-in
flag at all, so it could never be exercised by any test.

These tests turn each gate ON explicitly and assert it actually fires, so a
regression in the underlying rule is caught rather than silently skipped.
"""

from __future__ import annotations

import datetime

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord


class ProductionGateRelaxationTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Gate Region")
        self.district = District.objects.create(
            name="Gate District", region=self.region, district_type="primary"
        )
        self.school = School.objects.create(
            school_id="GATE-1",
            name="Gate Primary",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        self.user = User.objects.create_user(
            email="gate-cceo@edify.test",
            name="Gate CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.user, title="CCEO")
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)

    # ── Gate 1: apps/ssa/services.py — SSA sequence rule ──────────────────
    def test_ssa_sequence_rule_fires_when_enforced(self):
        """Current-FY SSA may not be uploaded while an UNVERIFIED prior-FY
        record exists for the school. Skipped under test unless
        ENFORCE_SSA_SEQUENCE=true, so it needs an explicit exercise."""
        import os

        from apps.core.fy import get_operational_fy
        from apps.ssa.services import upload as ssa_upload

        current_fy = get_operational_fy()
        prev_fy = str(int(current_fy) - 1)

        # An unverified prior-FY record: present, but not confirmed.
        SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=datetime.datetime(
                int(prev_fy) - 1, 11, 1, tzinfo=datetime.timezone.utc
            ),
            fy=prev_fy,
            quarter="Q1",
            average_score=5.0,
            uploaded_by=self.user.id,
            verification_status="pending",
        )

        payload = {
            "schoolId": self.school.school_id,
            "dateOfSsa": f"{int(current_fy) - 1}-11-15",
            "scores": [
                {"intervention": i, "score": 6.0}
                for i in [
                    "christlike_behaviour",
                    "exposure_to_word_of_god",
                    "financial_health",
                    "leadership",
                    "government_requirement",
                    "learning_environment",
                    "teaching_environment",
                    "enrolment",
                ]
            ],
        }

        os.environ["ENFORCE_SSA_SEQUENCE"] = "true"
        try:
            with self.assertRaises(BadRequest) as ctx:
                ssa_upload(payload, self.user)
            self.assertIn("not verified", str(ctx.exception.detail))
        finally:
            os.environ.pop("ENFORCE_SSA_SEQUENCE", None)

    # ── Gate 2: purpose/focus on create() — DELIBERATELY NOT ENFORCED ──────
    #
    # This assertion and its training sibling were leftovers. Commit b4fc9570
    # removed the purpose gate from create() on purpose: in the same change it
    # rewrote test_visit_creation_validation into
    # test_visit_creation_allows_optional_purpose_and_focus, stripped its
    # assertRaises, and left the comment "Purpose and focus help reporting, but
    # they no longer block a visit". It then added this file, asserting the
    # opposite, so the repository shipped two tests contradicting each other.
    #
    # The permissive behaviour is the decision; this now records it. If purpose
    # ever needs to become a hard gate again, restore the block in
    # apps/activities/services.py::create() AND update the other test —
    # changing one without the other is exactly how the contradiction arose.
    def test_purpose_and_focus_are_reporting_metadata_not_a_gate(self):
        from apps.activities.services import create

        result = create(
            {
                "activityType": "school_visit",
                "schoolId": self.school.school_id,
                "scheduledDate": "2026-08-11",  # a Tuesday: REG-02 still applies
                "strict_validation": True,
            },
            self.user,
        )
        self.assertIsNotNone(result["id"])
        self.assertIsNone(result["activityPurposeText"])

    def test_training_purpose_is_also_metadata_not_a_gate(self):
        """Same decision as above, for the training branch."""
        from apps.activities.services import create

        result = create(
            {
                "activityType": "school_improvement_training",
                "schoolId": self.school.school_id,
                "scheduledDate": "2026-08-11",
                "expectedParticipants": 10,
                "strict_validation": True,
            },
            self.user,
        )
        self.assertIsNotNone(result["id"])

    # ── Gates 3 & 4: per-activity-type evidence requirements ───────────────
    def _activity_with_generic_evidence(self):
        """An activity holding one non-quarantined file of the WRONG kind —
        enough to satisfy the baseline any-file rule, but not the
        per-activity-type requirement (a school_visit needs a VISIT_FORM)."""
        from apps.evidence.models import EvidenceRecord

        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            status="completion_started",
            responsible_staff_id=self.staff.id,
            delivery_type="staff",
            fy="2026",
            quarter="Q4",
            planned_date=datetime.date(2026, 8, 11),
            salesforce_activity_id="SVE-GATE-1",
        )
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="photo",  # not the required VISIT_FORM
            quarantined=False,
            uri="snapshot.jpg",
            original_name="snapshot.jpg",
            uploaded_by=self.user.id,
        )
        return activity

    def test_complete_evidence_requirement_fires_when_strict(self):
        from apps.activities.services import complete

        activity = self._activity_with_generic_evidence()
        with self.assertRaises(BadRequest) as ctx:
            complete(
                activity.id,
                {"salesforceId": "SVE-GATE-1", "strict_validation": True},
                self.user,
            )
        self.assertIn("Required evidence missing", str(ctx.exception.detail))

    def test_submit_for_review_evidence_requirement_fires_when_strict(self):
        """This gate had NO opt-in flag before, so no test could reach it."""
        from apps.activities.services import submit_for_review

        activity = self._activity_with_generic_evidence()
        with self.assertRaises(BadRequest) as ctx:
            submit_for_review(activity.id, self.user, {"strict_validation": True})
        self.assertIn("Required evidence missing", str(ctx.exception.detail))
