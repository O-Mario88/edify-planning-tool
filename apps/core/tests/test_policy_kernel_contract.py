"""The Policy Kernel contract.

Authority in this platform was defined in four places that had drifted apart:
the RBAC matrix, the page-permission map, ad-hoc role lists in the service
layer, and bare role-string comparisons inside individual views. The matrix is
the source of truth; these tests fail the build when another layer contradicts
it.

Each assertion below encodes a rule someone can otherwise silently break by
adding a role to a page set or a role string to a service.
"""

from __future__ import annotations

import inspect

from django.test import TestCase

from apps.core.navigation import PAGE_PERMISSIONS, get_user_role_slug
from apps.core.rbac import ROLE_PERMISSIONS, EdifyRole, Permission, permissions_for_role


# Role slug (navigation) → EdifyRole (matrix). The navigation layer speaks in
# short slugs; the matrix speaks in role values. Every mapping must be total or
# the two layers cannot be compared at all.
SLUG_TO_ROLE = {
    "ADMIN": EdifyRole.ADMIN,
    "CCEO": EdifyRole.CCEO,
    "PL": EdifyRole.COUNTRY_PROGRAM_LEAD,
    "CD": EdifyRole.COUNTRY_DIRECTOR,
    "IA": EdifyRole.IMPACT_ASSESSMENT,
    "RVP": EdifyRole.REGIONAL_VICE_PRESIDENT,
    "HR": EdifyRole.HUMAN_RESOURCES,
    "ACCOUNTANT": EdifyRole.PROGRAM_ACCOUNTANT,
    "PARTNER": EdifyRole.PARTNER_ADMIN,
    "PROJECT_COORDINATOR": EdifyRole.PROJECT_COORDINATOR,
}

# Pages whose access is governed by a permission. A role in the page set that
# lacks the permission is drift — it can open a page it cannot use, or worse,
# use it without the matrix recording that it may.
PAGE_REQUIRED_PERMISSION = {
    "cost_settings": Permission.COST_SETTINGS_MANAGE,
    "impact_analytics": Permission.ANALYTICS_VIEW,
    "analytics": Permission.ANALYTICS_VIEW,
    "cd_analytics": Permission.ANALYTICS_VIEW,
    "pl_analytics": Permission.ANALYTICS_VIEW,
    "country_budget": Permission.BUDGET_VIEW_SUMMARY,
}

# Deliberately open surfaces: the page admits everyone and the *service* scopes
# the data per role. Listed explicitly so "open to all" stays a decision on the
# record rather than an omission nobody revisits.
INTENTIONALLY_UNGATED_PAGES = {
    "ssa_performance": "service scopes by school/region/partner/project before "
    "computing any metric",
    "dashboard": "role-routed inside the view",
    "todos": "derived from the caller's own workflow state",
    "search": "each result section is scope-constrained in the view",
    "calendar": "view applies its own role-to-staff audience rule",
    "partners": "partner rows filtered by scope.can_view_partner_data",
    "notifications": "per-user inbox",
    "messages": "per-user inbox",
    "settings": "personal",
    "help": "personal",
    "personal_time_off": "personal",
    "leave_requests": "personal",
    "leave_calendar": "personal",
    "public_holidays": "reference data",
    "partner_detail": "partner rows filtered by scope",
}


class RoleSlugMappingContract(TestCase):
    def test_every_navigation_slug_maps_to_a_real_role(self):
        for slug, role in SLUG_TO_ROLE.items():
            self.assertIn(role, ROLE_PERMISSIONS, f"{slug} maps to an unknown role")

    def test_role_slug_resolution_is_stable(self):
        class _U:
            is_authenticated = True

            def __init__(self, role):
                self.active_role = role

        for slug, role in SLUG_TO_ROLE.items():
            if role is EdifyRole.PARTNER_ADMIN:
                continue  # two partner roles collapse to one slug by design
            self.assertEqual(
                get_user_role_slug(_U(role.value)),
                slug,
                f"{role.value} should resolve to slug {slug}",
            )


