"""Approved allocations are the operational priority contract, not copied agreements."""

from collections import defaultdict
from decimal import Decimal


from apps.core.fy import get_fy_date_range, get_operational_fy
from .models import MilestoneAllocation


def reporting_period(fy=None, quarter=None, month=None):
    fy = str(fy or get_operational_fy())
    if not fy.isdigit() or len(fy) != 4 or not 2000 <= int(fy) <= 2100:
        from apps.core.exceptions import BadRequest

        raise BadRequest("Choose a valid financial year.")
    from apps.core.exceptions import BadRequest

    if quarter and quarter not in {"Q1", "Q2", "Q3", "Q4"}:
        raise BadRequest("Choose a valid quarter.")
    if month and (not str(month).isdigit() or not 1 <= int(month) <= 12):
        raise BadRequest("Choose a valid financial-year month.")
    start, end = get_fy_date_range(fy)
    start, end = start.date(), end.date()
    from datetime import timedelta
    from apps.core.fy import get_month_date_range

    if month and str(month).isdigit() and 1 <= int(month) <= 12:
        start, end = get_month_date_range(fy, int(month))
        return fy, start.date(), end.date() - timedelta(days=1)
    if quarter in ("Q1", "Q2", "Q3", "Q4"):
        offset = (int(quarter[1]) - 1) * 3
        first, _ = get_month_date_range(fy, offset + 1)
        _, last = get_month_date_range(fy, offset + 3)
        return fy, first.date(), last.date() - timedelta(days=1)
    return fy, start, end - timedelta(days=1)


def allocation_priorities(
    user,
    fy=None,
    *,
    quarter=None,
    month=None,
    activity_ids=None,
    country=None,
    recipient_ids=None,
    include_plans=True,
):
    from apps.core.request_cache import memoize

    if activity_ids is not None:
        return _allocation_priorities(
            user,
            fy,
            quarter=quarter,
            month=month,
            activity_ids=activity_ids,
            country=country,
            recipient_ids=recipient_ids,
            include_plans=include_plans,
        )
    key = (
        "approved-allocation-contract",
        getattr(user, "id", None),
        getattr(user, "active_role", None),
        fy,
        quarter,
        month,
        country,
        tuple(sorted(recipient_ids)) if recipient_ids is not None else None,
        include_plans,
    )
    return memoize(
        key,
        lambda: _allocation_priorities(
            user,
            fy,
            quarter=quarter,
            month=month,
            country=country,
            recipient_ids=recipient_ids,
            include_plans=include_plans,
        ),
    )


