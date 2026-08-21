"""Money must move exactly once, however many times the button is pressed.

Every mutator in advance_service carries the same comment: select_for_update()
plus a status check *inside* the atomic block closes the double-click race. That
claim was never actually executed against a real database. A comment is not a
proof, and the failure it describes is the expensive kind — a second
disbursement, a second reimbursement, real money out of the account twice with
nothing in the record to say why.

So these tests run genuine concurrent threads against PostgreSQL, released
together on a barrier, and assert the arithmetic that matters:

    successes == 1                      (exactly one caller wins)
    audit rows for the action == 1      (the trail records one payment)
    the amount field written once       (no second, larger write)

TransactionTestCase, not TestCase: the threads need to see each other's
committed rows, which a shared outer transaction would hide — and hiding it is
precisely how this class of bug survives a test suite.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.finance_models import (
    NetSuiteExpenseRecord,
    PartnerPayment,
)
from apps.fund_requests.finance_services import PartnerPaymentService
from apps.fund_requests.advance_service import (
    _reconciliation_ok,
    confirm_reimbursement_receipt,
    disburse,
    reimburse,
)
from apps.fund_requests.models import (
    AdvanceRequest,
    AdvanceRequestStatus,
    WeeklyFundRequest,
    WeeklyFundRequestLine,
)
from apps.geography.models import District, Region
from apps.schools.models import School

CONCURRENCY = 6


class _Principal:
    def __init__(self, user_id: str, role: str = "Accountant"):
        self.user_id = user_id
        self.active_role = role


def _race(fn, threads: int = CONCURRENCY):
    """Run `fn` on `threads` real connections, released simultaneously.

    Returns (successes, failures). Each worker closes its own connection —
    a leaked connection here would hold a lock and hang the next test.
    """
    barrier = threading.Barrier(threads)
    successes: list = []
    failures: list = []
    lock = threading.Lock()

    def worker(index: int):
        try:
            barrier.wait(timeout=30)
            result = fn(index)
        except Exception as exc:  # noqa: BLE001 — the rejection IS the result
            with lock:
                failures.append(exc)
        else:
            with lock:
                successes.append(result)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(worker, range(threads)))

    return successes, failures


def _audit_count(action: str, subject_id: str) -> int:
    return AuditLog.objects.filter(action=action, subject_id=subject_id).count()


class ConcurrentDisbursementTest(TransactionTestCase):
    """The accountant's Disburse button, pressed six times at once."""

    def setUp(self):
        self.region = Region.objects.create(name="Race Region")
        self.district = District.objects.create(
            name="Race District", region=self.region
        )
        self.school = School.objects.create(
            school_id="SCH-RACE-1",
            name="Race Primary",
            region=self.region,
            district=self.district,
        )
        self.activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy="FY26",
            school=self.school,
            responsible_staff_id="race-owner",
        )
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            responsible_user="race-owner",
            description="Transport",
            unit_cost=450_000,
            quantity=1,
            amount=450_000,
        )
        self.advance = AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.cost_line,
            responsible_user_id="race-owner",
            fy="FY26",
            quarter="Q1",
            amount=450_000,
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
        )
        # This test is about the row lock, not the approval chain — but the
        # per-line disburse guard now requires the budget line to be CARRIED
        # by an approved weekly request (membership, not just "some request
        # for that week was approved"), so the fixture provides one.
        monday = date(2026, 4, 6)
        wfr = WeeklyFundRequest.objects.create(
            fy="FY26",
            week_start_date=monday,
            week_end_date=monday + timedelta(days=6),
            responsible_user="race-owner",
            total_amount=450_000,
            status="confirmed_for_advance",
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=wfr,
            activity_budget_line=self.cost_line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=450_000,
            total_cost=450_000,
        )

    def tearDown(self):
        connection.close()

    def test_six_simultaneous_disbursements_pay_once(self):
        successes, failures = _race(
            lambda i: disburse(
                self.advance.id,
                {"amount": 450_000, "method": "bank", "reference": f"REF-{i}"},
                _Principal(f"acct-{i}"),
            )
        )

        self.assertEqual(
            len(successes),
            1,
            f"exactly one disbursement may succeed, got {len(successes)}",
        )
        self.assertEqual(len(failures), CONCURRENCY - 1)
        for exc in failures:
            self.assertIsInstance(
                exc,
                BadRequest,
                f"a loser must be cleanly rejected, not crash: {exc!r}",
            )

        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, AdvanceRequestStatus.DISBURSED)
        self.assertEqual(
            self.advance.disbursed_amount,
            450_000,
            "the amount must be the single advance, not a multiple of it",
        )

    def test_the_audit_trail_records_one_payment_not_six(self):
        """A second payment that is not audited is worse than one that is."""
        _race(
            lambda i: disburse(
                self.advance.id,
                {"amount": 450_000, "method": "bank", "reference": f"REF-{i}"},
                _Principal(f"acct-{i}"),
            )
        )
        self.assertEqual(
            _audit_count("advance_request.disburse", self.advance.id),
            1,
            "one disbursement, one audit row",
        )

    def test_a_second_disbursement_after_the_first_settles_is_refused(self):
        """The sequential case, for completeness: the guard is the status
        check, so it must hold when there is no race at all."""
        disburse(
            self.advance.id,
            {"amount": 450_000, "method": "bank", "reference": "REF-A"},
            _Principal("acct-a"),
        )
        with self.assertRaises(BadRequest):
            disburse(
                self.advance.id,
                {"amount": 450_000, "method": "bank", "reference": "REF-B"},
                _Principal("acct-b"),
            )
        self.advance.refresh_from_db()
        self.assertEqual(self.advance.disbursed_amount, 450_000)


