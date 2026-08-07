"""Health checks for the school-closure invariants.

The failure these watch for is quiet by construction: a closed school that is
still counted looks exactly like an open one on every page. Nothing breaks,
nothing 500s, and a country reports reaching learners at a school that shut
last term.
"""

from __future__ import annotations


def report() -> dict:
    checks = [
        _closed_schools_still_operationally_visible(),
        _closed_schools_with_live_future_work(),
        _closed_schools_with_active_partner_work(),
        _closures_missing_their_enrolment_snapshot(),
        _locked_activities_awaiting_closure_review(),
        _active_definition_agrees_across_modules(),
    ]
    issues = sum(c["count"] for c in checks)
    return {"clean": issues == 0, "issueCount": issues, "checks": checks}


def _finding(*, key, label, severity, expected, count, examples, route) -> dict:
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


def _closed_schools_still_operationally_visible() -> dict:
    """A closed school the operational directory still returns.

    The one check that catches a call site nobody migrated. It asks the
    canonical operational queryset directly rather than inspecting source, so
    it stays true however the query is written.
    """
    from apps.core.scoping import _operationally_active
    from apps.schools.models import School

    leaked = _operationally_active(School.objects.all()).exclude(
        operational_status__in=("active", "reopened")
    )

    return _finding(
        key="closed_school_operationally_visible",
        label="Closed schools still returned by the operational queryset",
        severity="error",
        expected="The operational directory returns only schools that are operating",
        count=leaked.count(),
        examples=[
            {
                "id": row["id"],
                "school": row["name"],
                "actual": row["operational_status"],
            }
            for row in leaked.values("id", "name", "operational_status")[:10]
        ],
        route="/schools",
    )


def _closed_schools_with_live_future_work() -> dict:
    """Work still planned at a school that has shut.

    Somebody will travel to it. The closure cancels future unlocked work, so a
    finding here means either a closure that failed part-way or an activity
    created afterwards.
    """
    from datetime import date

    from apps.activities.models import Activity
    from apps.schools.lifecycle_service import closed_schools

    closed = {s.id: s for s in closed_schools()}
    if not closed:
        return _finding(
            key="closed_school_future_work",
            label="Future work planned at closed schools",
            severity="error",
            expected="A closed school has no future executable work",
            count=0,
            examples=[],
            route="/planning",
        )

    live = Activity.objects.filter(
        school_id__in=closed,
        deleted_at__isnull=True,
        planned_date__gte=date.today(),
    ).exclude(status__in=("cancelled", "deferred", "rejected", "completed", "closed"))

    return _finding(
        key="closed_school_future_work",
        label="Future work planned at closed schools",
        severity="error",
        expected="A closed school has no future executable work",
        count=live.count(),
        examples=[
            {
                "id": row["id"],
                "school": closed[row["school_id"]].name
                if row["school_id"] in closed
                else "",
                "actual": f"{row['status']}, planned {row['planned_date']}",
            }
            for row in live.values("id", "school_id", "status", "planned_date")[:10]
        ],
        route="/planning",
    )


def _closed_schools_with_active_partner_work() -> dict:
    """A partner still holding an assignment at a school that has shut."""
    from apps.partners.models import PartnerAssignment
    from apps.schools.lifecycle_service import closed_schools

    closed = {s.id: s.name for s in closed_schools()}
    if not closed:
        count, rows = 0, []
    else:
        qs = PartnerAssignment.objects.filter(school_id__in=closed).exclude(
            status=PartnerAssignment.STATUS_RETURNED_TO_STAFF
        )
        count = qs.count()
        rows = [
            {
                "id": r["id"],
                "school": closed.get(r["school_id"], ""),
                "partner": r["partner__name"],
                "actual": f"assignment still {r['status']}",
            }
            for r in qs.values("id", "school_id", "status", "partner__name")[:10]
        ]

    return _finding(
        key="closed_school_partner_work",
        label="Active partner assignments at closed schools",
        severity="error",
        expected="Closing a school withdraws its partner assignments",
        count=count,
        examples=rows,
        route="/partner-oversight/",
    )


def _closures_missing_their_enrolment_snapshot() -> dict:
    """A closure that cannot say what the programme lost.

    A warning rather than an error: the school is correctly closed and nothing
    is broken. But the enrolment removed is unrecoverable once the school
    record moves on, so it is worth chasing while somebody still remembers.
    """
    from apps.schools.lifecycle_models import SchoolClosure

    missing = SchoolClosure.objects.filter(
        reopened_at__isnull=True, enrollment_at_closure__isnull=True
    ).select_related("school")

    return _finding(
        key="closure_missing_enrolment_snapshot",
        label="Closures with no enrolment snapshot",
        severity="warning",
        expected="Every closure records the learners it took out of the programme",
        count=missing.count(),
        examples=[
            {
                "id": c.id,
                "school": getattr(c.school, "name", ""),
                "actual": "no enrolment recorded at closure",
            }
            for c in missing[:10]
        ],
        route="/schools/closed",
    )


def _locked_activities_awaiting_closure_review() -> dict:
    """Money committed against a school that has since shut.

    Deliberately not cancelled by the closure — money that has moved settles
    through accountability. Reported so it is settled rather than forgotten.
    """
    from apps.schools.lifecycle_models import SchoolClosure

    pending = SchoolClosure.objects.filter(
        reopened_at__isnull=True, locked_activities_for_review__gt=0
    ).select_related("school")

    return _finding(
        key="closure_locked_finance_pending",
        label="Closed schools with committed funds still to settle",
        severity="warning",
        expected="Committed money at a closed school is settled or returned",
        count=pending.count(),
        examples=[
            {
                "id": c.id,
                "school": getattr(c.school, "name", ""),
                "actual": (
                    f"{c.locked_activities_for_review} activity(s) with "
                    "committed funds"
                ),
            }
            for c in pending[:10]
        ],
        route="/finance/accountability",
    )


def _active_definition_agrees_across_modules() -> dict:
    """The two places that answer "operating" must answer the same.

    `core.scoping` keeps its own status tuple rather than importing from the
    schools app, to avoid a scoping module depending on an app it scopes. That
    is a deliberate duplication, and a duplicated constant that drifts is worse
    than the import would have been — so it is asserted rather than trusted.
    """
    from apps.core.scoping import _operationally_active
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.schools.models import School

    scoping_sql = str(_operationally_active(School.objects.all()).query)
    drift = [s for s in OPERATING_STATUSES if str(s) not in scoping_sql]

    return _finding(
        key="active_definition_drift",
        label="The operational and lifecycle definitions of active disagree",
        severity="error",
        expected="core.scoping and schools.lifecycle_models name the same statuses",
        count=len(drift),
        examples=[
            {"id": str(s), "actual": "missing from core.scoping._operationally_active"}
            for s in drift
        ],
        route="apps/core/scoping.py",
    )
