"""Weekly fund request approval routing — the mandate's finance laws.

CCEO weekly requests route to their supervising PL; PL-owned requests route
to the CD (a PL never approves their own); only an APPROVED request reaches
the accountant queue; returned requests are re-submittable, not dead ends.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import WeeklyFundRequest
from apps.fund_requests.weekly_service import (
    approve_weekly_request,
    generate_weekly_fund_request,
    request_advance,
    return_weekly_request,
)
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


class WeeklyApprovalRoutingTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Routing Region")
        self.district = District.objects.create(name="Routing District", region=self.region)
        self.school = School.objects.create(
            school_id="RT-SCH",
            name="Routing School",
            region=self.region,
            district=self.district,
        )

        def _user(email, name, role):
            u = User.objects.create_user(
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            sp = StaffProfile.objects.create(user=u, title=role)
            return u, sp

        self.cceo, self.cceo_sp = _user("cceo@rt.org", "Ana CCEO", EdifyRole.CCEO.value)
        self.pl, self.pl_sp = _user(
            "pl@rt.org", "Peter PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.other_pl, self.other_pl_sp = _user(
            "pl2@rt.org", "Olga OtherPL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cd, self.cd_sp = _user(
            "cd@rt.org", "Carla CD", EdifyRole.COUNTRY_DIRECTOR.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )

        self.week_start = _monday(date(2026, 7, 6))

    def _wfr(self, owner, amount=100_000, status="pending_responsible_confirmation"):
        return WeeklyFundRequest.objects.create(
            fy="2026",
            week_start_date=self.week_start,
            week_end_date=self.week_start + timedelta(days=6),
            responsible_user=owner.id,
            total_amount=amount,
            status=status,
        )

    def _costed_activity(self, owner):
        act = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=owner.id,
            fy="2026",
            scheduled_date=timezone.make_aware(
                timezone.datetime(2026, 7, 8, 9, 0)
            ),
        )
        ActivityScheduleCostLine.objects.create(
            activity=act,
            cost_setting_key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
            planned_date=date(2026, 7, 8),
            month=7,
            fiscal_year="2026",
            responsible_user=owner.id,
        )
        return act

    # ── Mandatory routing tests ───────────────────────────────────────────────
    def test_cceo_weekly_request_routes_to_pl(self):
        wfr = self._wfr(self.cceo)
        res = request_advance(wfr.id, self.cceo)
        self.assertEqual(res["status"], "submitted_to_pl")
        wfr.refresh_from_db()
        self.assertEqual(wfr.responsible_role, EdifyRole.CCEO.value)

    def test_pl_weekly_request_routes_to_cd(self):
        wfr = self._wfr(self.pl)
        res = request_advance(wfr.id, self.pl)
        self.assertEqual(res["status"], "submitted_to_cd")
        wfr.refresh_from_db()
        self.assertEqual(wfr.responsible_role, EdifyRole.COUNTRY_PROGRAM_LEAD.value)

    def test_pl_owned_activity_generates_weekly_fund_request(self):
        self._costed_activity(self.pl)
        wfr = generate_weekly_fund_request(self.pl.id, self.week_start.isoformat())
        self.assertIsNotNone(wfr)
        self.assertEqual(wfr.responsible_user, self.pl.id)
        self.assertEqual(wfr.total_amount, 50_000)
        self.assertEqual(wfr.lines.count(), 1)

    # ── Approval authority ────────────────────────────────────────────────────
    def test_supervising_pl_approves_cceo_request(self):
        wfr = self._wfr(self.cceo)
        request_advance(wfr.id, self.cceo)
        res = approve_weekly_request(wfr.id, self.pl)
        self.assertEqual(res["status"], "confirmed_for_advance")

    def test_other_pl_cannot_approve_foreign_portfolio(self):
        wfr = self._wfr(self.cceo)
        request_advance(wfr.id, self.cceo)
        with self.assertRaises(Forbidden):
            approve_weekly_request(wfr.id, self.other_pl)

    def test_pl_cannot_approve_own_request(self):
        wfr = self._wfr(self.pl)
        request_advance(wfr.id, self.pl)
        # Even as the routed stage's wrong role, self-approval dies first.
        with self.assertRaises(Forbidden):
            approve_weekly_request(wfr.id, self.pl)

    def test_cd_approves_pl_request(self):
        wfr = self._wfr(self.pl)
        request_advance(wfr.id, self.pl)
        res = approve_weekly_request(wfr.id, self.cd)
        self.assertEqual(res["status"], "confirmed_for_advance")

    def test_pl_cannot_act_at_cd_stage(self):
        wfr = self._wfr(self.pl)
        request_advance(wfr.id, self.pl)
        with self.assertRaises(Forbidden):
            approve_weekly_request(wfr.id, self.other_pl)

    # ── Return → resubmit loop (no dead ends) ────────────────────────────────
    def test_returned_request_can_be_resubmitted(self):
        wfr = self._wfr(self.cceo)
        request_advance(wfr.id, self.cceo)
        with self.assertRaises(BadRequest):
            return_weekly_request(wfr.id, {"reason": ""}, self.pl)
        res = return_weekly_request(wfr.id, {"reason": "Wrong week"}, self.pl)
        self.assertEqual(res["status"], "returned_by_pl")

        res = request_advance(wfr.id, self.cceo)
        self.assertEqual(res["status"], "submitted_to_pl")

    def test_cd_return_goes_back_to_pl_owner(self):
        wfr = self._wfr(self.pl)
        request_advance(wfr.id, self.pl)
        res = return_weekly_request(wfr.id, {"reason": "Costs off"}, self.cd)
        self.assertEqual(res["status"], "returned_by_cd")
        res = request_advance(wfr.id, self.pl)
        self.assertEqual(res["status"], "submitted_to_cd")

    # ── Child advances stay out of the accountant queue until approval ──────
    def test_child_advances_confirm_only_on_approval(self):
        from apps.fund_requests.advance_service import sync_for_activity
        from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequestLine

        act = self._costed_activity(self.cceo)
        sync_for_activity(act, responsible_user_id=self.cceo.id)
        wfr = generate_weekly_fund_request(self.cceo.id, self.week_start.isoformat())

        request_advance(wfr.id, self.cceo)
        adv = AdvanceRequest.objects.get(activity=act)
        self.assertEqual(adv.status, "pending_responsible_confirmation")

        approve_weekly_request(wfr.id, self.pl)
        adv.refresh_from_db()
        self.assertEqual(adv.status, "confirmed_for_advance")
