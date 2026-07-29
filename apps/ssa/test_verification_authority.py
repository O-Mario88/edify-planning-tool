"""SSA verification is Impact Assessment's, and it lives in one place.

`ssa_views.py` used to write `verification_status = CONFIRMED` inline. The view
did check the permission first, so this was never an open door — but a
transition written in a view is a transition every other caller can perform
without the authority check, the readiness recompute or the audit row, and
those three are what make a confirmation mean anything.

Section 35: official SSA verification must require IA authority and must not
follow from a role merely being able to open the page.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.enums import VerificationStatus
from apps.core.exceptions import Forbidden
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord
from apps.ssa.services import return_record, verify_record


def _user(key, role):
    return User.objects.create(
        id=f"ssaver-{key}"[:30],
        email=f"ssaver-{key}@edify.org",
        name=f"SSA {key}",
        roles=[role],
        active_role=role,
        is_active=True,
    )


class SsaVerificationAuthorityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ia = _user("ia", "ImpactAssessment")
        cls.cceo = _user("cceo", "CCEO")
        cls.cd = _user("cd", "CountryDirector")
        cls.admin = _user("admin", "Admin")
        region = Region.objects.create(name="Verify Region")
        district = District.objects.create(name="Verify District", region=region)
        cls.school = School.objects.create(
            school_id="SCH-VERIFY-1",
            name="Verify Primary",
            region=region,
            district=district,
        )

    def _record(self):
        return SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=date.today(),
            fy="2026",
            verification_status=VerificationStatus.PENDING.value,
        )

    def test_impact_assessment_may_confirm(self):
        record = verify_record(self._record(), self.ia)
        self.assertEqual(record.verification_status, VerificationStatus.CONFIRMED.value)
        self.assertIsNotNone(record.verified_at)

    def test_nobody_else_may_confirm_however_senior(self):
        """Seniority is not IA authority — the CD leads, IA verifies."""
        for actor in (self.cceo, self.cd, self.admin):
            with self.subTest(role=actor.active_role):
                record = self._record()
                with self.assertRaises(Forbidden):
                    verify_record(record, actor)
                record.refresh_from_db()
                self.assertEqual(
                    record.verification_status, VerificationStatus.PENDING.value
                )

    def test_nobody_else_may_return_either(self):
        for actor in (self.cceo, self.cd, self.admin):
            with self.subTest(role=actor.active_role):
                with self.assertRaises(Forbidden):
                    return_record(self._record(), actor)

    def test_confirming_writes_an_audit_row(self):
        record = verify_record(self._record(), self.ia)
        self.assertTrue(
            AuditLog.objects.filter(action="ssa_verify", subject_id=record.id).exists()
        )

    def test_returning_writes_an_audit_row_with_the_reason(self):
        record = return_record(self._record(), self.ia, "Scores look transposed.")
        row = AuditLog.objects.filter(action="ssa_return", subject_id=record.id).first()
        self.assertIsNotNone(row)
        self.assertIn("transposed", row.reason or "")

    def test_confirming_twice_writes_one_audit_row(self):
        """A double-submitted form must not re-confirm or double-audit."""
        record = self._record()
        verify_record(record, self.ia)
        verify_record(record, self.ia)
        self.assertEqual(
            AuditLog.objects.filter(action="ssa_verify", subject_id=record.id).count(),
            1,
        )

    def test_the_view_no_longer_writes_the_field_itself(self):
        """The regression this guards: the transition moving back into a view."""
        import inspect

        from apps.frontend.views import ssa_views

        source = inspect.getsource(ssa_views)
        self.assertNotIn("verification_status = VerificationStatus.CONFIRMED", source)
        self.assertNotIn("verification_status = VerificationStatus.RETURNED", source)
        self.assertIn("verify_record", source)
