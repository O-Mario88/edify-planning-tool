"""Tests for the PL Fund Approval flow (apps.fund_requests.pl_approval_service).

The Program Lead approves/returns monthly fund plans that are DERIVED from the
persisted `ActivityScheduleCostLine` budget lines of the CCEOs they supervise —
never other PLs' portfolios, never country-wide, and never hand-entered totals.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.audit.models import AuditLog
from apps.command_center.todo_service import get_todos
from apps.core.enums import ActivityType
from apps.core.exceptions import BadRequest, Forbidden
from apps.fund_requests import pl_approval_service as svc
from apps.fund_requests.models import FundRequest
from apps.geography.models import District, Region
from apps.schools.models import School

FY = "2026"
MONTH = 7  # July


class _Principal:
    """The minimal AuthPrincipal shape resolve_user_scope + the service need."""

    def __init__(self, user, profile=None):
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile_id = profile.id if profile else None


class PLFundApprovalTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region)

        # ── Team A: PL1 supervises CCEO-A ────────────────────────────────────
        self.pl1 = User.objects.create(
            id="pl-1",
            email="pl1@edify.org",
            name="Pat Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        self.pl1_sp = StaffProfile.objects.create(
            id="sp-pl-1", user=self.pl1, title="PL"
        )
        self.cceo_a = User.objects.create(
            id="cceo-a",
            email="cceoa@edify.org",
            name="Sarah Ncube",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.cceo_a_sp = StaffProfile.objects.create(
            id="sp-cceo-a", user=self.cceo_a, title="CCEO"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl1_sp, supervisee=self.cceo_a_sp
        )

        # ── Team B: PL2 supervises CCEO-B (isolation control) ────────────────
        self.pl2 = User.objects.create(
            id="pl-2",
            email="pl2@edify.org",
            name="Paul Boss",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        self.pl2_sp = StaffProfile.objects.create(
            id="sp-pl-2", user=self.pl2, title="PL"
        )
        self.cceo_b = User.objects.create(
            id="cceo-b",
            email="cceob@edify.org",
            name="Brian Otim",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.cceo_b_sp = StaffProfile.objects.create(
            id="sp-cceo-b", user=self.cceo_b, title="CCEO"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl2_sp, supervisee=self.cceo_b_sp
        )

        self.pl1_principal = _Principal(self.pl1, self.pl1_sp)
        self.pl2_principal = _Principal(self.pl2, self.pl2_sp)
        self.cceo_a_principal = _Principal(self.cceo_a, self.cceo_a_sp)

        # CCEO-A: two valid staff school visits (100k + 200k = 300k).
        self._school("SCH-A1")
        self.act_a1 = self._activity(self.cceo_a_sp.id, self._school("SCH-A1"))
        self._cost_line(self.act_a1, 100_000)
        self.act_a2 = self._activity(self.cceo_a_sp.id, self._school("SCH-A2"))
        self._cost_line(self.act_a2, 200_000)

        # CCEO-B: one visit, so PL2's team is non-empty (isolation control).
        self.act_b1 = self._activity(self.cceo_b_sp.id, self._school("SCH-B1"))
        self._cost_line(self.act_b1, 500_000)

    # ── fixture helpers ──────────────────────────────────────────────────────
    def _school(self, sid):
        return School.objects.get_or_create(
            school_id=sid,
            defaults={"name": sid, "region": self.region, "district": self.district},
        )[0]

    def _activity(
        self,
        staff_id,
        school,
        atype=ActivityType.SCHOOL_VISIT,
        delivery="staff",
        status="scheduled",
    ):
        return Activity.objects.create(
            school=school,
            delivery_type=delivery,
            activity_type=atype,
            status=status,
            responsible_staff_id=staff_id,
            fy=FY,
        )

    def _cost_line(self, activity, amount, month=MONTH, catalogue_id="cat-v1"):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=amount,
            quantity=1,
            amount=amount,
            month=month,
            fiscal_year=FY,
            catalogue_id=catalogue_id,
        )

    def _queue_names(self, principal, **filters):
        f = {"fy": FY, "month": MONTH, **filters}
        return {q["name"] for q in svc.get_pl_fund_approvals(principal, f)["queue"]}

    # ── scoping ──────────────────────────────────────────────────────────────
    def test_pl_sees_only_supervised_cceo_fund_requests(self):
        names = self._queue_names(self.pl1_principal)
        self.assertIn("Sarah Ncube", names)
        self.assertNotIn("Brian Otim", names)

    def test_pl_cannot_see_other_pl_fund_requests(self):
        names = self._queue_names(self.pl2_principal)
        self.assertIn("Brian Otim", names)
        self.assertNotIn("Sarah Ncube", names)

    def test_non_pl_cannot_access(self):
        with self.assertRaises(Forbidden):
            svc.get_pl_fund_approvals(self.cceo_a_principal, {"fy": FY, "month": MONTH})
        with self.assertRaises(Forbidden):
            svc.approve(self.cceo_a_principal, self.cceo_a.id, FY, MONTH)

    def test_pl_cannot_approve_cceo_outside_team(self):
        # PL1 must not be able to approve CCEO-B (PL2's supervisee).
        with self.assertRaises(Forbidden):
            svc.approve(self.pl1_principal, self.cceo_b.id, FY, MONTH)

    # ── derivation ───────────────────────────────────────────────────────────
    def test_fund_request_requires_activity_budget_lines(self):
        # A supervised CCEO whose activities have NO cost lines produces no plan,
        # and approving them is refused (nothing to fund).
        cceo_c = get_user_model().objects.create(
            id="cceo-c",
            email="cceoc@edify.org",
            name="Carol No-Cost",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cceo_c_sp = StaffProfile.objects.create(
            id="sp-cceo-c", user=cceo_c, title="CCEO"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl1_sp, supervisee=cceo_c_sp
        )
        self._activity(cceo_c_sp.id, self._school("SCH-C1"))  # no cost line

        self.assertNotIn("Carol No-Cost", self._queue_names(self.pl1_principal))
        with self.assertRaises(BadRequest):
            svc.approve(self.pl1_principal, cceo_c.id, FY, MONTH)

    def test_daily_visit_batch_costing_included_in_breakdown(self):
        detail = svc.get_pl_fund_approvals(
            self.pl1_principal, {"fy": FY, "month": MONTH, "cceo": self.cceo_a.id}
        )["selected"]
        self.assertEqual(detail["name"], "Sarah Ncube")
        self.assertEqual(detail["total_fmt"], svc._ugx(300_000))
        cats = {r["category"]: r for r in detail["breakdown"]}
        self.assertIn("Staff School Visits", cats)
        self.assertEqual(cats["Staff School Visits"]["qty"], 2)
        self.assertEqual(cats["Staff School Visits"]["total"], svc._ugx(300_000))

    # ── validation gates ─────────────────────────────────────────────────────
    def test_missing_cost_catalogue_version_blocks_approval(self):
        self._cost_line(self.act_a1, 50_000, catalogue_id=None)  # no catalogue version
        with self.assertRaises(BadRequest):
            svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)

    def test_partner_visit_without_planned_school_blocks_approval(self):
        act = Activity.objects.create(
            delivery_type="partner",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            responsible_staff_id=self.cceo_a_sp.id,
            fy=FY,
            school=None,  # <-- partner visit not mapped to a planned school
        )
        self._cost_line(act, 80_000)
        with self.assertRaises(BadRequest):
            svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)

    # ── approve / return ─────────────────────────────────────────────────────
    def test_pl_can_approve_valid_fund_request(self):
        # Approve routes the plan straight to the accountant's disbursement queue.
        fr = svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)
        fr.refresh_from_db()
        self.assertEqual(fr.status, "sent_to_accountant")
        self.assertEqual(fr.reviewed_by_user_id, self.pl1.id)
        self.assertEqual(fr.total_amount, 300_000)
        self.assertEqual(fr.submitted_by_user_id, self.cceo_a.id)
        # items are derived from the live budget lines, not hand-entered
        self.assertEqual(fr.items.count(), 2)

    def test_ensure_fund_request_crash_leaves_no_partial_state(self):
        """_ensure_fund_request()'s update_or_create + delete/recreate-items
        sequence must be atomic — a crash between the FundRequest write and
        the item bulk_create must roll back both, never leaving a
        FundRequest persisted with a total_amount but zero items."""
        with patch(
            "apps.fund_requests.models.FundRequestItem.objects.bulk_create",
            side_effect=RuntimeError("simulated crash mid-write"),
        ):
            with self.assertRaises(RuntimeError):
                svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)

        # Fully rolled back: no orphan FundRequest with a stale total and no
        # items — the write either lands whole or not at all.
        self.assertFalse(
            FundRequest.objects.filter(
                submitted_by_user_id=self.cceo_a.id, period="monthly"
            ).exists()
        )

    def test_pl_can_return_invalid_fund_request_with_reason(self):
        fr = svc.return_request(
            self.pl1_principal,
            self.cceo_a.id,
            FY,
            MONTH,
            {"reason": "Costs look too high", "comment": "Recheck transport rates"},
        )
        fr.refresh_from_db()
        self.assertEqual(fr.status, "returned_by_pl")
        self.assertIn("Costs look too high", fr.review_note)

    def test_return_requires_reason(self):
        with self.assertRaises(BadRequest):
            svc.return_request(
                self.pl1_principal, self.cceo_a.id, FY, MONTH, {"reason": ""}
            )

    def test_approve_all_valid_skips_invalid_requests(self):
        # Add a second supervised CCEO whose plan is INVALID (partner visit, no school).
        cceo_d = get_user_model().objects.create(
            id="cceo-d",
            email="cceod@edify.org",
            name="Dan Invalid",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cceo_d_sp = StaffProfile.objects.create(
            id="sp-cceo-d", user=cceo_d, title="CCEO"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl1_sp, supervisee=cceo_d_sp
        )
        bad = Activity.objects.create(
            delivery_type="partner",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            responsible_staff_id=cceo_d_sp.id,
            fy=FY,
            school=None,
        )
        self._cost_line(bad, 90_000)

        approved, skipped = svc.approve_all_valid(self.pl1_principal, FY, MONTH)
        self.assertEqual(approved, 1)  # only Sarah's valid plan
        self.assertEqual(skipped, 1)  # Dan's invalid plan skipped, not force-approved

        self.assertEqual(
            FundRequest.objects.filter(
                submitted_by_user_id=self.cceo_a.id, status="sent_to_accountant"
            ).count(),
            1,
        )
        self.assertFalse(
            FundRequest.objects.filter(
                submitted_by_user_id=cceo_d.id, status="sent_to_accountant"
            ).exists()
        )

    # ── accountant routing + disbursement ────────────────────────────────────
    def test_approve_routes_to_accountant_disbursement_queue(self):
        svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)
        # The plan now sits in the accountant's disbursement queue.
        queue = FundRequest.objects.filter(
            period="monthly", status="sent_to_accountant"
        )
        self.assertEqual(queue.count(), 1)
        self.assertEqual(queue.first().submitted_by_user_id, self.cceo_a.id)

    def test_approve_notifies_accountant(self):
        acct = get_user_model().objects.create(
            id="acct-1",
            email="acct@edify.org",
            name="Ada Accounts",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)
        from apps.notifications.models import Notification

        self.assertTrue(
            Notification.objects.filter(
                recipient_id=acct.id,
                source_event_type="fund_request_sent_to_accountant",
            ).exists()
        )

    def test_accountant_can_disburse_approved_plan(self):
        from apps.fund_requests import disbursement_dashboard_service as disb_svc

        acct = get_user_model().objects.create(
            id="acct-2",
            email="acct2@edify.org",
            name="Ben Books",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        acct_principal = _Principal(acct)
        fr = svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)
        disbursed = disb_svc.disburse(acct_principal, fr.id)
        disbursed.refresh_from_db()
        self.assertEqual(disbursed.status, "disbursed")

    def test_non_accountant_cannot_disburse(self):
        from apps.fund_requests import disbursement_dashboard_service as disb_svc

        fr = svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)
        with self.assertRaises(Forbidden):
            disb_svc.disburse(self.pl1_principal, fr.id)

    def test_disburse_requires_a_queued_plan(self):
        from apps.fund_requests import disbursement_dashboard_service as disb_svc

        acct = get_user_model().objects.create(
            id="acct-3",
            email="acct3@edify.org",
            name="Cara Cash",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        with self.assertRaises(BadRequest):
            disb_svc.disburse(_Principal(acct), "does-not-exist")

    # ── side effects: audit + notification + CCEO To-Do ──────────────────────
    def test_approval_creates_audit_log(self):
        svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)
        self.assertTrue(
            AuditLog.objects.filter(
                action="fund_request.approve_pl", actor_id=self.pl1.id
            ).exists()
        )

    def test_return_creates_cceo_todo(self):
        # Before return: the CCEO has no "Fix Returned Fund Request" To-Do.
        titles_before = [t["title"] for t in get_todos(self.cceo_a_principal)["todos"]]
        self.assertNotIn("Fix Returned Fund Request", titles_before)

        svc.return_request(
            self.pl1_principal,
            self.cceo_a.id,
            FY,
            MONTH,
            {"reason": "Recheck cluster participant counts"},
        )

        # After return: the To-Do is DERIVED from the returned_by_pl status.
        todos = get_todos(self.cceo_a_principal)["todos"]
        fix = next(
            (t for t in todos if t["title"] == "Fix Returned Fund Request"), None
        )
        self.assertIsNotNone(fix)
        self.assertEqual(fix["priority"], "critical")
        self.assertIn("Recheck cluster participant counts", fix["description"])

    def test_returned_todo_autocloses_on_reapproval(self):
        # Return, then re-approve — the CCEO's correction To-Do must disappear
        # (derive-from-state: it is never manually closed).
        svc.return_request(
            self.pl1_principal,
            self.cceo_a.id,
            FY,
            MONTH,
            {"reason": "Fix costs"},
        )
        self.assertIn(
            "Fix Returned Fund Request",
            [t["title"] for t in get_todos(self.cceo_a_principal)["todos"]],
        )
        svc.approve(self.pl1_principal, self.cceo_a.id, FY, MONTH)
        self.assertNotIn(
            "Fix Returned Fund Request",
            [t["title"] for t in get_todos(self.cceo_a_principal)["todos"]],
        )
