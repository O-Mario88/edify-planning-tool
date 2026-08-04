"""A partner can hand an unscheduled assignment back, with a reason.

Before this the partner queue offered Schedule and nothing else. A partner who
could not take the work had two options: schedule a visit that would not
happen, or leave the row sitting there — and the managing staff learnt about it
by noticing the silence.

The rule that matters financially is that returning creates *nothing*: no
Activity, no ActivityBudgetLine, no cost. Assignment already creates no cost
(`test_assignment_stores_catalogue_and_creates_no_activity_or_cost` covers
that); this covers the other exit from the same state, so neither route can
start committing money by accident.

Return is also refused once the assignment has been scheduled, because by then
there IS an Activity with a catalogue-snapshotted cost sitting in a week, month,
quarter and FY budget. Unpicking that is what reschedule, release and
cancellation are for.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner, PartnerAssignment
from apps.partners.services import (
    RETURN_REASON_MAX_LENGTH,
    RETURN_REASON_MIN_LENGTH,
    return_assignment,
)
from apps.schools.models import School

User = get_user_model()

GOOD_REASON = "The school is closed for the whole of that term break."


class _ReturnFixture:
    """Shared setup. Deliberately not a TestCase: subclassing one test class
    from another makes the parent's tests run a second time under the child's
    name, which inflates the count and hides nothing."""

    def setUp(self):
        self.region = Region.objects.create(name="PR Region")
        self.district = District.objects.create(name="PR District", region=self.region)
        self.sub_county = SubCounty.objects.create(
            name="PR Sub", district=self.district
        )
        self.school = School.objects.create(
            school_id="PR-SCH",
            name="PR School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
        )
        self.staff = User.objects.create(
            id="pr-staff",
            email="pr-staff@edify.org",
            name="PR Staff",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.partner_user = User.objects.create(
            id="pr-partner-user",
            email="pr-partner@edify.org",
            name="PR Partner User",
            roles=["Partner"],
            active_role="Partner",
            is_active=True,
        )
        self.partner = Partner.objects.create(
            name="PR Partner Org", user_id=self.partner_user.id
        )
        self.assignment = self._assignment()

    def _assignment(self, **kwargs):
        return PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.staff.id,
            status=PartnerAssignment.STATUS_PENDING_SCHEDULING,
            **kwargs,
        )

    def _return(self, **overrides):
        data = {"reason_category": "school_unavailable", "reason": GOOD_REASON}
        data.update(overrides)
        return return_assignment(self.assignment.id, data, self.partner_user)


class PartnerReturnsAnAssignmentTest(_ReturnFixture, TestCase):
    # ── The financial guarantee ──────────────────────────────────────────────

    def test_returning_creates_no_activity_and_no_cost(self):
        before = Activity.objects.count()
        self._return()
        self.assertEqual(
            Activity.objects.count(),
            before,
            "returning an assignment must not create an Activity",
        )
        self.assertFalse(
            Activity.objects.filter(assigned_partner_id=self.partner.id).exists()
        )

    def test_returning_records_the_reason_and_who_returned_it(self):
        self._return()
        self.assignment.refresh_from_db()
        self.assertEqual(
            self.assignment.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF
        )
        self.assertEqual(self.assignment.return_reason_category, "school_unavailable")
        self.assertEqual(self.assignment.return_reason, GOOD_REASON)
        self.assertEqual(self.assignment.returned_by, self.partner_user.id)
        self.assertIsNotNone(self.assignment.returned_at)

    # ── Reason validation ────────────────────────────────────────────────────

    def test_a_reason_category_is_required(self):
        with self.assertRaises(BadRequest):
            self._return(reason_category="")

    def test_an_invented_category_is_rejected(self):
        with self.assertRaises(BadRequest):
            self._return(reason_category="because_i_said_so")

    def test_whitespace_cannot_buy_the_minimum_length(self):
        # Length is measured on the stripped value, or "   ok   " would pass.
        with self.assertRaises(BadRequest):
            self._return(reason=" " * 40)

    def test_a_too_short_explanation_is_rejected(self):
        with self.assertRaises(BadRequest):
            self._return(reason="x" * (RETURN_REASON_MIN_LENGTH - 1))

    def test_a_too_long_explanation_is_rejected(self):
        with self.assertRaises(BadRequest):
            self._return(reason="x" * (RETURN_REASON_MAX_LENGTH + 1))

    def test_a_rejected_return_leaves_the_assignment_untouched(self):
        with self.assertRaises(BadRequest):
            self._return(reason="too short")
        self.assignment.refresh_from_db()
        self.assertEqual(
            self.assignment.status, PartnerAssignment.STATUS_PENDING_SCHEDULING
        )
        self.assertIsNone(self.assignment.returned_at)

    # ── State and scope ──────────────────────────────────────────────────────

    def test_a_scheduled_assignment_cannot_be_returned(self):
        self.assignment.status = PartnerAssignment.STATUS_SCHEDULED
        self.assignment.save(update_fields=["status"])
        with self.assertRaises(ConflictError):
            self._return()

    def test_returning_twice_is_idempotent(self):
        first = self._return()
        second = self._return()
        self.assertEqual(first["status"], second["status"])
        self.assignment.refresh_from_db()
        # The second call must not overwrite the original decision.
        self.assertEqual(self.assignment.return_reason, GOOD_REASON)

    def test_another_partner_cannot_return_this_assignment(self):
        other_user = User.objects.create(
            id="pr-other-user",
            email="pr-other@edify.org",
            name="Other Partner",
            roles=["Partner"],
            active_role="Partner",
            is_active=True,
        )
        Partner.objects.create(name="Other Org", user_id=other_user.id)
        with self.assertRaises(NotFoundError):
            return_assignment(
                self.assignment.id,
                {"reason_category": "capacity", "reason": GOOD_REASON},
                other_user,
            )
        self.assignment.refresh_from_db()
        self.assertEqual(
            self.assignment.status, PartnerAssignment.STATUS_PENDING_SCHEDULING
        )

    def test_a_non_partner_cannot_return_an_assignment(self):
        with self.assertRaises(Forbidden):
            return_assignment(
                self.assignment.id,
                {"reason_category": "capacity", "reason": GOOD_REASON},
                self.staff,
            )


class ReturnedAssignmentReachesTheStaffQueueTest(_ReturnFixture, TestCase):
    """The reason has to arrive somewhere the staff member will see it."""

    def test_a_returned_assignment_becomes_a_staff_todo(self):
        from apps.command_center.todo_service import _returned_assignment_todos
        from apps.core.scoping import resolve_user_scope
        from django.utils import timezone

        self._return()
        todos = _returned_assignment_todos(
            self.staff, resolve_user_scope(self.staff), timezone.now().date()
        )
        self.assertEqual(len(todos), 1, "the assigning staff member must get a To-Do")
        self.assertIn("School unavailable", todos[0]["description"])
        self.assertIn(GOOD_REASON[:30], todos[0]["description"])

    def test_the_todo_closes_itself_when_the_assignment_moves_on(self):
        # To-Dos are derived from workflow state, not stored, so reassigning or
        # cancelling must clear this without anyone remembering to delete it.
        from apps.command_center.todo_service import _returned_assignment_todos
        from apps.core.scoping import resolve_user_scope
        from django.utils import timezone

        self._return()
        self.assignment.status = PartnerAssignment.STATUS_SCHEDULED
        self.assignment.save(update_fields=["status"])
        todos = _returned_assignment_todos(
            self.staff, resolve_user_scope(self.staff), timezone.now().date()
        )
        self.assertEqual(todos, [])

    def test_an_audit_event_records_the_return(self):
        from apps.audit.models import AuditLog

        self._return()
        self.assertTrue(
            AuditLog.objects.filter(
                action="partner.assignment_returned",
                subject_id=self.assignment.id,
            ).exists()
        )