class PagePermissionContract(TestCase):
    def test_page_sets_do_not_grant_access_the_matrix_withholds(self):
        failures = []
        for page, permission in PAGE_REQUIRED_PERMISSION.items():
            allowed = PAGE_PERMISSIONS.get(page, set())
            for slug in allowed:
                role = SLUG_TO_ROLE.get(slug)
                if role is None or role is EdifyRole.ADMIN:
                    continue
                if permission.value not in permissions_for_role(role):
                    failures.append(
                        f"page '{page}' admits {slug} but the matrix withholds "
                        f"{permission.value}"
                    )
        self.assertEqual(failures, [], "\n".join(failures))

    def test_all_roles_pages_are_an_explicit_decision(self):
        """A page open to every role must be listed as intentional. This stops
        an ALL_ROLES entry from being added casually to a surface that should
        have been gated."""
        from apps.core.navigation import ALL_ROLES

        for page, allowed in PAGE_PERMISSIONS.items():
            if allowed == ALL_ROLES:
                self.assertIn(
                    page,
                    INTENTIONALLY_UNGATED_PAGES,
                    f"page '{page}' is open to every role but is not recorded as "
                    "an intentional exception — gate it or document why",
                )

    def test_every_page_key_has_a_permission_entry(self):
        """A page with no entry falls through to `can_view_page`'s secure
        default (deny) — fine — but a *typo'd* key silently denies a page that
        was meant to be open. Every key referenced by the sidebar must exist."""
        from apps.core.navigation import SIDEBAR_ITEMS

        for section in SIDEBAR_ITEMS:
            for item in section["items"]:
                self.assertIn(
                    item["page_key"],
                    PAGE_PERMISSIONS,
                    f"sidebar item '{item['label']}' references unknown page key "
                    f"'{item['page_key']}'",
                )


class CountryMoneyChainContract(TestCase):
    """The country envelope chain used to run entirely on role strings, so the
    matrix could not describe who approves the country's money."""

    def test_cd_may_submit_the_country_envelope(self):
        self.assertIn(
            Permission.COUNTRY_BUDGET_SUBMIT.value,
            permissions_for_role(EdifyRole.COUNTRY_DIRECTOR),
        )

    def test_rvp_may_approve_the_country_envelope(self):
        self.assertIn(
            Permission.COUNTRY_BUDGET_APPROVE.value,
            permissions_for_role(EdifyRole.REGIONAL_VICE_PRESIDENT),
        )

    def test_cd_may_clear_escalated_advances(self):
        self.assertIn(
            Permission.FUND_REQUEST_APPROVE_ESCALATED.value,
            permissions_for_role(EdifyRole.COUNTRY_DIRECTOR),
        )

    def test_field_approval_stays_with_the_field_chain(self):
        """budget.approve is the CCEO/PL right. Leadership must not acquire it
        as a side effect of gaining country-envelope authority."""
        for role in (EdifyRole.COUNTRY_DIRECTOR, EdifyRole.REGIONAL_VICE_PRESIDENT):
            self.assertNotIn(
                Permission.BUDGET_APPROVE.value,
                permissions_for_role(role),
                f"{role.value} must not hold the field chain's budget.approve",
            )
        for role in (EdifyRole.CCEO, EdifyRole.COUNTRY_PROGRAM_LEAD):
            self.assertIn(Permission.BUDGET_APPROVE.value, permissions_for_role(role))

    def test_rvp_cannot_submit_and_approve_the_same_envelope(self):
        """Separation of duties: one role must never hold both ends."""
        rvp = permissions_for_role(EdifyRole.REGIONAL_VICE_PRESIDENT)
        self.assertNotIn(Permission.COUNTRY_BUDGET_SUBMIT.value, rvp)
        cd = permissions_for_role(EdifyRole.COUNTRY_DIRECTOR)
        self.assertNotIn(Permission.COUNTRY_BUDGET_APPROVE.value, cd)