class ConcurrentReimbursementTest(TransactionTestCase):
    """The other money-out path: reimbursing a claim six times at once."""

    def setUp(self):
        self.region = Region.objects.create(name="Race Region 2")
        self.district = District.objects.create(
            name="Race District 2", region=self.region
        )
        self.school = School.objects.create(
            school_id="SCH-RACE-2",
            name="Race Two Primary",
            region=self.region,
            district=self.district,
        )
        self.activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy="FY26",
            school=self.school,
            responsible_staff_id="race2-owner",
            # reimburse() now refuses money for unverified work (the IA gate
            # the advance path always had) — this test is about the row lock.
            ia_verification_status="confirmed",
        )
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            responsible_user="race2-owner",
            description="Transport",
            unit_cost=200_000,
            quantity=1,
            amount=200_000,
        )
        # A self-funded claim: nothing was disbursed, the employee spent
        # 200,000 of their own money and is owed it back exactly once.
        self.advance = AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.cost_line,
            responsible_user_id="race2-owner",
            fy="FY26",
            quarter="Q1",
            amount=200_000,
            advance_type="self_funded",
            accounted_amount=200_000,
            status=AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED,
        )

    def tearDown(self):
        connection.close()

    def test_six_simultaneous_reimbursements_pay_once(self):
        successes, failures = _race(
            lambda i: reimburse(
                self.advance.id,
                {"method": "bank", "reference": f"RB-{i}"},
                _Principal(f"acct-{i}"),
            )
        )

        self.assertEqual(
            len(successes), 1, "an employee may be reimbursed once, not six times"
        )
        self.assertEqual(len(failures), CONCURRENCY - 1)

        self.advance.refresh_from_db()
        self.assertEqual(
            self.advance.status, AdvanceRequestStatus.REIMBURSEMENT_DISBURSED
        )
        self.assertEqual(self.advance.reimbursed_amount, 200_000)
        self.assertEqual(_audit_count("advance_request.reimburse", self.advance.id), 1)

    def test_reimbursing_never_touches_the_original_advance_fields(self):
        """The reconciliation identity depends on disbursed_* staying put."""
        reimburse(
            self.advance.id,
            {"method": "bank", "reference": "RB-solo"},
            _Principal("acct-solo"),
        )
        self.advance.refresh_from_db()
        self.assertIsNone(
            self.advance.disbursed_amount,
            "a self-funded claim was never disbursed and must not claim to be",
        )
        self.assertIsNone(self.advance.disburse_reference)

    def test_the_settlement_identity_holds_after_the_full_loop(self):
        """accounted == disbursed - returned + reimbursed, end to end.

        This is the identity _reconciliation_ok enforces at every terminal
        transition; here it is checked on a record that actually walked the
        pipeline rather than on a constructed row.
        """
        reimburse(
            self.advance.id,
            {"method": "bank", "reference": "RB-loop"},
            _Principal("acct-loop"),
        )
        confirm_reimbursement_receipt(
            self.advance.id, {}, _Principal("race2-owner", "CCEO")
        )
        self.advance.refresh_from_db()

        disbursed = self.advance.disbursed_amount or 0
        returned = self.advance.returned_amount or 0
        reimbursed = self.advance.reimbursed_amount or 0
        self.assertEqual(
            self.advance.accounted_amount,
            disbursed - returned + reimbursed,
            "the settlement identity must hold on a real settled record",
        )
        self.assertTrue(_reconciliation_ok(self.advance))


