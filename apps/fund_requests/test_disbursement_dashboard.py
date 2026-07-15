"""Tests for the Fund Disbursement Dashboard (accountant finance center).

Core rule under test: only approved fund requests can be disbursed. The
dashboard consolidates monthly plans, weekly advances, partner payments, and
reimbursements; the accountant disburses / holds / returns; every action is
audited, notified, and reflected in derive-from-state To-Dos.
"""

import threading
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.audit.models import AuditLog
from apps.command_center.todo_service import get_todos
from apps.core.enums import ActivityType
from apps.core.exceptions import BadRequest, Forbidden
from apps.fund_requests import disbursement_dashboard_service as svc
from apps.fund_requests import pl_approval_service as pl_svc
from apps.fund_requests.models import FundRequest, WeeklyFundRequest
from apps.geography.models import District, Region
from apps.schools.models import School

FY = "2026"
MONTH = 7


class _Principal:
    def __init__(self, user, profile=None):
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile_id = profile.id if profile else None


class DisbursementDashboardTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)

        # PL supervises CCEO; the PL approval routes plans into the queue.
        self.pl = User.objects.create(
            id="pl-1",
            email="pl@edify.org",
            name="Pat Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        self.pl_sp = StaffProfile.objects.create(id="sp-pl", user=self.pl, title="PL")
        self.cceo = User.objects.create(
            id="cceo-1",
            email="cceo@edify.org",
            name="Sarah Ncube",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.cceo_sp = StaffProfile.objects.create(
            id="sp-cceo", user=self.cceo, title="CCEO"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        self.acct = User.objects.create(
            id="acct-1",
            email="acct@edify.org",
            name="Moses Tindi",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        self.pl_p = _Principal(self.pl, self.pl_sp)
        self.cceo_p = _Principal(self.cceo, self.cceo_sp)
        self.acct_p = _Principal(self.acct)

        school = School.objects.create(
            school_id="SCH-1",
            name="Test School",
            region=self.region,
            district=self.district,
        )
        act = Activity.objects.create(
            school=school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            responsible_staff_id=self.cceo_sp.id,
            fy=FY,
        )
        ActivityScheduleCostLine.objects.create(
            activity=act,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=250_000,
            quantity=1,
            amount=250_000,
            month=MONTH,
            fiscal_year=FY,
            catalogue_id="cat-v1",
        )

    def _approved_plan(self):
        """PL approves → the plan lands in the accountant queue."""
        return pl_svc.approve(self.pl_p, self.cceo.id, FY, MONTH)

    # ── access + queue composition ────────────────────────────────────────────
    def test_only_accountant_can_open_dashboard(self):
        with self.assertRaises(Forbidden):
            svc.get_disbursement_dashboard(self.cceo_p, {"fy": FY, "month": MONTH})
        ctx = svc.get_disbursement_dashboard(self.acct_p, {"fy": FY, "month": MONTH})
        self.assertIn("queue", ctx)

    def test_approved_plan_enters_disbursement_queue(self):
        self._approved_plan()
        ctx = svc.get_disbursement_dashboard(self.acct_p, {"fy": FY, "month": MONTH})
        pending = [q for q in ctx["queue"] if q["status"] == "Pending Disbursement"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["name"], "Sarah Ncube")
        self.assertEqual(pending[0]["kind_label"], "Team Fund Plan")

    def test_unapproved_plan_cannot_be_disbursed(self):
        # A plan still in the approval chain is visible but NOT disbursable.
        fr = FundRequest.objects.create(
            fy=FY,
            period="monthly",
            period_key=f"{FY}-M{MONTH}",
            scope="own",
            submitted_by_user_id=self.cceo.id,
            submitted_by_role="CCEO",
            total_amount=100_000,
            activity_count=1,
            status="submitted_to_pl",
        )
        ctx = svc.get_disbursement_dashboard(
            self.acct_p, {"fy": FY, "month": MONTH, "item": f"fr:{fr.id}"}
        )
        self.assertEqual(ctx["selected"]["status"], "Pending Approval")
        self.assertFalse(ctx["selected"]["can_disburse"])
        with self.assertRaises(BadRequest):
            svc.disburse(self.acct_p, fr.id)

    def test_weekly_advance_appears_in_queue(self):
        WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 6),
            week_end_date=date(2026, 7, 12),
            responsible_user=self.cceo.id,
            total_amount=80_000,
            status="confirmed_for_advance",
        )
        ctx = svc.get_disbursement_dashboard(self.acct_p, {"fy": FY, "month": MONTH})
        kinds = {q["kind_label"] for q in ctx["queue"]}
        self.assertIn("Weekly Advance", kinds)

    # ── approval chain gating ─────────────────────────────────────────────────
    def test_chain_shows_finance_pending_after_pl_approval(self):
        fr = self._approved_plan()
        ctx = svc.get_disbursement_dashboard(
            self.acct_p, {"fy": FY, "month": MONTH, "item": f"fr:{fr.id}"}
        )
        chain = {c["label"]: c["state"] for c in ctx["selected"]["chain"]}
        self.assertEqual(chain["PL"], "approved")
        self.assertEqual(chain["Finance"], "pending")
        self.assertEqual(chain["Disbursement"], "not_started")
        self.assertTrue(ctx["selected"]["can_disburse"])

    # ── disburse ──────────────────────────────────────────────────────────────
    def test_disburse_records_payment_and_notifies(self):
        fr = self._approved_plan()
        svc.disburse(
            self.acct_p,
            fr.id,
            {"amount": "250000", "method": "Mobile Money", "reference": "TXN-77"},
        )
        fr.refresh_from_db()
        self.assertEqual(fr.status, "disbursed")
        self.assertEqual(fr.disbursed_amount, 250_000)
        self.assertEqual(fr.disburse_method, "Mobile Money")
        self.assertEqual(fr.disburse_reference, "TXN-77")
        self.assertEqual(fr.disbursed_by_user_id, self.acct.id)
        self.assertTrue(
            AuditLog.objects.filter(
                action="fund_request.disburse", subject_id=fr.id
            ).exists()
        )
        from apps.notifications.models import Notification

        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cceo.id, source_event_type="fund_request_disbursed"
            ).exists()
        )

    def test_disburse_crash_leaves_plan_undisbursed(self):
        """disburse()'s FundRequest.save() + Disbursement.bulk_create() must be
        atomic — a crash between the two must roll back both, never leaving a
        FundRequest marked "disbursed" with zero Disbursement audit rows."""
        from apps.fund_requests.finance_models import Disbursement

        fr = self._approved_plan()
        with patch(
            "apps.fund_requests.finance_models.Disbursement.objects.bulk_create",
            side_effect=RuntimeError("simulated crash mid-write"),
        ):
            with self.assertRaises(RuntimeError):
                svc.disburse(
                    self.acct_p,
                    fr.id,
                    {"method": "Mobile Money", "reference": "TXN-CRASH"},
                )

        fr.refresh_from_db()
        self.assertEqual(fr.status, "sent_to_accountant")
        self.assertIsNone(fr.disbursed_at)
        self.assertIsNone(fr.disbursed_amount)
        self.assertEqual(Disbursement.objects.filter(fund_request=fr).count(), 0)

    def test_disburse_creates_one_disbursement_record_per_activity(self):
        """Disbursement.activity is required — a month-level release must still
        leave a real per-activity audit trail, split proportionally when the
        accountant releases less than the full approved total."""
        from apps.fund_requests.finance_models import Disbursement

        # setUp() already schedules one 250_000 activity for this CCEO/month;
        # add a second so the proportional split has two real lines to cover.
        school2 = School.objects.create(
            school_id="SCH-2",
            name="Second School",
            region=self.region,
            district=self.district,
        )
        act2 = Activity.objects.create(
            school=school2,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            responsible_staff_id=self.cceo_sp.id,
            fy=FY,
        )
        ActivityScheduleCostLine.objects.create(
            activity=act2,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=250_000,
            quantity=1,
            amount=250_000,
            month=MONTH,
            fiscal_year=FY,
            catalogue_id="cat-v1",
        )

        fr = self._approved_plan()  # two activities, 250_000 each, total 500_000
        self.assertEqual(fr.total_amount, 500_000)
        line_activity_ids = {item.activity_id for item in fr.items.all()}
        self.assertEqual(len(line_activity_ids), 2)

        svc.disburse(
            self.acct_p,
            fr.id,
            {"amount": "250000", "method": "Bank Transfer", "reference": "TXN-88"},
        )
        records = Disbursement.objects.filter(fund_request=fr)
        self.assertEqual(records.count(), 2)
        self.assertEqual({r.activity_id for r in records}, line_activity_ids)
        # fraction = 250_000 / 500_000 = 0.5, applied to each 250_000 line.
        for r in records:
            self.assertEqual(r.amount_disbursed, 125_000)
            self.assertEqual(r.payment_method, "Bank Transfer")
            self.assertEqual(r.payment_reference, "TXN-88")
            self.assertEqual(r.disbursed_by, self.acct.id)

    def test_disburse_rejects_over_approved_amount(self):
        fr = self._approved_plan()
        with self.assertRaises(BadRequest):
            svc.disburse(self.acct_p, fr.id, {"amount": "9999999"})

    def test_double_disbursement_blocked(self):
        fr = self._approved_plan()
        svc.disburse(self.acct_p, fr.id)
        with self.assertRaises(BadRequest):
            svc.disburse(self.acct_p, fr.id)

    # ── hold / release ────────────────────────────────────────────────────────
    def test_hold_requires_reason_and_keeps_item_in_queue(self):
        fr = self._approved_plan()
        with self.assertRaises(BadRequest):
            svc.hold(self.acct_p, fr.id, {"reason": ""})
        svc.hold(self.acct_p, fr.id, {"reason": "Cash not available"})
        fr.refresh_from_db()
        self.assertEqual(fr.status, "held")
        self.assertIn("Cash not available", fr.held_reason)
        ctx = svc.get_disbursement_dashboard(self.acct_p, {"fy": FY, "month": MONTH})
        held = [q for q in ctx["queue"] if q["status"] == "Held"]
        self.assertEqual(len(held), 1)
        # Held items cannot be disbursed until released.
        with self.assertRaises(BadRequest):
            svc.disburse(self.acct_p, fr.id)

    def test_release_returns_item_to_disbursement_queue(self):
        fr = self._approved_plan()
        svc.hold(self.acct_p, fr.id, {"reason": "Bank issue"})
        svc.release(self.acct_p, fr.id)
        fr.refresh_from_db()
        self.assertEqual(fr.status, "sent_to_accountant")
        self.assertIsNone(fr.held_reason)

    # ── return ────────────────────────────────────────────────────────────────
    def test_return_creates_requester_todo(self):
        fr = self._approved_plan()
        svc.return_item(
            self.acct_p,
            fr.id,
            {"reason": "Missing payment details", "comment": "Add mobile money number"},
        )
        fr.refresh_from_db()
        self.assertEqual(fr.status, "returned_by_accountant")
        titles = [t["title"] for t in get_todos(self.cceo_p)["todos"]]
        self.assertIn("Fix Returned Fund Request", titles)

    # ── receipt confirmation ──────────────────────────────────────────────────
    def test_receipt_confirmation_flow_and_todo_autoclose(self):
        fr = self._approved_plan()
        svc.disburse(self.acct_p, fr.id, {"method": "Bank Transfer", "reference": "R1"})
        # The requester derives a Confirm Receipt To-Do…
        titles = [t["title"] for t in get_todos(self.cceo_p)["todos"]]
        self.assertIn("Confirm Receipt of Funds", titles)
        # …only the requester can confirm…
        with self.assertRaises(Forbidden):
            svc.confirm_receipt(self.acct_p, fr.id)
        svc.confirm_receipt(self.cceo_p, fr.id)
        fr.refresh_from_db()
        self.assertIsNotNone(fr.receipt_confirmed_at)
        # …and the To-Do auto-closes.
        titles = [t["title"] for t in get_todos(self.cceo_p)["todos"]]
        self.assertNotIn("Confirm Receipt of Funds", titles)

    # ── accountant To-Dos ─────────────────────────────────────────────────────
    def test_accountant_disburse_todo_derives_and_autocloses(self):
        fr = self._approved_plan()
        titles = [t["title"] for t in get_todos(self.acct_p)["todos"]]
        self.assertIn("Disburse Sarah Ncube Fund Plan", titles)
        svc.disburse(self.acct_p, fr.id)
        titles = [t["title"] for t in get_todos(self.acct_p)["todos"]]
        self.assertNotIn("Disburse Sarah Ncube Fund Plan", titles)

    # ── reconciliation tracker ────────────────────────────────────────────────
    def test_disbursed_plan_enters_reconciliation_awaiting_receipts(self):
        fr = self._approved_plan()
        svc.disburse(self.acct_p, fr.id)
        ctx = svc.get_disbursement_dashboard(self.acct_p, {"fy": FY, "month": MONTH})
        self.assertEqual(ctx["recon"]["counts"]["receipts"], 1)
        labels = [r["label"] for r in ctx["recon"]["rows"]]
        self.assertTrue(any("Sarah Ncube" in label for label in labels))

    def test_reconciliation_netsuite_stage(self):
        fr = self._approved_plan()
        svc.disburse(self.acct_p, fr.id)
        fr.refresh_from_db()
        fr.accountability_submitted_at = timezone.now()
        fr.save(update_fields=["accountability_submitted_at"])
        ctx = svc.get_disbursement_dashboard(self.acct_p, {"fy": FY, "month": MONTH})
        self.assertEqual(ctx["recon"]["counts"]["netsuite"], 1)

    # ── analytics honesty ─────────────────────────────────────────────────────
    def test_kpis_reflect_real_amounts(self):
        self._approved_plan()
        ctx = svc.get_disbursement_dashboard(self.acct_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["Pending Disbursement"], "UGX 250K")
        self.assertEqual(by_label["Disbursed Today"], "UGX 0")
        # Utilization: allocation from real cost lines; nothing disbursed yet.
        self.assertEqual(ctx["utilization"]["allocation"], "UGX 250K")
        self.assertEqual(ctx["utilization"]["pct"], 0)


