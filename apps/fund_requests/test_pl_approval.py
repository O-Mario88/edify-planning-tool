"""Tests for the PL Fund Approval flow (apps.fund_requests.pl_approval_service).

The queue is WEEKLY: every figure derives from the `ActivityScheduleCostLine`
budget lines generated when supervised CCEOs scheduled activities (priced from
the CD Cost Catalogue), surfaced through the auto-generated `WeeklyFundRequest`.
The CCEO sends the request (`submitted_to_pl`), the PL approves or returns, and
an approval routes it to the Accountant's disbursement queue
(`confirmed_for_advance`). All mutations delegate to weekly_service — the one
state machine — so these tests drive the full chain: schedule → auto-generate →
send → approve → accountant.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.audit.models import AuditLog
from apps.command_center.todo_service import get_todos
from apps.core.enums import ActivityType
from apps.core.exceptions import BadRequest, Forbidden
from apps.fund_requests import pl_approval_service as svc
from apps.fund_requests import weekly_service
from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequest

FY = "2026"
MONTH = 7  # July
WEEK_START = date(2026, 7, 6)  # a Monday in July FY2026
WEEK = WEEK_START.isoformat()


class _Principal:
    """The minimal AuthPrincipal shape resolve_user_scope + the service need."""

    def __init__(self, user, profile=None):
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile_id = profile.id if profile else None


class PLFundApprovalTest(TestCase):
    def setUp(self):
        User = get_user_model()
        from apps.geography.models import District, Region

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

        # CCEO-A: two valid staff school visits (100k + 200k = 300k) this week.
        self.act_a1 = self._activity(self.cceo_a_sp, self._school("SCH-A1"))
        self._cost_line(self.act_a1, 100_000)
        self.act_a2 = self._activity(self.cceo_a_sp, self._school("SCH-A2"))
        self._cost_line(self.act_a2, 200_000)

        # CCEO-B: one visit, so PL2's team is non-empty (isolation control).
        self.act_b1 = self._activity(self.cceo_b_sp, self._school("SCH-B1"))
        self._cost_line(self.act_b1, 500_000)

    # ── fixture helpers ──────────────────────────────────────────────────────
    def _school(self, sid):
        from apps.schools.models import School

        return School.objects.get_or_create(
            school_id=sid,
            defaults={"name": sid, "region": self.region, "district": self.district},
        )[0]

    def _activity(
        self,
        staff_profile,
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
            responsible_staff_id=staff_profile.id,
            fy=FY,
            # §1: every budget amount originates from a dated plan.
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 7, 7, 9, 0)),
        )

    def _cost_line(
        self,
        activity,
        amount,
        catalogue_id="cat-v1",
        key="transport_allowance",
        planned=WEEK_START + timedelta(days=1),
    ):
        owner_user_id = StaffProfile.objects.get(
            id=activity.responsible_staff_id
        ).user_id
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key=key,
            label="Transport",
            unit_cost=amount,
            quantity=1,
            amount=amount,
            month=planned.month,
            fiscal_year=FY,
            catalogue_id=catalogue_id,
            # The weekly pipeline keys on the line's owner + dates: the
            # generator selects by responsible_user + planned_date, the queue
            # by week_start_date.
            responsible_user=owner_user_id,
            planned_date=planned,
            week_start_date=planned - timedelta(days=planned.weekday()),
            week_end_date=planned
            - timedelta(days=planned.weekday())
            + timedelta(days=6),
        )
        AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            responsible_user_id=owner_user_id,
            fy=FY,
            quarter="Q1",
            month=planned.month,
            amount=amount,
            status="draft_from_schedule",
        )
        return line

    def _send(self, cceo_user_id):
        """The CCEO's own 'send weekly advance request' click."""
        wfr = weekly_service.generate_weekly_fund_request(cceo_user_id, WEEK)
        principal = (
            self.cceo_a_principal
            if cceo_user_id == self.cceo_a.id
            else _Principal(
                get_user_model().objects.get(id=cceo_user_id),
            )
        )
        weekly_service.request_advance(wfr.id, principal)
        wfr.refresh_from_db()
        return wfr

    def _page(self, principal, **filters):
        f = {"fy": FY, "month": MONTH, "week": WEEK, **filters}
        return svc.get_pl_fund_approvals(principal, f)

    def _queue_names(self, principal, **filters):
        return {q["name"] for q in self._page(principal, **filters)["queue"]}

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
            svc.get_pl_fund_approvals(
                self.cceo_a_principal, {"fy": FY, "month": MONTH, "week": WEEK}
            )
        with self.assertRaises(Forbidden):
            svc.approve(self.cceo_a_principal, self.cceo_a.id, WEEK)

    def test_pl_cannot_approve_cceo_outside_team(self):
        self._send(self.cceo_b.id)
        with self.assertRaises(Forbidden):
            svc.approve(self.pl1_principal, self.cceo_b.id, WEEK)

    # ── derivation: automatic from the schedule ──────────────────────────────
    def test_queue_auto_generates_the_weekly_request(self):
        """EVERYTHING AUTOMATIC: opening the queue materialises the weekly
        request row from the scheduled cost lines — no manual generation."""
        self.assertFalse(
            WeeklyFundRequest.objects.filter(
                responsible_user=self.cceo_a.id, week_start_date=WEEK_START
            ).exists()
        )
        page = self._page(self.pl1_principal)
        wfr = WeeklyFundRequest.objects.get(
            responsible_user=self.cceo_a.id, week_start_date=WEEK_START
        )
        self.assertEqual(wfr.status, "pending_responsible_confirmation")
        self.assertEqual(wfr.total_amount, 300_000)
        card = next(q for q in page["queue"] if q["name"] == "Sarah Ncube")
        self.assertEqual(card["status"], "Awaiting CCEO Send")

    def test_fund_request_requires_activity_budget_lines(self):
        # A supervised CCEO whose activities have NO cost lines produces no
        # queue entry, and approving them is refused (nothing to fund).
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
        self._activity(cceo_c_sp, self._school("SCH-C1"))  # no cost line

        self.assertNotIn("Carol No-Cost", self._queue_names(self.pl1_principal))
        with self.assertRaises(BadRequest):
            svc.approve(self.pl1_principal, cceo_c.id, WEEK)

    def test_week_scoping_excludes_other_weeks(self):
        # A line planned the following week must not join this week's request.
        act = self._activity(self.cceo_a_sp, self._school("SCH-A3"))
        self._cost_line(act, 999_000, planned=WEEK_START + timedelta(days=8))
        detail = self._page(self.pl1_principal, cceo=self.cceo_a.id)["selected"]
        self.assertEqual(detail["total_fmt"], svc._ugx(300_000))

    def test_breakdown_derives_from_planned_activities(self):
        detail = self._page(self.pl1_principal, cceo=self.cceo_a.id)["selected"]
        self.assertEqual(detail["name"], "Sarah Ncube")
        self.assertEqual(detail["total_fmt"], svc._ugx(300_000))
        cats = {r["category"]: r for r in detail["breakdown"]}
        self.assertIn("Staff School Visits", cats)
        self.assertEqual(cats["Staff School Visits"]["qty"], 2)
        self.assertEqual(cats["Staff School Visits"]["total"], svc._ugx(300_000))

    # ── the send gate ────────────────────────────────────────────────────────
    def test_approve_requires_the_cceo_to_send_first(self):
        self._page(self.pl1_principal)  # materialises the pending request
        with self.assertRaises(BadRequest):
            svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)

    def test_sent_request_awaits_approval_in_the_queue(self):
        self._send(self.cceo_a.id)
        page = self._page(self.pl1_principal)
        card = next(q for q in page["queue"] if q["name"] == "Sarah Ncube")
        self.assertEqual(card["status"], "Awaiting Approval")
        detail = self._page(self.pl1_principal, cceo=self.cceo_a.id)["selected"]
        self.assertTrue(detail["can_approve"])

    # ── validation gates ─────────────────────────────────────────────────────
    def test_missing_cost_catalogue_version_blocks_approval(self):
        self._cost_line(self.act_a1, 50_000, catalogue_id=None, key="meal_allowance")
        self._send(self.cceo_a.id)
        with self.assertRaises(BadRequest):
            svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)

    def test_partner_work_never_touches_the_staff_funds(self):
        """Partners are paid directly (MOU 50% advance + clearance), so a
        partner activity — even a malformed one — must neither block the
        staff advance nor appear in its breakdown or totals."""
        act = Activity.objects.create(
            delivery_type="partner",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            responsible_staff_id=self.cceo_a_sp.id,
            fy=FY,
            school=None,  # malformed partner visit: a partner-channel problem
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 7, 8, 9, 0)),
        )
        self._cost_line(act, 80_000)
        self._send(self.cceo_a.id)

        detail = self._page(self.pl1_principal, cceo=self.cceo_a.id)["selected"]
        # Breakdown and request total are staff-only (300k, not 380k)…
        self.assertEqual(detail["total_fmt"], svc._ugx(300_000))
        self.assertNotIn(
            "Partner School Visits",
            {row["category"] for row in detail["breakdown"]},
        )
        # …with the partner money surfaced only as the channel note.
        self.assertEqual(detail["partner_total_fmt"], svc._ugx(80_000))

        # And the malformed partner activity does not block the staff advance.
        svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)
        self.assertEqual(
            WeeklyFundRequest.objects.get(
                responsible_user=self.cceo_a.id, week_start_date=WEEK_START
            ).status,
            "confirmed_for_advance",
        )

    # ── approve / return ─────────────────────────────────────────────────────
    def test_pl_approve_routes_to_accountant_queue(self):
        self._send(self.cceo_a.id)
        svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)
        wfr = WeeklyFundRequest.objects.get(
            responsible_user=self.cceo_a.id, week_start_date=WEEK_START
        )
        self.assertEqual(wfr.status, "confirmed_for_advance")
        self.assertEqual(wfr.total_amount, 300_000)
        # The child advances now sit in the accountant's advance queue.
        self.assertEqual(
            AdvanceRequest.objects.filter(
                responsible_user_id=self.cceo_a.id, status="confirmed_for_advance"
            ).count(),
            2,
        )

    def test_approve_is_not_a_fresh_decision_twice(self):
        self._send(self.cceo_a.id)
        svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)
        with self.assertRaises(BadRequest):
            svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)

    def test_pl_can_return_with_reason(self):
        self._send(self.cceo_a.id)
        svc.return_request(
            self.pl1_principal,
            self.cceo_a.id,
            WEEK,
            {"reason": "Costs look too high", "comment": "Recheck transport rates"},
        )
        wfr = WeeklyFundRequest.objects.get(
            responsible_user=self.cceo_a.id, week_start_date=WEEK_START
        )
        self.assertEqual(wfr.status, "returned_by_pl")
        self.assertTrue(
            AuditLog.objects.filter(
                action="weekly_fund_request.return", actor_id=self.pl1.id
            ).exists()
        )

    def test_return_requires_reason(self):
        self._send(self.cceo_a.id)
        with self.assertRaises(BadRequest):
            svc.return_request(self.pl1_principal, self.cceo_a.id, WEEK, {"reason": ""})

    def test_returned_request_can_be_corrected_and_resent(self):
        self._send(self.cceo_a.id)
        svc.return_request(
            self.pl1_principal, self.cceo_a.id, WEEK, {"reason": "Fix costs"}
        )
        wfr = WeeklyFundRequest.objects.get(
            responsible_user=self.cceo_a.id, week_start_date=WEEK_START
        )
        weekly_service.request_advance(wfr.id, self.cceo_a_principal)
        svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "confirmed_for_advance")

    def test_approve_all_valid_skips_unsubmitted_and_invalid(self):
        # Sarah has sent hers; Dan's is sent but INVALID (partner, no school).
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
        good = self._activity(cceo_d_sp, self._school("SCH-D1"))
        self._cost_line(good, 40_000)
        # Staff-side defect: a budget line with no Cost Catalogue version.
        bad = self._activity(cceo_d_sp, self._school("SCH-D2"))
        self._cost_line(bad, 90_000, catalogue_id=None, key="meal_allowance")

        self._send(self.cceo_a.id)
        self._send(cceo_d.id)

        approved = svc.approve_all_valid(self.pl1_principal, WEEK)
        self.assertEqual(approved, 1)  # only Sarah's valid request

        self.assertEqual(
            WeeklyFundRequest.objects.get(
                responsible_user=self.cceo_a.id, week_start_date=WEEK_START
            ).status,
            "confirmed_for_advance",
        )
        self.assertEqual(
            WeeklyFundRequest.objects.get(
                responsible_user=cceo_d.id, week_start_date=WEEK_START
            ).status,
            "submitted_to_pl",
        )

    # ── accountant routing + disbursement ────────────────────────────────────
    def test_approve_notifies_accountant(self):
        acct = get_user_model().objects.create(
            id="acct-1",
            email="acct@edify.org",
            name="Ada Accounts",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        self._send(self.cceo_a.id)
        svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)
        from apps.notifications.models import Notification

        self.assertTrue(
            Notification.objects.filter(
                recipient_id=acct.id,
                source_event_type="weekly_fund_request_ready",
            ).exists()
        )

    def test_accountant_can_disburse_approved_request(self):
        acct = get_user_model().objects.create(
            id="acct-2",
            email="acct2@edify.org",
            name="Ben Books",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        self._send(self.cceo_a.id)
        svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)
        wfr = WeeklyFundRequest.objects.get(
            responsible_user=self.cceo_a.id, week_start_date=WEEK_START
        )
        weekly_service.disburse(
            wfr.id, {"method": "mobile_money", "reference": "MM-1"}, _Principal(acct)
        )
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "disbursed")

    def test_non_accountant_cannot_disburse(self):
        self._send(self.cceo_a.id)
        svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)
        wfr = WeeklyFundRequest.objects.get(
            responsible_user=self.cceo_a.id, week_start_date=WEEK_START
        )
        with self.assertRaises(Forbidden):
            weekly_service.disburse(wfr.id, {}, self.pl1_principal)

    def test_disburse_requires_an_approved_request(self):
        acct = get_user_model().objects.create(
            id="acct-3",
            email="acct3@edify.org",
            name="Cara Cash",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        wfr = weekly_service.generate_weekly_fund_request(self.cceo_a.id, WEEK)
        with self.assertRaises(BadRequest):
            weekly_service.disburse(wfr.id, {}, _Principal(acct))

    # ── side effects: audit + CCEO To-Do ─────────────────────────────────────
    def test_approval_creates_audit_log(self):
        self._send(self.cceo_a.id)
        svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)
        self.assertTrue(
            AuditLog.objects.filter(
                action="weekly_fund_request.approve", actor_id=self.pl1.id
            ).exists()
        )

    def test_return_creates_cceo_todo(self):
        self._send(self.cceo_a.id)
        titles_before = [t["title"] for t in get_todos(self.cceo_a_principal)["todos"]]
        self.assertNotIn("Fix Fund Request", titles_before)

        svc.return_request(
            self.pl1_principal,
            self.cceo_a.id,
            WEEK,
            {"reason": "Recheck cluster participant counts"},
        )

        # The To-Do is DERIVED from the returned_by_pl status.
        todos = get_todos(self.cceo_a_principal)["todos"]
        fix = next((t for t in todos if t["title"] == "Fix Fund Request"), None)
        self.assertIsNotNone(fix)
        self.assertEqual(fix["priority"], "critical")

    def test_returned_todo_autocloses_on_reapproval(self):
        self._send(self.cceo_a.id)
        svc.return_request(
            self.pl1_principal, self.cceo_a.id, WEEK, {"reason": "Fix costs"}
        )
        self.assertIn(
            "Fix Fund Request",
            [t["title"] for t in get_todos(self.cceo_a_principal)["todos"]],
        )
        wfr = WeeklyFundRequest.objects.get(
            responsible_user=self.cceo_a.id, week_start_date=WEEK_START
        )
        weekly_service.request_advance(wfr.id, self.cceo_a_principal)
        svc.approve(self.pl1_principal, self.cceo_a.id, WEEK)
        self.assertNotIn(
            "Fix Fund Request",
            [t["title"] for t in get_todos(self.cceo_a_principal)["todos"]],
        )
