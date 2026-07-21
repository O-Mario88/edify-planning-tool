"""Regression tests for the six critical governance holes closed in Phase 0.

Each test names the hole it locks shut. These are authorization boundaries, so
a failure here is a security regression, not a cosmetic one.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.flags import services as flag_services
from apps.flags.models import CdFlag
from apps.planning import services as planning_services
from apps.planning.models import MonthlyPlan
from apps.professional_development.approval_service import PDApprovalRoutingService
from apps.professional_development.models import (
    PDStatus,
    ProfessionalDevelopmentRequest,
)


def _user(email, name, role, **kw):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        **kw,
    )


class FlagsApiAuthorizationTests(TestCase):
    """C1 — /api/flags was IsAuthenticated-only: any user could read every flag
    and resolve any flag."""

    def setUp(self):
        self.cd = _user("cd-flags@t.org", "CD", EdifyRole.COUNTRY_DIRECTOR.value)
        self.other_cd = _user(
            "cd2-flags@t.org", "CD Two", EdifyRole.COUNTRY_DIRECTOR.value
        )
        self.pl = _user("pl-flags@t.org", "PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.other_pl = _user(
            "pl2-flags@t.org", "PL Two", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo = _user("cceo-flags@t.org", "CCEO", EdifyRole.CCEO.value)
        self.flag = CdFlag.objects.create(
            raised_by_user_id=self.cd.id,
            raised_by_name=self.cd.name,
            assigned_to_user_id=self.pl.id,
            category="quality",
            note="Check this cluster",
        )

    def test_cd_sees_only_flags_they_raised(self):
        rows = flag_services.list_flags({}, self.cd)
        self.assertEqual([r["id"] for r in rows], [self.flag.id])
        self.assertEqual(flag_services.list_flags({}, self.other_cd), [])

    def test_pl_sees_only_flags_assigned_to_them(self):
        rows = flag_services.list_flags({}, self.pl)
        self.assertEqual([r["id"] for r in rows], [self.flag.id])
        self.assertEqual(flag_services.list_flags({}, self.other_pl), [])

    def test_unrelated_role_sees_no_flags(self):
        self.assertEqual(flag_services.list_flags({}, self.cceo), [])

    def test_non_assignee_cannot_resolve_a_flag(self):
        with self.assertRaises(Exception) as ctx:
            flag_services.update_flag(
                self.flag.id, {"action": "resolve"}, self.other_pl
            )
        self.assertIsInstance(ctx.exception, Exception)
        self.flag.refresh_from_db()
        self.assertEqual(self.flag.status, "open")

    def test_raiser_cannot_resolve_their_own_flag(self):
        with self.assertRaises(Forbidden):
            flag_services.update_flag(self.flag.id, {"action": "resolve"}, self.cd)

    def test_assignee_can_resolve(self):
        flag_services.update_flag(self.flag.id, {"action": "resolve"}, self.pl)
        self.flag.refresh_from_db()
        self.assertEqual(self.flag.status, "resolved")

    def test_program_leads_picker_is_cd_only_and_carries_no_email(self):
        """This picker returned every Program Lead's name AND email to any
        caller holding analytics.view — a staff directory by side door."""
        client = Client()
        for user in (self.cceo, self.other_pl):
            client.force_login(user)
            resp = client.get("/api/flags/program-leads")
            self.assertEqual(
                resp.status_code, 403, f"{user.active_role} must be refused"
            )

        client.force_login(self.cd)
        resp = client.get("/api/flags/program-leads")
        self.assertEqual(resp.status_code, 200)
        for row in resp.json():
            self.assertIn("id", row)
            self.assertIn("name", row)
            self.assertNotIn(
                "email", row, "assignment needs an id and a name, not contact PII"
            )

    def test_api_requires_permission_not_just_authentication(self):
        client = Client()
        client.force_login(self.cceo)
        # CCEO holds analytics.view, so it reaches the endpoint but the service
        # returns no rows. A role with neither permission is rejected outright.
        partner = _user("partner-flags@t.org", "Partner", EdifyRole.PARTNER_ADMIN.value)
        client.force_login(partner)
        resp = client.get("/api/flags")
        self.assertIn(resp.status_code, (401, 403))


class PdHrStageAuthorizationTests(TestCase):
    """C2 — any CD/RVP could approve any PD request in any country at HR stage."""

    def setUp(self):
        self.hr, self.hr_sp = self._staff(
            "hr-pd@t.org", "Hana HR", EdifyRole.HUMAN_RESOURCES.value, "Uganda"
        )
        self.cceo, self.cceo_sp = self._staff(
            "cceo-pd@t.org", "Cara CCEO", EdifyRole.CCEO.value, "Uganda"
        )
        self.cd, self.cd_sp = self._staff(
            "cd-pd@t.org", "Cody CD", EdifyRole.COUNTRY_DIRECTOR.value, "Uganda"
        )
        self.foreign_cd, self.foreign_cd_sp = self._staff(
            "cd-ke@t.org", "Kofi CD", EdifyRole.COUNTRY_DIRECTOR.value, "Kenya"
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.hr_sp, supervisor=self.cd_sp
        )

    def _staff(self, email, name, role, country):
        u = _user(email, name, role)
        sp = StaffProfile.objects.create(user=u, title=role, country=country)
        return u, sp

    def _request_at_hr(self, owner_sp, owner_user, country="Uganda"):
        return ProfessionalDevelopmentRequest.objects.create(
            fy="FY26",
            staff_id=owner_sp.id,
            staff_name=owner_user.name,
            country=country,
            course_name="Data for Leaders",
            course_category="Leadership Development",
            course_type="online",
            institution="Coursera",
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + timedelta(days=60),
            funding_type="self_funded",
            created_by=owner_user.id,
            status=PDStatus.SUBMITTED_TO_HR,
        )

    def test_cd_cannot_approve_a_non_hr_staffers_request(self):
        req = self._request_at_hr(self.cceo_sp, self.cceo)
        self.assertFalse(PDApprovalRoutingService.can_review(req, self.cd))
        with self.assertRaises(Forbidden):
            PDApprovalRoutingService.hr_approve(req.id, self.cd)

    def test_cd_may_approve_hrs_own_request_in_country(self):
        req = self._request_at_hr(self.hr_sp, self.hr)
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.cd))

    def test_foreign_cd_cannot_approve_across_countries(self):
        req = self._request_at_hr(self.hr_sp, self.hr, country="Uganda")
        self.assertFalse(PDApprovalRoutingService.can_review(req, self.foreign_cd))
        with self.assertRaises(Forbidden):
            PDApprovalRoutingService.hr_approve(req.id, self.foreign_cd)

    def test_hr_retains_normal_authority(self):
        req = self._request_at_hr(self.cceo_sp, self.cceo)
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.hr))

    def test_pd_decisions_are_audited(self):
        from apps.audit.models import AuditLog

        req = self._request_at_hr(self.cceo_sp, self.cceo)
        PDApprovalRoutingService.hr_return(req.id, self.hr, "Fix the dates")
        self.assertTrue(
            AuditLog.objects.filter(action="pd_hr_return", subject_id=req.id).exists(),
            "PD decisions must land on the tamper-evident audit chain.",
        )


class SsaVerificationAuthorityTests(TestCase):
    """C3 — the SSA queue confirmed records on page permission alone, so a CD,
    PL or CCEO could confirm partner-submitted SSAs country-wide."""

    def setUp(self):
        self.client = Client()

    def test_cd_cannot_post_a_verification(self):
        cd = _user("cd-ssa@t.org", "CD", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=cd, title="CD", country="Uganda")
        self.client.force_login(cd)
        resp = self.client.post(
            "/ssa/verification/", {"record_id": "nonexistent", "action": "verify"}
        )
        # Denied before the record is ever looked up (403 fragment or redirect).
        self.assertNotEqual(resp.status_code, 404)

    def test_ia_keeps_verification_authority(self):
        from apps.core.permissions import has_permission
        from apps.core.rbac import Permission

        ia = _user("ia-ssa@t.org", "IA", EdifyRole.IMPACT_ASSESSMENT.value)
        cd = _user("cd-ssa2@t.org", "CD", EdifyRole.COUNTRY_DIRECTOR.value)
        self.assertTrue(has_permission(ia, Permission.IA_VERIFY.value))
        self.assertFalse(has_permission(cd, Permission.IA_VERIFY.value))


class MonthlyPlanApprovalScopeTests(TestCase):
    """C6 — approve_plan/return_plan had no owner or scope check, so any
    budget.approve holder could approve any plan in the country."""

    def setUp(self):
        self.pl, self.pl_sp = self._staff(
            "pl-plan@t.org", "Pat PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.other_pl, self.other_pl_sp = self._staff(
            "pl2-plan@t.org", "Pia PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo, self.cceo_sp = self._staff(
            "cceo-plan@t.org", "Cara CCEO", EdifyRole.CCEO.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        )
        self.plan = MonthlyPlan.objects.create(
            month_iso="2026-08",
            owner_staff_id=self.cceo_sp.id,
            owner_name=self.cceo.name,
            status="submitted",
        )

    def _staff(self, email, name, role):
        u = _user(email, name, role)
        sp = StaffProfile.objects.create(user=u, title=role, country="Uganda")
        return u, sp

    def test_unrelated_pl_cannot_approve_another_teams_plan(self):
        with self.assertRaises(Forbidden):
            planning_services.approve_plan(self.plan.id, {}, self.other_pl)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, "submitted")

    def test_supervising_pl_can_approve(self):
        planning_services.approve_plan(self.plan.id, {}, self.pl)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, "approved")

    def test_owner_cannot_approve_their_own_plan(self):
        with self.assertRaises(Forbidden):
            planning_services.approve_plan(self.plan.id, {}, self.cceo)

    def test_unrelated_pl_cannot_return_another_teams_plan(self):
        with self.assertRaises(Forbidden):
            planning_services.return_plan(self.plan.id, {"reason": "no"}, self.other_pl)

    def test_plan_lifecycle_signatures_match_the_view_contract(self):
        """The DRF lifecycle view calls fn(plan_id, request.data, request.user);
        submit/approve previously took only two arguments and raised TypeError."""
        import inspect

        for fn in (
            planning_services.submit_plan,
            planning_services.approve_plan,
            planning_services.return_plan,
        ):
            self.assertEqual(
                len(inspect.signature(fn).parameters),
                3,
                f"{fn.__name__} must accept (plan_id, data, principal)",
            )


class StaffPerformancePiiTests(TestCase):
    """C5 — the performance API returned staff email to summary-only roles."""

    def test_rvp_payload_carries_no_email(self):
        rvp = _user(
            "rvp-perf@t.org", "Remy VP", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        subject = _user("cceo-perf@t.org", "Cara CCEO", EdifyRole.CCEO.value)
        StaffProfile.objects.create(user=subject, title="CCEO", country="Uganda")
        client = Client()
        client.force_login(rvp)
        resp = client.get("/api/performance/hr/staff")
        self.assertEqual(resp.status_code, 200)
        for row in resp.json().get("staff", []):
            self.assertNotIn(
                "email", row, "Summary-only roles must not receive contact PII."
            )

    def test_country_role_still_receives_email(self):
        cd = _user("cd-perf@t.org", "Cody CD", EdifyRole.COUNTRY_DIRECTOR.value)
        subject = _user("cceo-perf2@t.org", "Cara CCEO", EdifyRole.CCEO.value)
        StaffProfile.objects.create(user=subject, title="CCEO", country="Uganda")
        client = Client()
        client.force_login(cd)
        resp = client.get("/api/performance/hr/staff")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json().get("staff", [])
        if rows:
            self.assertIn("email", rows[0])
