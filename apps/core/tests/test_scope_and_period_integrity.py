"""Filters narrow an authorized set — they never widen one.

The second tier of the HR / filters / messaging audit. Each test pins a way a
query parameter, an empty scope, or a wrong calendar could hand someone data
or a number they were not entitled to.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
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


class FiscalQuarterTests(TestCase):
    """A calendar quarter is not a fiscal quarter."""

    def test_fund_requests_page_uses_the_canonical_calendar(self):
        import inspect

        from apps.frontend.views import budget_views

        source = inspect.getsource(budget_views)
        self.assertNotIn(
            'f"Q{((month_num - 1) // 3) + 1}"',
            source,
            "this labelled October Q4; the canonical FY calls it Q1, and the "
            "wrong label was fed to get_quarter_date_range()",
        )

    def test_canonical_quarters_are_october_anchored(self):
        from apps.core.fy import get_quarter_for_date

        self.assertEqual(get_quarter_for_date(date(2025, 10, 1)), "Q1")
        self.assertEqual(get_quarter_for_date(date(2026, 1, 1)), "Q2")
        self.assertEqual(get_quarter_for_date(date(2026, 4, 1)), "Q3")
        self.assertEqual(get_quarter_for_date(date(2026, 7, 1)), "Q4")


class FundAllocationScopeTests(TestCase):
    """The roster carries every staff member's monthly money."""

    def test_service_without_a_principal_returns_nothing(self):
        from apps.budget.allocation_service import MonthlyFundAllocationService

        qs = MonthlyFundAllocationService._scope_staff(None, StaffProfile.objects.all())
        self.assertEqual(qs.count(), 0, "no principal must not mean no limit")

    def test_service_requires_a_principal_parameter(self):
        import inspect

        from apps.budget.allocation_service import MonthlyFundAllocationService

        params = inspect.signature(
            MonthlyFundAllocationService.get_monthly_allocation
        ).parameters
        self.assertIn("principal", params)


class ClusterReadScopeTests(TestCase):
    """Five cluster read services accepted a principal and ignored it."""

    def test_every_cluster_read_goes_through_the_scoped_resolver(self):
        import inspect

        from apps.clusters import services

        for fn in (
            services.cluster_schools,
            services.cluster_detail,
            services.cluster_weakest_interventions,
            services.cluster_intervention_summary,
            services.cluster_activity_impact,
        ):
            source = inspect.getsource(fn)
            self.assertIn(
                "_scoped_cluster(cluster_id, principal)",
                source,
                f"{fn.__name__} must resolve the cluster through the scope guard",
            )


class PlanningIntelligenceScopeTests(TestCase):
    def test_panel_uses_the_scoped_school_queryset(self):
        import inspect

        from apps.frontend.views import planning_views

        source = inspect.getsource(planning_views.planning_intelligence_view)
        self.assertIn("school_queryset(resolve_user_scope(request.user))", source)


class FundRequestScopeFailsClosedTests(TestCase):
    """`and scope.staff_ids` skipped the narrowing for anyone without a
    StaffProfile and fell through to the unfiltered .all()."""

    def test_scope_narrowing_is_not_gated_on_a_truthy_staff_id_set(self):
        import inspect

        from apps.frontend.views import budget_views

        source = inspect.getsource(budget_views)
        self.assertNotIn("if not scope.country_scope and scope.staff_ids:", source)


class SupervisedTeamExcludesDepartedStaffTests(TestCase):
    """Offboarding soft-deletes the profile and leaves the link standing."""

    def test_soft_deleted_supervisee_leaves_the_team(self):
        from django.utils import timezone

        from apps.core.scoping import resolve_user_scope

        pl = _user("sd-pl@t.org", "PL One", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        sp_pl = StaffProfile.objects.create(user=pl, country="Uganda")
        gone = _user("sd-gone@t.org", "Departed", EdifyRole.CCEO.value)
        sp_gone = StaffProfile.objects.create(user=gone, country="Uganda")
        StaffSupervisorAssignment.objects.create(supervisee=sp_gone, supervisor=sp_pl)

        scope = resolve_user_scope(pl)
        self.assertIn(sp_gone.id, scope.supervised_staff_ids)

        sp_gone.deleted_at = timezone.now()
        sp_gone.save(update_fields=["deleted_at"])

        scope = resolve_user_scope(pl)
        self.assertNotIn(
            sp_gone.id,
            scope.supervised_staff_ids,
            "a departed employee must not stay in a live supervisor's scope",
        )


class OnboardingStateWriterTests(TestCase):
    """Nothing outside the demo seeder ever moved a profile off 'pending', and
    coverage eligibility filters on 'active'."""

    def test_accepting_an_invite_activates_the_staff_profile(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.accounts.models import UserInvitation
        from apps.accounts.auth_services import set_password
        from apps.core.security import hash_token

        u = User.objects.create_user(
            email="onb@t.org",
            name="New Hire",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=False,
            status="pending_invited",
        )
        profile = StaffProfile.objects.create(user=u, country="Uganda")
        self.assertEqual(profile.onboarding_state, "pending")

        inviter = _user("onb-admin@t.org", "Admin One", EdifyRole.ADMIN.value)
        inv = UserInvitation.objects.create(
            user=u,
            invited_by=inviter,
            token_hash=hash_token("tok-123"),
            expires_at=timezone.now() + timedelta(days=3),
        )
        set_password("tok-123", "Str0ng!Passw0rd42", "Str0ng!Passw0rd42")

        profile.refresh_from_db()
        self.assertEqual(
            profile.onboarding_state,
            "active",
            "an employee stuck at 'pending' can never be nominated to cover leave",
        )
        self.assertIsNotNone(inv.id)


class PublicHolidayWriteMethodTests(TestCase):
    """Holidays are an input to the charged-days calculation."""

    def test_holidays_are_not_mutated_over_get(self):
        import inspect

        from apps.frontend.views import leave_views

        source = inspect.getsource(leave_views.leave_policies_view)
        self.assertNotIn('request.GET.get("delete_holiday")', source)
        self.assertNotIn('request.GET.get("action") == "add_holiday"', source)

    def test_template_posts_with_a_csrf_token(self):
        from pathlib import Path

        from django.conf import settings

        html = Path(
            settings.BASE_DIR, "templates/pages/leave/leave_policies.html"
        ).read_text()
        self.assertNotIn('href="?delete_holiday=', html)
        self.assertIn("csrf_token", html)
