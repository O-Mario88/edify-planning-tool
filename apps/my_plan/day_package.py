"""The day package — the offline-first field day's data contract (Phase 3).

One JSON document that lets a field officer run a whole day without
connectivity: today's own activities in route order, each carrying the
school's location, the evidence checklist, and the participant plan. The
client caches it before travel; check-ins and completions queue locally and
replay when the network returns. This module is the server half; the
service-worker/queue client is the remaining half of Phase 3 (see
OPERATIONS_ROADMAP.md).

Scope rules are the platform's, not the endpoint's: the package contains
only the caller's own work (the same ownership filter My Plan uses), and
partner-delivered monitoring rows are excluded — a partner's day package is
their portal's concern.
"""

from __future__ import annotations

from datetime import date as date_type

from django.db.models import Q
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.scoping import resolve_user_scope
from apps.evidence.requirements import missing_evidence_kinds
from apps.my_plan.services import ACTIVE_MY_PLAN_EXCLUDED_STATUSES


def _location_for(school, geo_overrides: dict) -> dict | None:
    if school is None:
        return None
    override = geo_overrides.get(school.id)
    latitude = override[0] if override else school.latitude
    longitude = override[1] if override else school.longitude
    return {
        "latitude": latitude,
        "longitude": longitude,
        "source": "geo_point" if override else "directory",
    }


def build_day_package(principal, *, day: date_type | None = None) -> dict:
    """Everything the caller's field day needs, serialised for offline use."""

    target = day or timezone.localdate()
    scope = resolve_user_scope(principal)
    staff_ids = [
        identifier
        for identifier in (
            scope.staff_ids
            or [getattr(principal, "staff_profile_id", None), principal.id]
        )
        if identifier
    ]
    activities = list(
        Activity.objects.filter(
            # Same legacy fallback My Plan applies (services._scheduled_in_
            # range): older scheduled rows can carry a NULL planned_date, and
            # a real dated activity must not vanish from the field day.
            Q(planned_date=target)
            | Q(planned_date__isnull=True, scheduled_date__date=target),
            deleted_at__isnull=True,
            responsible_staff_id__in=staff_ids,
        )
        .exclude(status__in=ACTIVE_MY_PLAN_EXCLUDED_STATUSES)
        .exclude(delivery_type="partner")
        .select_related("school", "school__sub_county", "school__district")
        .order_by("scheduled_date", "id")
    )
    from apps.routes.models import SchoolGeoPoint

    school_ids = [a.school_id for a in activities if a.school_id]
    geo_overrides = {
        school_id: (latitude, longitude)
        for school_id, latitude, longitude in SchoolGeoPoint.objects.filter(
            school_id__in=school_ids
        ).values_list("school_id", "latitude", "longitude")
    }
    rows = []
    for activity in activities:
        school = activity.school
        rows.append(
            {
                "activityId": activity.id,
                "activityType": activity.activity_type,
                "name": activity.activity_name_snapshot or activity.activity_type,
                "status": activity.status,
                "scheduledAt": (
                    activity.scheduled_date.isoformat()
                    if activity.scheduled_date
                    else None
                ),
                "school": (
                    {
                        "id": school.id,
                        "name": school.name,
                        "schoolType": school.school_type,
                        "district": (
                            school.district.name if school.district_id else None
                        ),
                        "subCounty": (
                            school.sub_county.name if school.sub_county_id else None
                        ),
                        "location": _location_for(school, geo_overrides),
                    }
                    if school
                    else None
                ),
                "clusterId": activity.cluster_id,
                "focusIntervention": activity.focus_intervention,
                # The §3a capture contract: prefilled plan, staff confirm
                # reality. Planned figures ride along so the client can show
                # "planned 40 → actual [ ]" without re-entry.
                "plannedParticipants": activity.expected_participants,
                "participantsPerSchool": activity.participants_per_school,
                "schoolsInvited": activity.schools_invited,
                "evidenceRequired": missing_evidence_kinds(activity),
            }
        )
    # Route order: geography first (sub-county groups), then schedule. The
    # full optimiser is Phase 4; grouping alone already kills criss-cross.
    groups: dict[str, list] = {}
    for row in rows:
        key = (row["school"] or {}).get("subCounty") or "Unlocated"
        groups.setdefault(key, []).append(row)
    return {
        "date": target.isoformat(),
        "generatedAt": timezone.now().isoformat(),
        "activityCount": len(rows),
        "routeGroups": [
            {"area": area, "activities": items}
            for area, items in sorted(groups.items())
        ],
        # Client sync contract (the visible states the standard requires).
        "syncStates": ["saved_on_device", "syncing", "synced", "needs_attention"],
    }
