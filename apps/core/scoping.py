"""
Data-access scope resolution — faithful port of ScopeService.resolveUserScope.

EVERY query that returns operational records must be constrained by the resolved
scope — never return all rows and filter on the client. The scope captures the
role's reach:

  • Country roles (CD, IA, Accountant, Admin) → whole country.
  • RVP → summary-only, scoped to assigned region(s); NO school-level rows.
  • CCEO/PL → own assigned schools (+, for PL, the supervised-staff team lens).
  • Partner → only their own partner.

The capability flags (canViewFinancialData, canApprove, …) gate feature
surfaces. `school_queryset` / `aggregate_school_filter` produce the ORM
constraints matching the legacy schoolWhere / aggregateSchoolWhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from django.db.models import Q

from apps.core.rbac import EdifyRole, Permission, permissions_for_role


COUNTRY_ROLES = {
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.PROGRAM_ACCOUNTANT.value,
    EdifyRole.ADMIN.value,
}
SUMMARY_ONLY_ROLES = {EdifyRole.REGIONAL_VICE_PRESIDENT.value}


@dataclass
class UserScope:
    """The resolved data-access scope for a user + active role."""

    user_id: str
    active_role: str
    permissions: list[str] = field(default_factory=list)
    country_scope: bool = False
    region_ids: list[str] = field(default_factory=list)
    district_ids: list[str] = field(default_factory=list)
    cluster_ids: list[str] = field(default_factory=list)
    school_ids: list[str] = field(default_factory=list)  # union own + team
    own_school_ids: list[str] = field(default_factory=list)
    team_school_ids: list[str] = field(default_factory=list)
    core_school_ids: list[str] = field(default_factory=list)
    staff_ids: list[str] = field(default_factory=list)
    supervised_staff_ids: list[str] = field(default_factory=list)
    partner_ids: list[str] = field(default_factory=list)

    # Capability flags.
    can_view_summary_only: bool = False
    can_view_school_level_detail: bool = True
    can_view_partner_data: bool = False
    can_view_financial_data: bool = False
    can_view_own: bool = False
    can_view_team: bool = False
    can_view_country: bool = False
    can_approve: bool = False
    can_assign: bool = False
    can_export: bool = False


# Sentinel meaning "no rows match" — matches the legacy `['__none__']` idiom.
_NONE = ["__none__"]


def _uniq(items: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for x in items:
        if x and x not in seen:
            seen[x] = None
    return list(seen.keys())


def resolve_user_scope(user) -> UserScope:
    """Resolve the scope for an AuthPrincipal. Defensive about missing apps —
    schools/partners/staff may not exist yet during the build; return an empty
    scope of the right shape so the country/summary-only paths keep working."""
    role = user.active_role
    perms = permissions_for_role(role)
    has = lambda p: p in perms  # noqa: E731

    country_scope = role in COUNTRY_ROLES
    summary_only = role in SUMMARY_ONLY_ROLES

    region_ids: list[str] = []
    district_ids: list[str] = []
    cluster_ids: list[str] = []
    school_ids: list[str] = []
    own_school_ids: list[str] = []
    team_school_ids: list[str] = []
    core_school_ids: list[str] = []
    supervised_staff_ids: list[str] = []
    partner_ids: list[str] = []

    staff_id = user.staff_profile_id

    try:
        from apps.accounts.models import (
            StaffGeographyAssignment,
            StaffSchoolAssignment,
            StaffSupervisorAssignment,
        )
    except Exception:  # noqa: BLE001 - accounts may not be ready in some unit contexts
        StaffGeographyAssignment = StaffSchoolAssignment = StaffSupervisorAssignment = (
            None  # type: ignore
        )

    if summary_only and staff_id and StaffGeographyAssignment:
        # RVP sees summary performance — scope to assigned region(s). No
        # school-level rows (see school_queryset); analytics get country counts.
        geo = StaffGeographyAssignment.objects.filter(
            staff_id=staff_id, region_id__isnull=False
        ).values_list("region_id", flat=True)
        region_ids = _uniq(geo)
    elif country_scope:
        # Country roles are not row-constrained by geography here.
        pass
    elif (
        role in (EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        and staff_id
        and StaffSchoolAssignment
    ):
        from django.utils import timezone
        from apps.accounts.models import TemporaryCoverageAssignment

        now = timezone.now()
        active_coverages = TemporaryCoverageAssignment.objects.filter(
            covering_staff_id=staff_id,
            start_datetime__lte=now,
            end_datetime__gte=now,
            status="active",
        )
        covered_staff_ids = list(
            active_coverages.values_list("original_staff_id", flat=True)
        )

        own_query = Q(staff_id=staff_id)
        if covered_staff_ids:
            own_query |= Q(staff_id__in=covered_staff_ids)

        # Own assigned schools (personal field work).
        own = StaffSchoolAssignment.objects.filter(own_query).values_list(
            "school_id", flat=True
        )
        own_school_ids = _uniq(own)

        # PL also supervises CCEOs — their schools form the TEAM lens (distinct
        # from own, so the three PL layers — own / team / combined — are real).
        has_pl_coverage = False
        if covered_staff_ids:
            from apps.accounts.models import StaffProfile

            has_pl_coverage = StaffProfile.objects.filter(
                id__in=covered_staff_ids,
                user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            ).exists()

        if (
            role == EdifyRole.COUNTRY_PROGRAM_LEAD.value or has_pl_coverage
        ) and StaffSupervisorAssignment:
            supervisor_query = Q(supervisor_id=staff_id)
            if covered_staff_ids:
                supervisor_query |= Q(supervisor_id__in=covered_staff_ids)

            supervisees = StaffSupervisorAssignment.objects.filter(
                supervisor_query
            ).values_list("supervisee_id", flat=True)
            supervised_staff_ids = _uniq(supervisees)
            if supervised_staff_ids and StaffSchoolAssignment:
                team = StaffSchoolAssignment.objects.filter(
                    staff_id__in=supervised_staff_ids
                ).values_list("school_id", flat=True)
                team_school_ids = [s for s in _uniq(team) if s not in own_school_ids]

        school_ids = _uniq([*own_school_ids, *team_school_ids])

        # Derive geography + clusters + core subset from the in-scope schools.
        if school_ids:
            school_model = _get_school_model()
            if school_model is not None:
                schools = school_model.objects.filter(id__in=school_ids).values(
                    "id", "district_id", "region_id", "cluster_id", "school_type"
                )
                district_ids = _uniq([s["district_id"] for s in schools])
                region_ids = _uniq([s["region_id"] for s in schools])
                cluster_ids = _uniq(
                    [s["cluster_id"] for s in schools if s["cluster_id"]]
                )
                core_school_ids = [
                    s["id"] for s in schools if s["school_type"] == "core"
                ]
    elif role == EdifyRole.PROJECT_COORDINATOR.value and staff_id:
        try:
            from apps.projects.models import Project, ProjectSchoolAssignment

            project_ids = list(
                Project.objects.filter(manager_staff_id=staff_id).values_list(
                    "id", flat=True
                )
            )
            own_school_ids = list(
                ProjectSchoolAssignment.objects.filter(
                    project_id__in=project_ids
                ).values_list("school_id", flat=True)
            )
            school_ids = _uniq(own_school_ids)
            if school_ids:
                school_model = _get_school_model()
                if school_model is not None:
                    schools = school_model.objects.filter(id__in=school_ids).values(
                        "id", "district_id", "region_id", "cluster_id", "school_type"
                    )
                    district_ids = _uniq([s["district_id"] for s in schools])
                    region_ids = _uniq([s["region_id"] for s in schools])
                    cluster_ids = _uniq(
                        [s["cluster_id"] for s in schools if s["cluster_id"]]
                    )
                    core_school_ids = [
                        s["id"] for s in schools if s["school_type"] == "core"
                    ]
        except Exception:
            pass
    elif role in (EdifyRole.PARTNER_ADMIN.value, EdifyRole.PARTNER_FIELD_OFFICER.value):
        # Partner users see ONLY their own partner's activities.
        partner_ids = resolve_partner_ids(user)
        if partner_ids:
            try:
                from apps.partners.models import PartnerAssignment

                assigned_schools = list(
                    PartnerAssignment.objects.filter(
                        partner_id__in=partner_ids
                    ).values_list("school_id", flat=True)
                )
                school_ids = _uniq(assigned_schools)
                if school_ids:
                    school_model = _get_school_model()
                    if school_model is not None:
                        schools = school_model.objects.filter(id__in=school_ids).values(
                            "id",
                            "district_id",
                            "region_id",
                            "cluster_id",
                            "school_type",
                        )
                        district_ids = _uniq([s["district_id"] for s in schools])
                        region_ids = _uniq([s["region_id"] for s in schools])
                        cluster_ids = _uniq(
                            [s["cluster_id"] for s in schools if s["cluster_id"]]
                        )
                        core_school_ids = [
                            s["id"] for s in schools if s["school_type"] == "core"
                        ]
            except Exception:
                pass

    return UserScope(
        user_id=user.user_id,
        active_role=role,
        permissions=perms,
        country_scope=country_scope,
        region_ids=region_ids,
        district_ids=district_ids,
        cluster_ids=cluster_ids,
        school_ids=school_ids,
        own_school_ids=own_school_ids,
        team_school_ids=team_school_ids,
        core_school_ids=core_school_ids,
        staff_ids=[staff_id] if staff_id else [],
        supervised_staff_ids=supervised_staff_ids,
        partner_ids=partner_ids,
        can_view_summary_only=summary_only,
        can_view_school_level_detail=not summary_only,
        can_view_partner_data=has(Permission.PARTNER_VIEW.value),
        can_view_financial_data=has(Permission.BUDGET_VIEW_DETAIL.value)
        or has(Permission.PAYMENT_ACT.value),
        can_view_own=bool(own_school_ids) or (not country_scope and not summary_only),
        can_view_team=(role == EdifyRole.COUNTRY_PROGRAM_LEAD.value) or country_scope,
        can_view_country=country_scope,
        can_approve=has(Permission.BUDGET_APPROVE.value)
        or has(Permission.IA_VERIFY.value),
        can_assign=has(Permission.ACTIVITY_ASSIGN.value),
        can_export=has(Permission.EXPORT.value),
    )


def resolve_partner_ids(user) -> list[str]:
    """Resolve the partner id(s) a partner user acts as.

    1) canonical FK — a partner field officer authenticates as Partner.userId.
    2) demo role-bridge fallback — the seed never sets Partner.userId, and the
       FE partner demo user maps by ROLE; pin to the first active partner.
       Disable in production once real linkage exists (PARTNER_ROLE_BRIDGE=false).
    """
    from django.conf import settings

    partner_model = _get_partner_model()
    if partner_model is None:
        return []
    linked = (
        partner_model.objects.filter(user_id=user.user_id, active_status=True)
        .order_by("created_at")
        .first()
    )
    if linked:
        return [linked.id]
    if getattr(settings, "PARTNER_ROLE_BRIDGE", True):
        first = (
            partner_model.objects.filter(active_status=True)
            .order_by("created_at")
            .first()
        )
        if first:
            return [first.id]
    return []


def cluster_in_scope(scope: UserScope, cluster) -> bool:
    """Return whether a cluster is inside an operational user's scope.

    Clusters are assigned and managed at district level.  A CCEO or Program
    Lead who has an assigned school in a district can work the district's
    clusters, even before one of their individual schools has been added to a
    particular cluster.  This mirrors the cluster list and assignment rules;
    keeping the rule here prevents a drawer from offering a cluster that the
    activity service later rejects.
    """
    if scope.country_scope:
        return True
    if getattr(cluster, "id", None) in scope.cluster_ids:
        return True
    return bool(
        getattr(cluster, "district_id", None)
        and cluster.district_id in scope.district_ids
    )


# ── ORM query constraints (legacy schoolWhere / aggregateSchoolWhere) ────────
def school_queryset(scope: UserScope):
    """Return the base queryset for the School model, scope-constrained.

    Summary-only roles (RVP) receive NO school-level rows — they use aggregate
    summaries only. Returns None if the schools app isn't installed yet.
    """
    school_model = _get_school_model()
    if school_model is None:
        return None
    qs = school_model.objects.all()
    if scope.active_role == "CountryDirector":
        from django.conf import settings

        if not getattr(settings, "ALLOW_CD_OPERATIONAL_PLANNING", False):
            return qs.none()
    if scope.country_scope:
        return qs
    if scope.can_view_summary_only:
        return qs.none()
    if scope.school_ids:
        return qs.filter(id__in=scope.school_ids)
    return qs.none()


def aggregate_school_filter(scope: UserScope) -> Q:
    """An ORM Q to apply to aggregate analytics. Summary-only roles see
    country-wide counts (their purpose) but never row-level detail."""
    if scope.country_scope or scope.can_view_summary_only:
        return Q()
    if scope.school_ids:
        return Q(id__in=scope.school_ids)
    return Q(id__in=_NONE)


# ── Lazy model accessors (apps may not be installed during the build) ────────
def _get_school_model():
    try:
        from apps.schools.models import School  # type: ignore

        return School
    except Exception:  # noqa: BLE001
        return None


def _get_partner_model():
    try:
        from apps.partners.models import Partner  # type: ignore

        return Partner
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "UserScope",
    "resolve_user_scope",
    "cluster_in_scope",
    "resolve_partner_ids",
    "school_queryset",
    "aggregate_school_filter",
]