def _allocation_priorities(
    user,
    fy=None,
    *,
    quarter=None,
    month=None,
    activity_ids=None,
    country=None,
    recipient_ids=None,
    include_plans=True,
):
    """Personal allocations first; leaders read their approved scope, without copies.

    Each row keeps its own unit. Overall is a weighted normalized score, never
    a sum of schools, visits and attendance. Missing weights withhold a score.
    """
    fy, start, end = reporting_period(fy, quarter, month)
    staff = getattr(user, "staff_profile", None)
    if staff is None and country is None and recipient_ids is None:
        return {"rows": [], "pct": None, "fy": fy, "scope": "Assigned priorities"}
    role = getattr(user, "active_role", "")
    allocations = (
        MilestoneAllocation.objects.filter(
            status="approved",
            milestone__priority__fy=fy,
            milestone__active=True,
            milestone__definition_status="approved",
        )
        .select_related("milestone__priority", "employee__user")
        .prefetch_related("period_targets", "milestone__activity_rules")
    )
    if recipient_ids is not None:
        allocations = allocations.filter(
            allocated_to_type="employee", employee_id__in=recipient_ids
        )
        scope_label = "Selected employees and monitored partners"
    elif role == "Program Lead":
        from django.db.models import Q
        from .contribution_scope import owner_ids

        team_roots = allocations.filter(allocated_to_type="team", team_id=staff.id)
        # Older approved employee allocations can predate the team parent.
        # Use their exact sum only for milestones without an approved team
        # allocation, so introducing the parent never counts both levels.
        allocations = allocations.filter(
            Q(allocated_to_type="team", team_id=staff.id)
            | (
                Q(allocated_to_type="employee", employee_id__in=owner_ids(staff, True))
                & ~Q(milestone_id__in=team_roots.values("milestone_id"))
            )
        )
        scope_label = "You and your team"
    elif country is not None or role in {
        "CountryDirector",
        "RegionalVicePresident",
        "Admin",
    }:
        from apps.core.scoping import resolve_user_scope

        scope = resolve_user_scope(user) if user is not None else None
        country = (
            country
            if country is not None
            else (getattr(scope, "country", "") or getattr(staff, "country", ""))
        )
        allocations = allocations.filter(parent__isnull=True)
        if country:
            from django.db.models import Q

            allocations = allocations.filter(
                milestone__priority__country_id=country
            ).filter(Q(employee__isnull=True) | Q(employee__country=country))
        scope_label = "Country delivery"
    else:
        allocations = allocations.filter(allocated_to_type="employee", employee=staff)
        scope_label = "Your delivery and monitored partners"
    groups = defaultdict(list)
    for allocation in allocations:
        groups[str(allocation.milestone_id)].append(allocation)
    from .milestone_progress import (
        _aggregate_credits,
        MilestoneProgressCredit,
        RATE_MEASUREMENT_TYPES,
        counting_basis_families,
    )
    from .target_distribution import milestone_plan_progress
    from apps.activities.models import Activity

    rows = []
    for group in groups.values():
        milestone = group[0].milestone
        target = Decimal(0)
        denominator = Decimal(0)
        rate_numerator = Decimal(0)
        for allocation in group:
            periods = [
                p
                for p in allocation.period_targets.all()
                if p.period_type == "month" and start <= p.period_start <= end
            ]
            is_rate = milestone.measurement_type in RATE_MEASUREMENT_TYPES
            target += (
                allocation.allocated_target
                if is_rate or (not quarter and not month)
                else sum((p.planned_value for p in periods), Decimal(0))
            )
            denominator += allocation.denominator or Decimal(0)
            rate_numerator += allocation.allocated_target * (
                allocation.denominator or Decimal(0)
            )
        # Country targets are the master figure; team roots partition that
        # figure and must not multiply a rate by the number of holders.
        country_scope = country is not None or role in {
            "CountryDirector",
            "RegionalVicePresident",
            "Admin",
        }
        if milestone.measurement_type in RATE_MEASUREMENT_TYPES:
            if country_scope:
                target = milestone.target_value
            elif denominator:
                target = rate_numerator / denominator
        activities = Activity.objects.filter(
            fy=fy,
            deleted_at__isnull=True,
            planned_date__gte=start,
            planned_date__lte=end,
        )
        from .contribution_scope import scope_activities

        if country_scope:
            activities = scope_activities(
                activities, country=milestone.priority.country_id
            )
        elif recipient_ids is not None:
            from django.db.models import Q
            from apps.accounts.models import StaffProfile

            ids = set(recipient_ids) | set(
                StaffProfile.objects.filter(id__in=recipient_ids).values_list(
                    "user_id", flat=True
                )
            )
            activities = activities.filter(
                Q(responsible_staff_id__in=ids)
                | Q(delivery_type="partner", monitored_by_staff_id__in=ids)
            ).distinct()
        else:
            activities = scope_activities(
                activities, staff=staff, include_team=role == "Program Lead"
            )
        # Ownership never lets work from another country satisfy this milestone.
        activities = scope_activities(activities, country=milestone.priority.country_id)
        if activity_ids is not None:
            activities = activities.filter(id__in=activity_ids)
        progress = (
            milestone_plan_progress(
                [milestone],
                fy=fy,
                activity_ids=activities.values("id"),
                targets={str(milestone.id): target},
            ).get(str(milestone.id))
            if include_plans
            else None
        )
        credits = MilestoneProgressCredit.objects.filter(
            rule__milestone=milestone,
            rule__active=True,
            reversed_at__isnull=True,
            activity_id__in=activities.values("id"),
        )
        bases = {r.counting_basis for r in milestone.activity_rules.all() if r.active}
        actual = Decimal(_aggregate_credits(credits, bases) or 0)
        verified_units = actual
        configured = bool(bases) and len(counting_basis_families(bases)) == 1
        if milestone.measurement_type in RATE_MEASUREMENT_TYPES:
            actual = actual / denominator * 100 if denominator else Decimal(0)
            configured = configured and bool(denominator)
        if (
            milestone.measurement_type in RATE_MEASUREMENT_TYPES
            and milestone.cap_at_100
        ):
            actual = min(actual, Decimal(100))
        pct = round(float(actual / target * 100), 2) if target and configured else None
        if (
            pct is not None
            and milestone.cap_at_100
            and milestone.measurement_type not in RATE_MEASUREMENT_TYPES
        ):
            pct = min(pct, 100)

        if progress:
            progress["verified"] = verified_units
            progress["verified_pct"] = min(pct, 100) if pct is not None else None
            if milestone.measurement_type in RATE_MEASUREMENT_TYPES:
                progress["pct"] = (
                    min(
                        round(
                            float(
                                progress["completed"] / denominator * 100 / target * 100
                            ),
                            1,
                        ),
                        100,
                    )
                    if denominator and target
                    else None
                )
                progress["target"] = denominator * target / 100 if denominator else None
                progress["planned_pct"] = (
                    min(
                        round(float(progress["planned"] / progress["target"] * 100), 1),
                        100,
                    )
                    if progress["target"]
                    else None
                )
        rows.append(
            {
                "id": str(milestone.id),
                "title": milestone.title,
                "priority": milestone.priority.title,
                "target": target,
                "actual": actual,
                "pct": pct,
                "unit": milestone.target_unit,
                "progress": progress,
                "weight": float(
                    (group[0].weight if not country_scope else 0)
                    or milestone.weight
                    or 0
                ),
                "scope": scope_label,
                "source": "Approved allocation",
                "allocation_ids": [str(a.id) for a in group],
            }
        )
    eligible = [r for r in rows if r["pct"] is not None]
    weights_ready = (
        eligible
        and len(eligible) == len([row for row in rows if row["target"] > 0])
        and all(r["weight"] > 0 for r in eligible)
    )
    total_weight = sum(r["weight"] for r in eligible) if weights_ready else 0
    pct = (
        round(sum(r["pct"] * r["weight"] for r in eligible) / total_weight, 2)
        if total_weight
        else None
    )
    return {
        "rows": rows,
        "pct": pct,
        "fy": fy,
        "scope": scope_label,
        "start": start,
        "end": end,
    }