class LockActuallySerializesTest(TransactionTestCase):
    """Guard against the lock being silently removed.

    If someone drops select_for_update from disburse(), the two tests above
    could still pass by luck — threads rarely collide on the exact instruction.
    This one holds the row lock open and proves a second reader genuinely
    blocks, so the serialization is demonstrated rather than hoped for.
    """

    def setUp(self):
        self.region = Region.objects.create(name="Lock Region")
        self.district = District.objects.create(
            name="Lock District", region=self.region
        )
        self.school = School.objects.create(
            school_id="SCH-LOCK-1",
            name="Lock Primary",
            region=self.region,
            district=self.district,
        )
        self.activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy="FY26",
            school=self.school,
            responsible_staff_id="lock-owner",
        )
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            responsible_user="lock-owner",
            description="Transport",
            unit_cost=100_000,
            quantity=1,
            amount=100_000,
        )
        self.advance = AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.cost_line,
            responsible_user_id="lock-owner",
            fy="FY26",
            quarter="Q1",
            amount=100_000,
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
        )

    def tearDown(self):
        connection.close()

    def test_a_locked_advance_row_blocks_a_second_locker(self):
        blocked = threading.Event()
        acquired = threading.Event()

        def second_locker():
            try:
                with transaction.atomic():
                    # nowait: if the first transaction really holds the row,
                    # this raises immediately instead of waiting.
                    AdvanceRequest.objects.select_for_update(nowait=True).get(
                        id=self.advance.id
                    )
                    acquired.set()
            except Exception:  # noqa: BLE001 — being refused is the pass condition
                blocked.set()
            finally:
                connections.close_all()

        with transaction.atomic():
            AdvanceRequest.objects.select_for_update().get(id=self.advance.id)
            thread = threading.Thread(target=second_locker)
            thread.start()
            thread.join(timeout=15)

        self.assertTrue(
            blocked.is_set(),
            "a second transaction must not acquire a row this one holds",
        )
        self.assertFalse(acquired.is_set())


class ConcurrentPartnerPaymentTest(TransactionTestCase):
    """The partner payout path — the one that was actually broken.

    pay_partner ran every guard, including "already paid?", OUTSIDE its
    transaction and without a row lock. A four-way race produced 1 success and
    3 raw IntegrityErrors from uniq_partner_payment_per_activity: the money was
    safe, but the losing accountant got a database error on a payment screen
    and no way to tell whether the payment had gone through.
    """

    def setUp(self):
        self.region = Region.objects.create(name="PP Race Region")
        self.district = District.objects.create(
            name="PP Race District", region=self.region
        )
        self.school = School.objects.create(
            school_id="SCH-PP-RACE",
            name="PP Race Primary",
            region=self.region,
            district=self.district,
        )
        self.activity = Activity.objects.create(
            activity_type="partner_activity",
            delivery_type="partner",
            status="ia_verified",
            ia_verification_status="confirmed",
            fy="FY26",
            school=self.school,
            responsible_staff_id="pp-owner",
            salesforce_activity_id="SF-PP-RACE",
        )
        ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            responsible_user="pp-owner",
            description="Partner fee",
            unit_cost=300_000,
            quantity=1,
            amount=300_000,
        )
        EvidenceRecord.objects.create(
            activity_id=self.activity.id,
            kind="photo",
            uri="pp-race-evidence.jpg",
            uploaded_by="pp-owner",
        )

    def tearDown(self):
        connection.close()

    def _pay(self, index: int):
        return PartnerPaymentService.pay_partner(
            activity=Activity.objects.get(id=self.activity.id),
            partner_name="Race Partner",
            amount=300_000,
            method="bank",
            reference=f"PP-{index}",
            user_id=f"acct-{index}",
            netsuite_id=f"NS-{index}",
        )

    def test_six_simultaneous_partner_payments_pay_once(self):
        successes, failures = _race(self._pay)

        self.assertEqual(
            len(successes), 1, "a partner may be paid once for one activity"
        )
        self.assertEqual(
            PartnerPayment.objects.filter(activity=self.activity).count(),
            1,
            "one payout row — a second is a double-counted payment",
        )

    def test_the_losers_are_told_why_instead_of_getting_a_database_error(self):
        """The actual defect. IntegrityError reaching the view is a 500 on a
        payment screen, and an accountant who cannot tell whether money moved
        will reasonably try to pay again."""
        _successes, failures = _race(self._pay)

        self.assertEqual(len(failures), CONCURRENCY - 1)
        for exc in failures:
            self.assertNotIsInstance(
                exc,
                IntegrityError,
                "a raw database error must never reach the accountant",
            )
            self.assertIsInstance(
                exc,
                BadRequest,
                f"a loser must get a stated reason, got {exc!r}",
            )
            self.assertIn("already recorded", str(exc))

    def test_the_activity_is_marked_paid_exactly_once(self):
        _race(self._pay)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.payment_status, "paid")
        # NetSuite records are staff-accountability artifacts — partner
        # payments never write one (owner, 2026-08-20).
        self.assertEqual(
            NetSuiteExpenseRecord.objects.filter(activity=self.activity).count(),
            0,
            "partner payments carry no NetSuite expense record",
        )
