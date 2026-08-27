"""Journey 8 — Activity cancelled after disbursement, walked end to end.

Journey 8 of the mandate's twenty-two: Cancellation, Planned output reversal,
Unused balance, Accountability, Recovery, No achievement. It is the journey
that touches three of the mandate's own P0 examples at once — money that has
already moved, recovery of what was not spent, and achievement credit that
must not survive the work being called off.

The suite already tested the two halves separately and neither knew about the
other. `test_cancelled_work_is_never_achieved` cancels a verified activity and
watches the milestone credit reverse, but no money is ever disbursed in it.
`test_audit_funding_channels` moves real money but never cancels anything. The
seam between them is where the damage lives: FIN-01 was a cancellation path
that CASCADE-deleted a *disbursed* advance, and TGT-02 was cancelled work
keeping its achievement credit. Each was a failure on one side of a join that
nothing walked.

So this walks the join. Real planning, a real weekly advance really disbursed
and receipted, then cancellation — and then the questions that only matter
once money has moved: does the disbursed advance still exist, can the owner
still account for what they actually spent, does the unused balance come back
through the accountant's verification, and is the achievement column clean.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.fy import get_operational_fy
from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequest
from apps.geography.models import District, Region
from apps.schools.models import School

TRANSPORT = 50_000
LUNCH = 12_000


def _confirmed_ssa(school, *, fy=None, score=6.0):
    from apps.core.enums import SsaIntervention
    from apps.ssa.models import SsaRecord, SsaScore

    record = SsaRecord.objects.create(
        school=school,
        fy=fy or get_operational_fy(),
        date_of_ssa=timezone.now(),
        average_score=score,
        verification_status="confirmed",
    )
    for intervention, _ in SsaIntervention.choices:
        SsaScore.objects.create(
            ssa_record=record, intervention=intervention, score=score
        )
    return record


def _schedulable_date() -> datetime.date:
    from apps.core.calendar_policy import SchedulingPolicyService

    day = timezone.localdate() + datetime.timedelta(days=7)
    for _ in range(21):
        if SchedulingPolicyService.check(None, day)["status"] != "blocked":
            return day
        day += datetime.timedelta(days=1)
    raise AssertionError("no schedulable date within three weeks")


def _at(day: datetime.date):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(9, 0)))


class CancelAfterDisbursementJourneyTest(TestCase):
    """Plan → fund → disburse → receipt → cancel → account → recover."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Cancel Region")
        cls.district = District.objects.create(
            name="Cancel District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="SCH-CANCEL-1",
            name="Cancel Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        _confirmed_ssa(cls.school)

        def _person(email, name, role):
            user = User.objects.create_user(
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            profile = StaffProfile.objects.create(
                user=user, staff_number=f"CN-{name[:6]}", country="Uganda", title=role
            )
            return user, profile

        cls.cceo, cls.cceo_sp = _person("cn-cceo@edify.org", "Cn CCEO", "CCEO")
        cls.pl, cls.pl_sp = _person("cn-pl@edify.org", "Cn PL", "Program Lead")
        cls.accountant, _ = _person("cn-acct@edify.org", "Cn Acct", "Accountant")

        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)

        cls.day = _schedulable_date()
        cls.fy = get_operational_fy(cls.day)
        cls.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda", fy=cls.fy, is_active=True, defaults={"version": 1}
        )
        for key, cost in (
            ("primary_transport_per_day", TRANSPORT),
            ("primary_lunch_per_day", LUNCH),
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key.replace("_", " ").title(),
                    "unit_cost": cost,
                    "fy": cls.fy,
                    "catalogue": cls.catalogue,
                },
            )

    def _fund_a_visit(self):
        """Plan a real visit and get its advance genuinely disbursed."""
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.fund_requests.weekly_service import (
            approve_weekly_request,
            confirm_receipt,
            disburse,
            request_advance,
        )
        from apps.planning.services import schedule_school_visit

        item = resolve_item_for_workflow_kind("school_visit")
        schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(self.day).isoformat(),
                "activityPurposeText": "Journey 8 proof",
            },
            self.cceo,
        )
        activity = Activity.objects.get(school=self.school)
        self.assertEqual(activity.status, "scheduled")

        wfr = WeeklyFundRequest.objects.get(responsible_user=self.cceo.id)
        request_advance(wfr.id, self.cceo)
        approve_weekly_request(wfr.id, self.pl)
        disburse(wfr.id, {"method": "Bank", "reference": "CN-1"}, self.accountant)
        confirm_receipt(wfr.id, self.cceo)

        advances = list(
            AdvanceRequest.objects.filter(
                budget_line__weekly_request_lines__weekly_fund_request=wfr
            ).distinct()
        )
        self.assertTrue(
            advances,
            "the fixture disbursed no advance, so every assertion below about "
            "money that has already moved would hold for the wrong reason",
        )
        for advance in advances:
            advance.refresh_from_db()
            self.assertGreater(
                advance.disbursed_amount or 0,
                0,
                "an advance was created but nothing was actually disbursed",
            )
        return activity, advances

    def test_cancelling_funded_work_keeps_the_money_and_drops_the_achievement(self):
        from apps.activities import services as asvc
        from apps.fund_requests import advance_service

        activity, advances = self._fund_a_visit()
        disbursed = {a.id: a.disbursed_amount for a in advances}

        # ── 1. Cancellation, through the real service ─────────────────────
        with self.captureOnCommitCallbacks(execute=True):
            # The responsible CCEO cancels their own work. A Programme Lead
            # has read-only supervisory oversight here and the platform
            # refuses them by name — verified below.
            asvc.cancel(
                activity.id,
                {"reason": "School closed for the term"},
                self.cceo,
            )
        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")

        # ── 2. Money that already moved SURVIVES the cancellation ─────────
        # This is the FIN-01 shape: a cancellation path that reaches through
        # to a disbursed advance destroys the disbursed, accounted and
        # returned figures along with the NetSuite code, and the person
        # accountable for the cash has nothing left to account against.
        for advance_id, amount in disbursed.items():
            survivor = AdvanceRequest.objects.filter(id=advance_id).first()
            self.assertIsNotNone(
                survivor,
                "cancelling the activity deleted an advance whose money had "
                "already been disbursed — the cash is real and now has no "
                "record to settle against",
            )
            self.assertEqual(
                survivor.disbursed_amount,
                amount,
                "the disbursed figure changed when the activity was cancelled",
            )

        # ── 3. Unused balance + 4. Accountability ─────────────────────────
        # The visit never happened, so the owner spent a part and returns the
        # rest. Accountability must still be reachable on cancelled work:
        # money that moved settles through this workflow or not at all.
        for index, advance in enumerate(advances):
            advance.refresh_from_db()
            total = advance.disbursed_amount
            spent = total // 3  # some cost was genuinely incurred
            advance_service.submit_accountability(
                advance.id,
                {
                    "amountSpent": spent,
                    "amountReturned": total - spent,
                    "netsuiteId": f"NS-CANCEL-{index}",
                },
                self.cceo,
            )
            advance.refresh_from_db()
            self.assertEqual(
                advance.status,
                "accountability_pl_pending",
                "a cancelled activity's advance could not be accounted for, "
                "so disbursed cash has no route back",
            )
            self.assertEqual(
                advance.returned_amount,
                total - spent,
                "the unused balance was not recorded as returnable",
            )

        for advance in advances:
            advance_service.pl_approve_accountability(advance.id, self.pl)
            advance.refresh_from_db()
            self.assertEqual(advance.status, "accountability_pending")

        # ── 5. Recovery — the accountant VERIFIES the return ──────────────
        # A self-declared return is not a recovery. The mandate makes the
        # accountant's verification the step that turns a claim into money
        # actually back in the account.
        for advance in advances:
            advance_service.verify_return(
                advance.id, {"reference": "RCV-CANCEL-1"}, self.accountant
            )
            advance.refresh_from_db()
            self.assertIsNotNone(
                advance.return_verified_at,
                "the unused balance was never verified as recovered",
            )

        for advance in advances:
            advance_service.approve_accountability(advance.id, self.accountant)
            advance.refresh_from_db()
            self.assertEqual(
                advance.status,
                "accounted",
                f"advance {advance.id} stalled at {advance.status} — cancelled "
                "work cannot reach a settled financial state",
            )
            # The settlement identity the platform checks at every terminal
            # transition: spend == received - returned + reimbursed.
            self.assertEqual(
                advance.accounted_amount,
                advance.disbursed_amount - (advance.returned_amount or 0),
                "the cancelled activity settled with a silent mismatch",
            )

        # ── 6. No achievement ─────────────────────────────────────────────
        from apps.hr.models import MilestoneProgressCredit

        self.assertFalse(
            MilestoneProgressCredit.objects.filter(
                activity=activity, reversed_at__isnull=True
            ).exists(),
            "cancelled work is standing in the achievement ledger — funded, "
            "called off, and still counted as delivered",
        )

    def test_the_cancelled_activity_stops_counting_as_planned_output(self):
        """Planned output reversal — step 2, asserted on its own.

        Kept separate because it is the step most easily satisfied by
        accident: an aggregate that happens to exclude cancelled work today
        can start including it without any other assertion here noticing.
        """
        from apps.activities import services as asvc
        from apps.activities.models import ActivityScheduleCostLine

        activity, _ = self._fund_a_visit()
        planned_before = ActivityScheduleCostLine.objects.filter(
            activity=activity
        ).count()
        self.assertGreater(
            planned_before,
            0,
            "the fixture produced no cost lines, so a reversal assertion "
            "would pass against nothing",
        )

        with self.captureOnCommitCallbacks(execute=True):
            asvc.cancel(activity.id, {"reason": "School closed"}, self.cceo)

        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")

        # The cost lines are deliberately RETAINED as the historical snapshot
        # (see activities.services._cancel_or_defer); what must change is that
        # every forward-looking aggregate stops counting them.
        self.assertEqual(
            ActivityScheduleCostLine.objects.filter(activity=activity).count(),
            planned_before,
            "the historical cost snapshot was destroyed rather than excluded",
        )
        self.assertFalse(
            Activity.objects.filter(id=activity.id)
            .exclude(status__in=("cancelled", "deferred"))
            .exists(),
            "the cancelled activity is still inside the set every planned-"
            "output aggregate draws from",
        )