def leadership_priority_rows(user, fy=None, *, quarter=None, month=None):
    """Each accountable person's approved contract, for review and CSV alike."""
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    staff = getattr(user, "staff_profile", None)
    if staff is None:
        return []
    profiles = StaffProfile.objects.filter(
        user__is_active=True, user__deleted_at__isnull=True
    ).select_related("user")
    if user.active_role == "Program Lead":
        ids = StaffSupervisorAssignment.objects.filter(supervisor=staff).values_list(
            "supervisee_id", flat=True
        )
        profiles = profiles.filter(id__in=[staff.id, *ids])
    elif user.active_role in {"CountryDirector", "RegionalVicePresident", "Admin"}:
        profiles = profiles.filter(
            country=staff.country, user__active_role__in=["Program Lead", "CCEO"]
        )
    else:
        profiles = profiles.filter(id=staff.id)
    result = []
    for profile in profiles.order_by("user__name"):
        contract = allocation_priorities(
            profile.user, fy, quarter=quarter, month=month, include_plans=False
        )
        result.append(
            {
                "staff_id": str(profile.id),
                "name": profile.user.name,
                "role": profile.user.active_role,
                "pct": contract["pct"],
                "scope": contract["scope"],
                "rows": contract["rows"],
            }
        )
    return result


def allocation_period_matrix(user, fy, month):
    """The same approved contract at monthly, quarterly and annual boundaries."""
    periods = [
        allocation_priorities(user, fy, month=month, include_plans=False),
        *[
            allocation_priorities(user, fy, quarter=f"Q{q}", include_plans=False)
            for q in range(1, 5)
        ],
        allocation_priorities(user, fy, include_plans=False),
    ]
    indexed = [{row["id"]: row for row in period["rows"]} for period in periods]
    return {
        "rows": [
            {
                "label": row["title"],
                "key": row["id"],
                "cells": [
                    {
                        "t": values[row["id"]]["target"],
                        "a": values[row["id"]]["actual"],
                        "pct": values[row["id"]]["pct"],
                    }
                    for values in indexed
                ],
            }
            for row in periods[-1]["rows"]
        ],
        "overall": [{"pct": period["pct"]} for period in periods],
        "annual": periods[-1],
    }


def snapshot_contract(data):
    """Read frozen allocations, including an honest empty state for older records."""
    return {
        "rows": [
            dict(row, title=row["milestone"])
            for row in data.get("distributedPriorities", [])
        ],
        "pct": data.get("distributedAchievement"),
        "scope": data.get("accountabilityScope", ""),
    }
