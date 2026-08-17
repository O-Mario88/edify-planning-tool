"""An unverified SSA upload must not satisfy a verification gate.

``apps.ssa.services.latest_applicable_record`` exists precisely so that "the
latest SSA" means the latest *confirmed* one on every decision surface -- its
docstring puts it plainly: an unverified upload must never gate, justify, or
rank money-bearing work.

Two live gates read the SSA table directly instead and filtered only on
``deleted_at__isnull=True``:

  * ``apps.activities.services.ia_confirm`` -- the Core-school assessment
    check, which decides whether an activity may advance to ``ia_verified``.
  * ``apps.activities.ia_services.SSAValidationService.validate_ssa`` -- which
    feeds the ``ssa_uploaded`` / ``analytics_ready`` signals in the live IA
    workspace.

So a partner-collected upload sitting at ``pending`` -- data nobody has
verified -- satisfied both. Verification is the control that turns claimed
work into credited work, and an unverified score is exactly the input it is
supposed to be sceptical of. These tests pin the confirmed-only rule at both
doors; both fail if either gate goes back to reading the raw table.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.ia_services import SSAValidationService
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord


class UnconfirmedSsaFailsVerificationGates(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Gate Region")
        cls.district = District.objects.create(
            name="Gate District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="GATE-001",
            name="Gate Core School",
            region=cls.region,
            district=cls.district,
            school_type="core",
            enrollment=200,
        )
        cls.ia_user = User.objects.create_user(
            email="gate-ia@edify.org",
            name="Gate IA",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(
            user=cls.ia_user, staff_number="ST-GATE-IA", country="Uganda"
        )

    def _pending_record(self):
        """The only SSA this school has is one nobody has verified."""
        return SsaRecord.objects.create(
            school=self.school,
            fy=get_operational_fy(),
            date_of_ssa=timezone.localdate() - datetime.timedelta(days=10),
            verification_status="pending",
        )

    def _core_activity(self):
        activity = Activity.objects.create(
            school=self.school,
            activity_type="core_visit",
            status="awaiting_ia_verification",
            fy=get_operational_fy(),
            planned_date=timezone.localdate() - datetime.timedelta(days=5),
            focus_intervention="leadership",
            salesforce_activity_id="SVE-GATE-001",
            responsible_staff_id=str(self.ia_user.id),
            ssa_collection_expected=True,
        )
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="photo",
            uri="gate-evidence.jpg",
            uploaded_by=str(self.ia_user.id),
            quarantined=False,
        )
        return activity

    def test_validate_ssa_rejects_an_unconfirmed_upload(self):
        activity = self._core_activity()
        self._pending_record()

        ok, message = SSAValidationService.validate_ssa(activity)

        self.assertFalse(
            ok,
            "A pending SSA upload satisfied the IA workspace SSA check. Only "
            "confirmed records may satisfy a verification gate.",
        )
        self.assertIn("confirmed", message.lower())

    def test_validate_ssa_accepts_a_confirmed_record(self):
        """The gate must still pass on real data -- otherwise the test above
        would also pass with the check hard-wired to False."""
        activity = self._core_activity()
        SsaRecord.objects.create(
            school=self.school,
            fy=get_operational_fy(),
            date_of_ssa=timezone.localdate() - datetime.timedelta(days=10),
            verification_status="confirmed",
        )

        ok, _message = SSAValidationService.validate_ssa(activity)

        self.assertTrue(ok)

    def test_ia_confirm_refuses_a_core_school_with_only_pending_ssa(self):
        from apps.activities import services

        activity = self._core_activity()
        self._pending_record()

        with self.assertRaises(BadRequest) as caught:
            services.ia_confirm(str(activity.id), {}, self.ia_user)

        self.assertIn("confirmed", str(caught.exception).lower())
        activity.refresh_from_db()
        self.assertEqual(
            activity.status,
            "awaiting_ia_verification",
            "The activity advanced past IA verification on unconfirmed data.",
        )