class DisbursementDoubleClickRaceTest(TransactionTestCase):
    """Regression test for a double-click on the "Disburse Funds" button: two
    near-simultaneous POSTs to /disbursements/action must not both pass the
    "still sent_to_accountant" check and write two sets of Disbursement audit
    rows. Uses real threads + TransactionTestCase so the two svc.disburse()
    calls run in genuinely concurrent DB transactions (a plain TestCase wraps
    the whole test in one transaction and can't reproduce the race)."""

    # TransactionTestCase truncates every table after each test, which would
    # otherwise silently wipe migration-seeded rows (e.g. the default
    # CostCatalogue) that other test modules in the same run depend on.
    # serialized_rollback=True would only restore that seeded state
    # transiently in THIS class's own setUp (not permanently -- under
    # --keepdb the next `manage.py test` invocation reuses a database left
    # flushed), AND it collides with the explicit reseed below (Django
    # inserts the ORIGINAL serialized snapshot's rows on top of what the
    # previous test's teardown already reseeded -- duplicate-key IntegrityError
    # on CostCatalogue's natural-key unique constraint). Deliberately NOT
    # using serialized_rollback; _post_teardown is the single source of
    # truth that leaves the kept database in a good state either way.

    def _post_teardown(self):
        super()._post_teardown()
        from apps.core.test_seed_utils import reseed_migration_data

        reseed_migration_data()

    def setUp(self):
        User = get_user_model()
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.pl = User.objects.create(
            id="pl-race-1",
            email="pl-race@edify.org",
            name="Pat Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        self.pl_sp = StaffProfile.objects.create(
            id="sp-pl-race", user=self.pl, title="PL"
        )
        self.cceo = User.objects.create(
            id="cceo-race-1",
            email="cceo-race@edify.org",
            name="Race Cceo",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.cceo_sp = StaffProfile.objects.create(
            id="sp-cceo-race", user=self.cceo, title="CCEO"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        self.acct = User.objects.create(
            id="acct-race-1",
            email="acct-race@edify.org",
            name="Moses Tindi",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        self.acct_p = _Principal(self.acct)

        school = School.objects.create(
            school_id="SCH-RACE-1",
            name="Race School",
            region=self.region,
            district=self.district,
        )
        act = Activity.objects.create(
            school=school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            responsible_staff_id=self.cceo_sp.id,
            fy=FY,
        )
        ActivityScheduleCostLine.objects.create(
            activity=act,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=250_000,
            quantity=1,
            amount=250_000,
            month=MONTH,
            fiscal_year=FY,
            catalogue_id="cat-v1",
        )

    def test_concurrent_disburse_calls_write_exactly_one_set_of_records(self):
        from apps.fund_requests.finance_models import Disbursement

        fr = pl_svc.approve(_Principal(self.pl, self.pl_sp), self.cceo.id, FY, MONTH)

        barrier = threading.Barrier(2)
        outcomes = []

        def worker():
            try:
                barrier.wait(timeout=5)
                svc.disburse(
                    self.acct_p,
                    fr.id,
                    {"method": "Mobile Money", "reference": "TXN-RACE"},
                )
                outcomes.append("disbursed")
            except BadRequest as e:
                outcomes.append(f"blocked:{e}")
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Exactly one of the two double-click requests must win; the other
        # must be cleanly rejected — never both silently "succeeding".
        self.assertEqual(outcomes.count("disbursed"), 1, outcomes)
        self.assertEqual(
            sum(1 for o in outcomes if o.startswith("blocked:")), 1, outcomes
        )

        fr.refresh_from_db()
        self.assertEqual(fr.status, "disbursed")
        # Only one activity funds this plan — a duplicate write would leave 2.
        self.assertEqual(Disbursement.objects.filter(fund_request=fr).count(), 1)
