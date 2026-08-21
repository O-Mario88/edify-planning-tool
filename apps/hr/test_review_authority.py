"""Who may review whom (2026-08-20 HR audit).

The organisation's rule: Program Leads review the CCEOs they supervise; the
Country Director reviews Program Leads, Impact Assessment and the Accountant;
HR oversees the cycle and conducts none of it.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
    User,
)
from apps.core.exceptions import Forbidden
from apps.hr.review_authority import (
    assert_reviewer,
    is_oversight,
    is_reviewer_of,
    reviewer_for,
    reviewees_of,
)


def _staff(role, email, *, state="active"):
    user = User.objects.create_user(
        email=email,
        password="pw",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )
    return user, StaffProfile.objects.create(
        user=user, title=role, country="Uganda", onboarding_state=state
    )


class ReviewAuthorityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd, cls.cd_sp = _staff("CountryDirector", "cd@ra.test")
        cls.pl, cls.pl_sp = _staff("Program Lead", "pl@ra.test")
        cls.pl2, cls.pl2_sp = _staff("Program Lead", "pl2@ra.test")
        cls.cceo, cls.cceo_sp = _staff("CCEO", "cceo@ra.test")
        cls.ia, cls.ia_sp = _staff("ImpactAssessment", "ia@ra.test")
        cls.acct, cls.acct_sp = _staff("Accountant", "acct@ra.test")
        cls.hr, cls.hr_sp = _staff("HumanResources", "hr@ra.test")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo_sp, supervisor=cls.pl_sp
        )
        for sp in (cls.pl_sp, cls.pl2_sp, cls.ia_sp, cls.acct_sp):
            StaffSupervisorAssignment.objects.create(
                supervisee=sp, supervisor=cls.cd_sp
            )

    def test_the_program_lead_reviews_their_own_cceo(self):
        self.assertEqual(reviewer_for(self.cceo_sp).id, self.pl_sp.id)
        self.assertTrue(is_reviewer_of(self.cceo_sp, self.pl))

    def test_another_program_lead_may_not(self):
        self.assertFalse(is_reviewer_of(self.cceo_sp, self.pl2))

    def test_the_country_director_reviews_pl_ia_and_accountant(self):
        for profile in (self.pl_sp, self.ia_sp, self.acct_sp):
            self.assertEqual(reviewer_for(profile).id, self.cd_sp.id)
            self.assertTrue(is_reviewer_of(profile, self.cd))

    def test_hr_oversees_and_never_conducts(self):
        self.assertTrue(is_oversight(self.hr))
        self.assertFalse(is_reviewer_of(self.cceo_sp, self.hr))
        with self.assertRaises(Forbidden) as caught:
            assert_reviewer(self.cceo_sp, self.hr)
        # The refusal must point at the manager, not just say no.
        self.assertIn("Return the review", str(caught.exception))

    def test_nobody_reviews_themselves(self):
        self.assertFalse(is_reviewer_of(self.cceo_sp, self.cceo))
        self.assertFalse(is_reviewer_of(self.cd_sp, self.cd))

    def test_a_former_manager_loses_authority_the_moment_the_line_moves(self):
        """The defect this closes: `PerformanceReview.manager` was stamped once
        at cycle open and never updated, so the manager an employee had LEFT
        kept rating them for the rest of the year."""
        self.assertTrue(is_reviewer_of(self.cceo_sp, self.pl))
        StaffSupervisorAssignment.objects.filter(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        ).delete()
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl2_sp
        )
        self.assertFalse(is_reviewer_of(self.cceo_sp, self.pl))
        self.assertTrue(is_reviewer_of(self.cceo_sp, self.pl2))

    def test_an_oversight_row_is_not_the_reporting_line(self):
        """An IA or RVP link is oversight, not line management — it used to
        satisfy every 'is this their manager?' check in the engine."""
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.ia_sp
        )
        self.assertFalse(is_reviewer_of(self.cceo_sp, self.ia))
        self.assertEqual(reviewer_for(self.cceo_sp).id, self.pl_sp.id)

    def test_a_suspended_manager_holds_nothing(self):
        self.pl_sp.onboarding_state = "suspended"
        self.pl_sp.save(update_fields=["onboarding_state"])
        self.assertFalse(is_reviewer_of(self.cceo_sp, self.pl))
        self.assertIsNone(reviewer_for(self.cceo_sp))

    def test_a_deactivated_manager_holds_nothing(self):
        self.pl.is_active = False
        self.pl.save(update_fields=["is_active"])
        self.assertIsNone(reviewer_for(self.cceo_sp))

    def test_authority_moves_to_an_active_cover_and_only_for_its_window(self):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        leave = self._leave_for(self.pl_sp)
        coverage = TemporaryCoverageAssignment.objects.create(
            leave_request=leave,
            original_staff=self.pl_sp,
            covering_staff=self.pl2_sp,
            start_datetime=now - timedelta(days=1),
            end_datetime=now + timedelta(days=1),
            status="active",
        )
        self.assertTrue(is_reviewer_of(self.cceo_sp, self.pl2))

        coverage.end_datetime = now - timedelta(hours=1)
        coverage.save(update_fields=["end_datetime"])
        self.assertFalse(is_reviewer_of(self.cceo_sp, self.pl2))

    def test_reviewees_lists_only_the_people_this_role_reviews(self):
        pl_reviewees = set(reviewees_of(self.pl).values_list("id", flat=True))
        self.assertEqual(pl_reviewees, {self.cceo_sp.id})
        cd_reviewees = set(reviewees_of(self.cd).values_list("id", flat=True))
        self.assertEqual(
            cd_reviewees,
            {self.pl_sp.id, self.pl2_sp.id, self.ia_sp.id, self.acct_sp.id},
        )
        self.assertEqual(list(reviewees_of(self.hr)), [])

    def _leave_for(self, profile):
        from apps.accounts.models import Leave

        return Leave.objects.create(
            staff=profile,
            type="personal_time_off",
            start_date="2026-09-01",
            end_date="2026-09-05",
            days=5,
            days_charged=5,
            status="approved",
        )
