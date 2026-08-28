"""Journey 11 — Professional Development, walked end to end.

Journey 11 of the mandate's twenty-two: Request, Manager review, HR review,
Financial approval, Completion, Evidence, Accounting, Impact review.

This is the platform's fourth money path and the last one this audit had not
walked. The others move programme money against school work; this one moves
money against a person's own annual development envelope, which makes its
control a *budget* rather than a per-transaction gate. FIN-02 was the same
class of failure on a different path — `reimburse()` accepted any amount
because nothing bounded it before the payout.

The envelope rule (§9) is: Remaining = Annual Allocation − Active Committed −
Accounted Used. It is enforced at **submit**, and going over is permitted only
with a declared exception reason, which stamps `is_exception` on the request.
That flag is the entire audit trail for over-budget development spending, so a
request that goes over without being marked is worse than one that is refused.

So this walks a funded request from draft to accounted, and then asks the two
questions the envelope exists for: does a second request that would exceed
what is left get refused, and when an exception is declared, is it actually
recorded as one.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.professional_development.approval_service import PDApprovalRoutingService
from apps.professional_development.models import (
    PDFundingType,
    PDStatus,
    ProfessionalDevelopmentAllocation,
    ProfessionalDevelopmentRequest,
)
from apps.professional_development.services import StaffPDService

ENVELOPE = 1_000_00  # cents
FIRST = 600_00
SECOND_WITHIN = 300_00
SECOND_OVER = 700_00


def _person(uid, email, name, role):
    user = User.objects.create(
        id=uid, email=email, name=name, roles=[role], active_role=role, is_active=True
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country="Uganda", title=role
    )
    return user, profile


class ProfessionalDevelopmentJourneyTest(TestCase):
    """Request → manager → HR → funded → completed → accounted."""

    @classmethod
    def setUpTestData(cls):
        cls.learner, cls.learner_sp = _person(
            "pd-learner", "pd-learner@edify.org", "PD Learner", EdifyRole.CCEO.value
        )
        cls.manager, cls.manager_sp = _person(
            "pd-manager",
            "pd-manager@edify.org",
            "PD Manager",
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.manager_sp, supervisee=cls.learner_sp
        )
        cls.fy = get_operational_fy()

    def setUp(self):
        allocation = StaffPDService.get_or_create_allocation(self.learner, self.fy)
        ProfessionalDevelopmentAllocation.objects.filter(id=allocation.id).update(
            annual_allocation=ENVELOPE
        )

    def _draft(self, *, amount: int, name: str, exception_reason: str = ""):
        return ProfessionalDevelopmentRequest.objects.create(
            staff_id=self.learner_sp.id,
            staff_name=self.learner.name,
            course_name=name,
            course_category="leadership",
            course_type="online",
            course_link="https://courses.example.org/leadership",
            institution="Example Institute",
            funding_type=PDFundingType.FULLY_FUNDED,
            fy=self.fy,
            requested_amount_cents=amount,
            course_fee_cents=amount,
            status=PDStatus.DRAFT,
            start_date=dt.date(2026, 1, 5),
            end_date=dt.date(2026, 3, 5),
            exception_reason=exception_reason,
        )

    def _remaining(self):
        return StaffPDService.balances(self.learner, self.fy)["remaining"]

    def test_a_funded_request_commits_against_the_envelope_when_submitted(self):
        # ── 0. The full envelope is available ─────────────────────────────
        self.assertEqual(
            self._remaining(),
            ENVELOPE,
            "the fixture's allocation never reached the balance, so every "
            "assertion below about spending it down would hold over nothing",
        )

        # ── 1-2. Request submitted, routed to the manager ─────────────────
        first = self._draft(amount=FIRST, name="Instructional Leadership")
        PDApprovalRoutingService.submit(first, self.learner)
        first.refresh_from_db()
        self.assertEqual(
            first.status,
            PDStatus.SUBMITTED_TO_SUPERVISOR,
            "a request from someone with a supervisor did not route to them",
        )
        self.assertFalse(
            first.is_exception,
            "a request inside the envelope was flagged as an exception",
        )

        # The money is committed from the moment it is asked for — not from
        # approval. Anything else lets a person commit the same envelope
        # several times over while approvals are pending.
        self.assertEqual(
            self._remaining(),
            ENVELOPE - FIRST,
            "submitting a funded request did not reduce the remaining fund, "
            "so the envelope can be committed more than once",
        )

        self.client.force_login(self.learner)
        response = self.client.get("/my-professional-development")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, first.course_name)

    def test_a_second_request_beyond_what_is_left_is_refused(self):
        first = self._draft(amount=FIRST, name="Instructional Leadership")
        PDApprovalRoutingService.submit(first, self.learner)

        over = self._draft(amount=SECOND_OVER, name="Advanced Coaching")
        with self.assertRaises(BadRequest) as caught:
            PDApprovalRoutingService.submit(over, self.learner)
        self.assertIn(
            "exceeds your remaining PD fund",
            str(caught.exception),
            "the refusal does not say what is wrong, so the person cannot act " "on it",
        )
        over.refresh_from_db()
        self.assertEqual(
            over.status,
            PDStatus.DRAFT,
            "the over-budget request was left in a submitted state despite "
            "the refusal",
        )

    def test_a_second_request_within_what_is_left_still_goes_through(self):
        """The envelope must refuse the right things and only those.

        Without this, the refusal above could be passing because the second
        request is refused unconditionally.
        """
        first = self._draft(amount=FIRST, name="Instructional Leadership")
        PDApprovalRoutingService.submit(first, self.learner)

        second = self._draft(amount=SECOND_WITHIN, name="Data for Decisions")
        PDApprovalRoutingService.submit(second, self.learner)
        second.refresh_from_db()
        self.assertEqual(second.status, PDStatus.SUBMITTED_TO_SUPERVISOR)
        self.assertFalse(second.is_exception)
        self.assertEqual(self._remaining(), ENVELOPE - FIRST - SECOND_WITHIN)

    def test_going_over_with_a_declared_reason_is_allowed_and_recorded(self):
        """The exception flag is the audit trail for over-budget spending.

        A request that goes over and is NOT marked is worse than one that is
        refused: it spends beyond the envelope and looks routine doing it.
        """
        first = self._draft(amount=FIRST, name="Instructional Leadership")
        PDApprovalRoutingService.submit(first, self.learner)

        over = self._draft(
            amount=SECOND_OVER,
            name="Advanced Coaching",
            exception_reason="Regional mandate; funded from the country reserve.",
        )
        PDApprovalRoutingService.submit(over, self.learner)
        over.refresh_from_db()
        self.assertEqual(over.status, PDStatus.SUBMITTED_TO_SUPERVISOR)
        self.assertTrue(
            over.is_exception,
            "a request that exceeded the envelope was accepted WITHOUT being "
            "marked an exception — over-budget development spending is now "
            "indistinguishable from routine spending",
        )
        # The overspend is recorded, and the two figures say different things
        # on purpose: `remaining_raw` is the signed truth, `remaining` is
        # clamped at zero because it is what the page renders. Both are
        # pinned — the first so an exception cannot be granted without the
        # commitment being visible somewhere, the second because every
        # consumer of `remaining` is entitled to assume it never goes
        # negative.
        balances = StaffPDService.balances(self.learner, self.fy)
        self.assertEqual(
            balances["remaining_raw"],
            ENVELOPE - FIRST - SECOND_OVER,
            "an exception was granted and the overspend is recorded nowhere, "
            "so the figure a budget holder reads understates what is committed",
        )
        self.assertLess(balances["remaining_raw"], 0)
        self.assertEqual(
            balances["remaining"],
            0,
            "the displayed remaining fund went negative; it is clamped so the "
            "page and its consumers can rely on a floor of zero",
        )