class ExportCapabilityContract(TestCase):
    """`can_export` kept its own role list, which disagreed with the matrix in
    both directions."""

    def test_can_export_is_derived_from_the_matrix(self):
        from apps.core.permissions import RolePermissionService

        source = inspect.getsource(RolePermissionService.can_export)
        self.assertNotIn(
            "RegionalVicePresident",
            source,
            "can_export must derive from the EXPORT permission, not a role list",
        )

    def test_export_holders_agree_across_layers(self):
        from apps.core.permissions import RolePermissionService

        class _U:
            def __init__(self, role):
                self.active_role = role

        for role in EdifyRole:
            expected = Permission.EXPORT.value in permissions_for_role(role)
            actual = RolePermissionService.can_export(_U(role.value), "any")
            self.assertEqual(
                expected,
                actual,
                f"{role.value}: matrix says export={expected}, "
                f"can_export says {actual}",
            )


class SummaryOnlyDoctrineContract(TestCase):
    """The RVP is a summary audience. Its doctrine was violated in both
    directions — dead-end empty pages one way, per-staff detail the other."""

    def test_rvp_holds_no_operational_write_permission(self):
        rvp = permissions_for_role(EdifyRole.REGIONAL_VICE_PRESIDENT)
        for forbidden in (
            Permission.PLANNING_CREATE,
            Permission.ACTIVITY_ASSIGN,
            Permission.ACTIVITY_COMPLETE,
            Permission.SCHOOL_EDIT,
            Permission.CLUSTER_ASSIGN,
            Permission.IA_VERIFY,
            Permission.PAYMENT_ACT,
            Permission.SCHOOL_DIRECTORY_VIEW,
        ):
            self.assertNotIn(
                forbidden.value,
                rvp,
                f"RVP must not hold {forbidden.value} — it is a summary role",
            )

    def test_cd_does_not_hold_the_operational_directory(self):
        self.assertNotIn(
            Permission.SCHOOL_DIRECTORY_VIEW.value,
            permissions_for_role(EdifyRole.COUNTRY_DIRECTOR),
        )

    def test_ssa_confirmation_is_ia_authority_alone(self):
        holders = [
            role.value
            for role in EdifyRole
            if Permission.IA_VERIFY.value in permissions_for_role(role)
        ]
        self.assertEqual(
            sorted(holders),
            sorted([EdifyRole.IMPACT_ASSESSMENT.value, EdifyRole.ADMIN.value]),
            "Only Impact Assessment (and Admin) may confirm SSA records",
        )


class ScopeDoctrineContract(TestCase):
    """One definition of what a role can reach, used by every surface."""

    def test_summary_only_roles_are_declared_once(self):
        from apps.core.scoping import COUNTRY_ROLES, SUMMARY_ONLY_ROLES

        self.assertEqual(
            SUMMARY_ONLY_ROLES, {EdifyRole.REGIONAL_VICE_PRESIDENT.value}
        )
        self.assertNotIn(
            EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            COUNTRY_ROLES,
            "a role cannot be both country-scoped and summary-only",
        )

    def test_analytics_surfaces_share_one_school_scope_helper(self):
        """SSA performance, impact analytics and the analytics rollups each had
        their own copy of the scope rule, and the copies disagreed."""
        import apps.analytics.impact_engine as impact
        import apps.analytics.services as analytics_services
        import apps.analytics.ssa_performance_service as ssa_perf

        for module, fn_name in (
            (ssa_perf, "_scoped_schools"),
            (impact, "_scoped_schools"),
            (analytics_services, "_scoped_schools"),
        ):
            source = inspect.getsource(getattr(module, fn_name))
            self.assertIn(
                "scoped_school_queryset",
                source,
                f"{module.__name__}.{fn_name} must use the shared scope helper",
            )
