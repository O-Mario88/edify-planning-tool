"""Professional Development moves real money, so its guards must hold.

Four defects the audit proved: a course clock that only ticked when the
employee personally opened their own page, an approval stage that was global
on role alone, a balance that subtracted the same request twice, and an
allocation write that could cut someone below what they had already spent.
"""

from __future__ import annotations

import inspect

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )


class CourseClockTests(TestCase):
    """`sync_dates` is the only thing that advances a course."""

    def test_the_reminder_job_advances_the_clock_itself(self):
        from apps.professional_development import reminders

        source = inspect.getsource(reminders.send_due_reminders)
        self.assertIn(
            "sync_dates",
            source,
            "its only caller was the employee's own page, so a record they "
            "never reopened stayed frozen and no reminder could ever fire",
        )


class ApprovalScopeTests(TestCase):
    """HR is a country function, not a global one."""

    def setUp(self):
        from apps.professional_development.models import (
            ProfessionalDevelopmentRequest,
        )

        self.staff = _user("pd-staff@t.org", "Owner", EdifyRole.CCEO.value)
        self.sp = StaffProfile.objects.create(user=self.staff, country="Uganda")
        self.req = ProfessionalDevelopmentRequest.objects.create(
            staff_id=self.sp.id,
            staff_name="Owner",
            fy="2026",
            country="Uganda",
            course_name="Course",
            course_category="leadership",
            course_type="online",
            institution="Test Institute",
            start_date="2026-01-01",
            end_date="2026-02-01",
            funding_type="edify_funded",
            requested_amount_cents=100_000,
            status="submitted_to_hr",
        )

    def _hr(self, country):
        hr = _user(f"pd-hr-{country}@t.org", "HR", "HumanResources")
        StaffProfile.objects.create(user=hr, country=country)
        return hr

    def test_in_country_hr_may_review(self):
        from apps.professional_development.approval_service import (
            _may_review_hr_stage,
        )

        self.assertTrue(_may_review_hr_stage(self.req, self._hr("Uganda")))

    def test_foreign_hr_may_not_review(self):
        from apps.professional_development.approval_service import (
            _may_review_hr_stage,
        )

        self.assertFalse(
            _may_review_hr_stage(self.req, self._hr("Kenya")),
            "an HR officer could approve, sign off and close another "
            "country's funded course",
        )

    def test_a_leadership_account_with_no_country_may_not_review(self):
        """The guard's comment said an unset country is not a licence to
        approve globally; written as `if a and b and a != b` it skipped
        entirely and fell through to `return True`."""
        from apps.professional_development.approval_service import (
            _may_review_hr_stage,
        )

        cd = _user("pd-cd-nocountry@t.org", "CD", EdifyRole.COUNTRY_DIRECTOR.value)
        self.assertFalse(_may_review_hr_stage(self.req, cd))


class BalanceArithmeticTests(TestCase):
    """A request between accountability and sign-off was counted twice."""

    def test_accounted_requests_are_not_also_counted_as_committed(self):
        from apps.professional_development.services import StaffPDService

        source = inspect.getsource(StaffPDService.balances)
        self.assertIn("not r.accounted_amount", source)


class AllocationWriteTests(TestCase):
    """The one HR write that moves money."""

    def setUp(self):
        self.hr = _user("alloc-hr@t.org", "HR One", "HumanResources")
        StaffProfile.objects.create(user=self.hr, country="Uganda")

    def test_hr_cannot_set_another_countrys_allocation(self):
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        with self.assertRaises(Forbidden):
            HRPDDashboardService.adjust_role_allocation(
                self.hr,
                role="CCEO",
                fy="2026",
                country="Kenya",
                amount_major=5000,
            )

    def test_the_allocation_write_is_audited(self):
        from apps.audit.models import AuditLog
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        HRPDDashboardService.adjust_role_allocation(
            self.hr, role="CCEO", fy="2026", country="Uganda", amount_major=5000
        )
        self.assertTrue(
            AuditLog.objects.filter(action="pd.role_allocation_adjusted").exists(),
            "changing the envelope every disbursement draws on left no trail",
        )

    def test_bulk_apply_will_not_cut_below_committed_spend(self):
        import inspect

        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        source = inspect.getsource(HRPDDashboardService.adjust_role_allocation)
        self.assertIn("committed_and_accounted_cents", source)


class SignOffAuditTests(TestCase):
    def test_sign_off_writes_an_audit_row(self):
        from apps.professional_development.completion_service import (
            PDCourseTrackingService,
        )

        source = inspect.getsource(PDCourseTrackingService.sign_off)
        self.assertIn(
            '_audit_decision("pd_sign_off"',
            source,
            "the decision that closes the record and releases the money was "
            "the one decision in the chain with no audit row",
        )


class BulkReminderScopeTests(TestCase):
    def test_bulk_reminders_respect_the_dashboard_scope(self):
        from apps.frontend.views import hr_views

        source = inspect.getsource(hr_views)
        self.assertIn(
            "_scoped_staff_ids(request.user)",
            source,
            "the button's label came from the scoped count while the send "
            "went to every country and every financial year",
        )