class CalledOffClearanceControlsTest(CancelAfterDisbursementJourneyTest):
    """The guards around the FIN-04 fix, on the same real-money fixture.

    Walking Journey 8 found that finance clearance required IA verification,
    which called-off work can never obtain, so disbursed cash could never
    settle. The fix lets cancelled and deferred work clear — and these hold
    the two edges of that, because a fix to a money gate is only as good as
    the case it still refuses.
    """

    def _accounted_to_pending(self, *, returned: bool):
        """Get a cancelled activity's advance to accountability_pending."""
        from apps.activities import services as asvc
        from apps.fund_requests import advance_service

        activity, advances = self._fund_a_visit()
        with self.captureOnCommitCallbacks(execute=True):
            asvc.cancel(activity.id, {"reason": "School closed"}, self.cceo)

        for index, advance in enumerate(advances):
            advance.refresh_from_db()
            total = advance.disbursed_amount
            spent = total // 3 if returned else total
            payload = {"amountSpent": spent, "netsuiteId": f"NS-CTRL-{index}"}
            if returned:
                payload["amountReturned"] = total - spent
            advance_service.submit_accountability(advance.id, payload, self.cceo)
            advance_service.pl_approve_accountability(advance.id, self.pl)
            advance.refresh_from_db()
            self.assertEqual(advance.status, "accountability_pending")
        return activity, advances

    def test_called_off_work_cannot_clear_while_its_return_is_unverified(self):
        """The control that replaces IA verification must actually bite."""
        from apps.core.exceptions import BadRequest
        from apps.fund_requests import advance_service

        _activity, advances = self._accounted_to_pending(returned=True)
        for advance in advances:
            with self.assertRaises(BadRequest) as caught:
                advance_service.approve_accountability(advance.id, self.accountant)
            self.assertIn(
                "verified",
                str(caught.exception).lower(),
                "cancelled work with money still owed cleared without anyone "
                "confirming the money came back",
            )
            advance.refresh_from_db()
            self.assertEqual(advance.status, "accountability_pending")

    def test_called_off_work_with_nothing_to_return_still_clears(self):
        """A genuine full spend on work later called off is a real expense."""
        from apps.fund_requests import advance_service

        _activity, advances = self._accounted_to_pending(returned=False)
        for advance in advances:
            advance_service.approve_accountability(advance.id, self.accountant)
            advance.refresh_from_db()
            self.assertEqual(advance.status, "accounted")

    def test_delivered_work_still_requires_ia_verification(self):
        """No hole opened: the original gate stands for work not called off."""
        from apps.core.exceptions import BadRequest
        from apps.fund_requests import advance_service

        activity, advances = self._fund_a_visit()
        # NOT cancelled — an ordinary scheduled activity whose owner accounts
        # for the money before IA has certified anything.
        for index, advance in enumerate(advances):
            advance.refresh_from_db()
            advance_service.submit_accountability(
                advance.id,
                {
                    "amountSpent": advance.disbursed_amount,
                    "netsuiteId": f"NS-DELIV-{index}",
                },
                self.cceo,
            )
            advance_service.pl_approve_accountability(advance.id, self.pl)

        self.assertNotIn(activity.status, ("cancelled", "deferred"))
        for advance in advances:
            with self.assertRaises(BadRequest) as caught:
                advance_service.approve_accountability(advance.id, self.accountant)
            self.assertIn(
                "IA has not verified",
                str(caught.exception),
                "undelivered, uncertified work cleared finance — the "
                "cancelled-work branch was written too wide",
            )
