"""Health checks for the planning-oversight invariants.

These watch the things that would make the oversight pages quietly wrong rather
than visibly broken. A page that 500s gets fixed the same day; a page whose
country budget is short by one team's cost lines gets believed.

Each finding names the record, what was expected, what is actually there and
where to resolve it, because a health check that only reports a count leaves
somebody to go and find the rows themselves.
"""

from __future__ import annotations

from django.db.models import Count, Q, Sum


def report() -> dict:
    """Every oversight invariant, checked against live data."""
    checks = [
        _assignments_scheduled_without_a_linked_activity(),
        _assignments_costed_before_scheduling(),
        _activities_claimed_by_two_assignments(),
        _activities_without_an_operational_owner(),
        _work_owned_by_staff_who_never_onboarded(),
        _activities_without_a_supervising_program_lead(),
        _scheduled_activities_without_a_cost(),
    ]
    issues = sum(check["count"] for check in checks)
    return {
        "clean": issues == 0,
        "issueCount": issues,
        "checks": checks,
    }


def _finding(
    *,
    key: str,
    label: str,
    severity: str,
    expected: str,
    count: int,
    examples,
    route: str,
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


def _assignments_scheduled_without_a_linked_activity() -> dict:
    """A scheduled handover whose activity was never recorded.

    Oversight still counts these correctly — a scheduled assignment is
    represented by its activity either way — but the handover history cannot be
    shown on the activity, and a genuinely unpaired row cannot be told apart
    from one that simply predates the link.
    """
    from apps.partners.models import PartnerAssignment

    rows = PartnerAssignment.objects.filter(
        status__in=("partner_scheduled", "scheduled", "completed"),
        scheduled_activity__isnull=True,
    ).values("id", "partner__name", "school__name")[:10]
    count = PartnerAssignment.objects.filter(
        status__in=("partner_scheduled", "scheduled", "completed"),
        scheduled_activity__isnull=True,
    ).count()

    return _finding(
        key="assignment_missing_scheduled_activity",
        label="Scheduled partner assignments with no linked activity",
        severity="warning",
        expected="Every scheduled assignment records the activity it became",
        count=count,
        examples=[
            {
                "id": row["id"],
                "partner": row["partner__name"],
                "school": row["school__name"],
                "actual": "scheduled, but scheduled_activity is empty",
            }
            for row in rows
        ],
        route="manage.py repair_partner_assignment_links",
    )


def _assignments_costed_before_scheduling() -> dict:
    """An unscheduled handover that already carries money.

    This is the one that would inflate a planned budget with work nobody has
    committed to a date, so it is an error rather than a warning.
    """
    from apps.activities.models import ActivityScheduleCostLine
    from apps.partners.models import PartnerAssignment

    unscheduled = PartnerAssignment.objects.filter(
        status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        scheduled_activity__isnull=False,
    )
    offenders = []
    for assignment in unscheduled.select_related("partner", "school")[:10]:
        total = (
            ActivityScheduleCostLine.objects.filter(
                activity_id=assignment.scheduled_activity_id
            ).aggregate(t=Sum("amount"))["t"]
            or 0
        )
        if total:
            offenders.append(
                {
                    "id": assignment.id,
                    "partner": getattr(assignment.partner, "name", ""),
                    "school": getattr(assignment.school, "name", ""),
                    "actual": f"unscheduled but linked to UGX {total:,} of cost",
                }
            )

    return _finding(
        key="assignment_costed_before_scheduling",
        label="Unscheduled assignments carrying cost",
        severity="error",
        expected="An assignment contributes UGX 0 until the partner schedules it",
        count=len(offenders),
        examples=offenders,
        route="/country-planning-oversight/",
    )


def _activities_claimed_by_two_assignments() -> dict:
    """One activity recorded as the outcome of more than one handover.

    The database constraint makes this impossible going forward; the check
    stays because historic rows predate it and because a constraint that is
    never verified is a belief rather than a fact.
    """
    from apps.partners.models import PartnerAssignment

    duplicates = (
        PartnerAssignment.objects.filter(scheduled_activity__isnull=False)
        .values("scheduled_activity_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    rows = list(duplicates[:10])

    return _finding(
        key="activity_claimed_twice",
        label="Activities claimed by more than one assignment",
        severity="error",
        expected="An activity is the outcome of at most one handover",
        count=len(rows),
        examples=[
            {
                "id": row["scheduled_activity_id"],
                "actual": f"claimed by {row['n']} assignments",
            }
            for row in rows
        ],
        route="/country-planning-oversight/",
    )


def _activities_without_an_operational_owner() -> dict:
    """Live work nobody is answerable for.

    These appear on no supervisor's page, because there is no supervisor to
    put them under — which is exactly why they need reporting somewhere.
    """
    from apps.activities.models import Activity
    from apps.planning.oversight_service import LIVE_ACTIVITY_STATUSES

    ownerless = Activity.objects.filter(
        deleted_at__isnull=True,
        status__in=LIVE_ACTIVITY_STATUSES,
    ).filter(
        Q(responsible_staff_id__isnull=True) | Q(responsible_staff_id=""),
        Q(monitored_by_staff_id__isnull=True) | Q(monitored_by_staff_id=""),
    )

    return _finding(
        key="activity_without_owner",
        label="Live activities with no operational owner",
        severity="error",
        expected="Every live activity names a responsible or monitoring staff member",
        count=ownerless.count(),
        examples=[
            {
                "id": row["id"],
                "school": row["school__name"],
                "actual": "no responsible or monitoring staff",
            }
            for row in ownerless.values("id", "school__name")[:10]
        ],
        route="/planning",
    )


def _work_owned_by_staff_who_never_onboarded() -> dict:
    """Live work owned by an account nobody can sign in as.

    Separate from the missing-supervisor check on purpose, because the two need
    opposite fixes and conflating them sends people to the wrong place. An
    active CCEO with no reporting line needs a line. An invited account that
    was never activated needs onboarding — giving it a supervisor would make
    the health report green while leaving the work exactly as unactionable as
    it was: the owner cannot sign in, cannot upload evidence, cannot complete
    anything, and cannot act on a TeamAction sent to them.
    """
    from apps.accounts.models import StaffProfile
    from apps.activities.models import Activity
    from apps.planning.oversight_service import LIVE_ACTIVITY_STATUSES

    owner_ids = set(
        Activity.objects.filter(
            deleted_at__isnull=True, status__in=LIVE_ACTIVITY_STATUSES
        )
        .exclude(responsible_staff_id__isnull=True)
        .exclude(responsible_staff_id="")
        .values_list("responsible_staff_id", flat=True)
        .distinct()
    )
    profiles = StaffProfile.objects.filter(
        Q(id__in=owner_ids) | Q(user_id__in=owner_ids)
    ).select_related("user")
    dormant = [p for p in profiles if not getattr(p.user, "is_active", True)]

    activity_count = (
        Activity.objects.filter(
            deleted_at__isnull=True, status__in=LIVE_ACTIVITY_STATUSES
        )
        .filter(
            Q(responsible_staff_id__in=[p.id for p in dormant])
            | Q(responsible_staff_id__in=[p.user_id for p in dormant])
        )
        .count()
        if dormant
        else 0
    )

    return _finding(
        key="owner_never_onboarded",
        label="Live work owned by staff who have never been activated",
        severity="error",
        expected="Every owner of live work can sign in and act on it",
        count=len(dormant),
        examples=[
            {
                "id": p.id,
                "staff": getattr(p.user, "name", "") or getattr(p.user, "email", ""),
                "actual": (
                    f"{getattr(p.user, 'status', 'inactive')}, never activated — "
                    "cannot sign in, upload evidence or act on an assigned action"
                ),
            }
            for p in dormant[:10]
        ],
        route=f"/admin-panel/staff-setup-queue ({activity_count} live activities affected)",
    )


def _activities_without_a_supervising_program_lead() -> dict:
    """Owned work whose owner reports to nobody.

    The Country Director's page groups by Program Lead, so these fall into an
    "Unassigned" group: real work that no team is accountable for. The fix is a
    supervisor link, not a change to the activity.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
    from apps.activities.models import Activity
    from apps.planning.oversight_service import LIVE_ACTIVITY_STATUSES

    supervised = set(
        StaffSupervisorAssignment.objects.values_list("supervisee_id", flat=True)
    )
    owner_ids = set(
        Activity.objects.filter(
            deleted_at__isnull=True, status__in=LIVE_ACTIVITY_STATUSES
        )
        .exclude(responsible_staff_id__isnull=True)
        .exclude(responsible_staff_id="")
        .values_list("responsible_staff_id", flat=True)
        .distinct()
    )
    # responsible_staff_id holds either id space, so resolve to profiles first.
    profiles = StaffProfile.objects.filter(
        Q(id__in=owner_ids) | Q(user_id__in=owner_ids)
    ).select_related("user")
    # Accounts that were never activated are reported by their own check
    # above. Counting them here too would give one problem two findings and
    # point the reader at a fix — adding a reporting line — that would leave
    # the work exactly as stuck as it was.
    unsupervised = [
        p
        for p in profiles
        if p.id not in supervised and getattr(p.user, "is_active", True)
    ]

    return _finding(
        key="owner_without_supervisor",
        label="Activity owners with no supervising Program Lead",
        severity="warning",
        expected="Every owner of live work reports to a Program Lead",
        count=len(unsupervised),
        examples=[
            {
                "id": p.id,
                "staff": getattr(p.user, "name", "") or getattr(p.user, "email", ""),
                "actual": "no supervisor link; their work groups as Unassigned",
            }
            for p in unsupervised[:10]
        ],
        route="/admin-panel/users",
    )


def _scheduled_activities_without_a_cost() -> dict:
    """Scheduled work that cannot enter a fund request."""
    from apps.activities.models import Activity, ActivityScheduleCostLine

    scheduled = Activity.objects.filter(
        deleted_at__isnull=True,
        status__in=("scheduled", "partner_scheduled", "planned"),
    )
    costed = set(
        ActivityScheduleCostLine.objects.filter(
            activity_id__in=scheduled.values("id")
        ).values_list("activity_id", flat=True)
    )
    missing = [
        row
        for row in scheduled.values("id", "school__name")[:2000]
        if row["id"] not in costed
    ]

    return _finding(
        key="scheduled_without_cost",
        label="Scheduled activities with no cost line",
        severity="warning",
        expected="Scheduled work is priced before it reaches a fund request",
        count=len(missing),
        examples=[
            {"id": row["id"], "school": row["school__name"], "actual": "no cost lines"}
            for row in missing[:10]
        ],
        route="/team-planning-oversight/?risk=scheduled_without_cost",
    )
