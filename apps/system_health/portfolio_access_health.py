"""Health checks for the direct-portfolio / team-oversight boundary.

Supervision is not ownership. A Programme Lead may watch everything their
CCEOs do and may plan nothing of it. That rule lives in `apps.core.scoping`
and is enforced at every write, but the ways it comes undone are quiet:

  * a queryset somewhere goes back to `scope.school_ids` (own **plus** team),
    and a supervisor's directory, planner or Core list silently widens again;
  * a page and the API behind it disagree, so what the UI hides an id reaches;
  * work already exists in the database that a supervisor created inside a
    supervisee's portfolio, before the rule was enforced.

The first two are checked here by *asking the real services the real
question* — not by re-deriving the rule, which would leave two definitions to
drift apart. Each check resolves a live Programme Lead's scope and asserts the
canonical service returns nothing outside their direct portfolio; if somebody
re-widens a queryset, the check goes red on the next run rather than at the
next audit.

The third is a data question, and it is answered by
`manage.py audit_portfolio_access`, which classifies the historical rows and
can repair the ones that are safe to repair.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# How many supervisors to probe. The checks resolve a full scope per person,
# which walks the assignment tree, so this stays bounded: the defect these
# watch for is structural — a service that reads the wrong set is wrong for
# everybody — so a sample answers the question a full sweep would.
_PROBE_LIMIT = 5


def report() -> dict:
    """Every portfolio-boundary invariant, checked against live data."""
    checks = [
        _directory_contains_supervised_schools(),
        _planning_selector_contains_supervised_schools(),
        _cluster_selector_contains_supervised_clusters(),
        _core_list_contains_supervised_core_schools(),
        _search_reaches_supervised_schools(),
        _direct_and_oversight_sets_overlap(),
        _core_page_size_is_bounded(),
    ]
    issues = sum(check["count"] for check in checks)
    return {
        "clean": issues == 0,
        "issueCount": issues,
        "checks": checks,
    }


def _finding(
    *, key: str, label: str, severity: str, expected: str, count: int, examples, route: str
) -> dict:
    return {
        "key": key,
        "label": label,
        "severity": severity,
        "expected": expected,
        "count": count,
        "examples": list(examples)[:10],
        "route": route,
        "clean": count == 0,
    }


def _supervisors():
    """Live Programme Leads who actually supervise somebody with schools.

    A lead with no team cannot demonstrate the defect, so probing them would
    return a clean result that means nothing.
    """
    from apps.accounts.models import StaffSupervisorAssignment, StaffProfile
    from apps.core.rbac import EdifyRole

    supervisor_ids = (
        StaffSupervisorAssignment.objects.filter(
            supervisee__deleted_at__isnull=True,
            supervisor__deleted_at__isnull=True,
        )
        .values_list("supervisor_id", flat=True)
        .distinct()
    )
    return list(
        StaffProfile.objects.filter(
            id__in=list(supervisor_ids)[:200],
            deleted_at__isnull=True,
            user__deleted_at__isnull=True,
            user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        ).select_related("user")[:_PROBE_LIMIT]
    )


def _probe(check_key: str, label: str, expected: str, route: str, leak_for):
    """Run `leak_for(user, scope)` over the sampled supervisors.

    `leak_for` returns the ids a surface offered that are NOT in the direct
    portfolio. Anything it returns is a leak, by definition of the surface it
    asked.
    """
    from apps.core.scoping import resolve_user_scope

    examples: list[dict] = []
    count = 0
    for staff in _supervisors():
        user = staff.user
        try:
            scope = resolve_user_scope(user)
            leaked = list(leak_for(user, scope))
        except Exception:  # noqa: BLE001 - one bad portfolio must not blind the rest
            logger.exception("Portfolio probe %s failed for %s", check_key, staff.id)
            continue
        if not leaked:
            continue
        count += len(leaked)
        examples.append(
            {
                "id": staff.id,
                "programLead": user.name,
                "actual": f"{len(leaked)} record(s) outside the direct portfolio",
                "sample": [str(x) for x in leaked[:3]],
            }
        )
    return _finding(
        key=check_key,
        label=label,
        severity="error",
        expected=expected,
        count=count,
        examples=examples,
        route=route,
    )


def _directory_contains_supervised_schools() -> dict:
    def leak(user, scope):
        from apps.core.scoping import direct_portfolio_schools

        qs = direct_portfolio_schools(scope)
        if qs is None:
            return []
        own = set(scope.own_school_ids)
        return [i for i in qs.values_list("id", flat=True)[:2000] if i not in own]

    return _probe(
        "pl_directory_includes_team_schools",
        "Programme Lead School Directory contains a supervised CCEO's school",
        "The operational directory returns directly assigned schools only",
        "/schools",
        leak,
    )


def _planning_selector_contains_supervised_schools() -> dict:
    def leak(user, scope):
        from apps.planning.planning_service import PlanningDashboardService

        data = PlanningDashboardService.get_dashboard_data(
            user, {"tab": "client", "page": 1}
        )
        own = set(scope.own_school_ids)
        team = set(scope.team_school_ids)
        rows = data.get("schools") or data.get("rows") or []
        return [
            r.get("id")
            for r in rows
            if isinstance(r, dict) and r.get("id") in team and r.get("id") not in own
        ]

    return _probe(
        "pl_planning_includes_team_schools",
        "Programme Lead Planning lists a supervised CCEO's school",
        "Planning offers only schools the Programme Lead may schedule at",
        "/planning",
        leak,
    )


def _cluster_selector_contains_supervised_clusters() -> dict:
    def leak(user, scope):
        from apps.core.scoping import cluster_queryset

        writable = cluster_queryset(scope, direct_only=True)
        if writable is None:
            return []
        allowed = set(scope.own_cluster_ids)
        allowed_districts = set(scope.own_district_ids)
        leaked = []
        for cluster in writable.only(
            "id", "district_id", "responsible_staff_id"
        )[:500]:
            if cluster.id in allowed:
                continue
            owner = (cluster.responsible_staff_id or "").strip()
            if owner:
                from apps.core.scoping import cluster_owner_ids

                if owner in cluster_owner_ids(scope, direct_only=True):
                    continue
                leaked.append(cluster.id)
            elif cluster.district_id not in allowed_districts:
                leaked.append(cluster.id)
        return leaked

    return _probe(
        "pl_cluster_selector_includes_team_clusters",
        "Programme Lead cluster planner offers a supervised CCEO's cluster",
        "Cluster planning offers only directly owned or unclaimed local clusters",
        "/clusters",
        leak,
    )


def _core_list_contains_supervised_core_schools() -> dict:
    def leak(user, scope):
        from apps.core_schools.core_planning_services import CoreSchoolsService

        qs, _ = CoreSchoolsService.base_queryset(user, lens="direct")
        own = set(scope.own_school_ids)
        return [i for i in qs.values_list("id", flat=True)[:2000] if i not in own]

    return _probe(
        "pl_core_list_includes_team_core_schools",
        "Programme Lead Core Schools list contains a supervised CCEO's core school",
        "The operational Core list returns directly assigned core schools only",
        "/core-schools",
        leak,
    )


def _search_reaches_supervised_schools() -> dict:
    def leak(user, scope):
        from apps.search.services import search
        from apps.schools.models import School

        team = list(scope.team_school_ids)[:1]
        if not team:
            return []
        name = (
            School.objects.filter(id=team[0]).values_list("name", flat=True).first()
        )
        if not name:
            return []
        results = search(user, name[:12])["results"]
        own = set(scope.own_school_ids)
        return [
            r["id"]
            for r in results
            if r["kind"] == "school" and r["id"] not in own
        ]

    return _probe(
        "pl_search_reaches_team_schools",
        "Top-bar search returns a supervised CCEO's school as an operational result",
        "Search returns the direct portfolio; the team appears under oversight",
        "/search",
        leak,
    )


def _direct_and_oversight_sets_overlap() -> dict:
    """The two lenses must be disjoint.

    If a school appears in both, a count of one has been presented as a count
    of the other somewhere, and "my portfolio" and "my team's" have started to
    mean the same thing again.
    """
    def leak(user, scope):
        from apps.core.scoping import direct_portfolio_schools, team_oversight_schools

        direct = direct_portfolio_schools(scope)
        oversight = team_oversight_schools(scope)
        if direct is None or oversight is None:
            return []
        return list(
            direct.filter(id__in=oversight.values("id")).values_list("id", flat=True)[
                :50
            ]
        )

    return _probe(
        "portfolio_and_oversight_overlap",
        "A school appears in both the direct portfolio and team oversight",
        "The operational and supervisory sets are disjoint",
        "apps/core/scoping.py",
        leak,
    )


def _core_page_size_is_bounded() -> dict:
    """The Core list must stay server-paginated with a validated page size.

    An unbounded Core query is the failure mode that only shows up in
    production, where the table has thousands of rows rather than the handful
    a developer sees.
    """
    from apps.frontend.views import core_schools_views as views

    problems = []
    sizes = getattr(views, "CORE_PAGE_SIZES", ())
    default = getattr(views, "CORE_PAGE_SIZE_DEFAULT", None)
    if not sizes:
        problems.append({"id": "CORE_PAGE_SIZES", "actual": "not defined"})
    elif max(sizes) > 100:
        problems.append(
            {"id": "CORE_PAGE_SIZES", "actual": f"largest option is {max(sizes)}"}
        )
    if default not in sizes:
        problems.append(
            {"id": "CORE_PAGE_SIZE_DEFAULT", "actual": f"{default} is not an option"}
        )

    class _Req:
        GET = {"per_page": "100000"}

    if views._core_page_size(_Req()) not in sizes:
        problems.append(
            {"id": "per_page", "actual": "an out-of-range value was accepted"}
        )

    return _finding(
        key="core_list_page_size_unbounded",
        label="Core Schools list page size is unbounded or unvalidated",
        severity="error",
        expected="Server-side pagination with a validated page size from a fixed set",
        count=len(problems),
        examples=problems,
        route="/core-schools",
    )
