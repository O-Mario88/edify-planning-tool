"""Route Intelligence health checks (mandate §14) — every count is derived
from real workflow rows; consumed by apps.system_health.services.report()."""

from __future__ import annotations

from datetime import date

from django.db.models import Q


def route_intelligence_checks() -> dict:
    from apps.activities.models import Activity
    from apps.routes.models import DailyVisitRouteBatch
    from apps.schools.models import School

    today = date.today()

    # 1. Planned staff visit day has no route batch.
    planned_days = set(
        Activity.objects.filter(
            deleted_at__isnull=True,
            activity_type="school_visit",
            delivery_type="staff",
            scheduled_date__date__gte=today,
        )
        .exclude(status__in=["cancelled", "not_planned", "rejected"])
        .exclude(daily_visit_batch__isnull=True)
        .values_list(
            "daily_visit_batch__responsible_user", "daily_visit_batch__visit_date"
        )
    )
    routed_days = set(
        DailyVisitRouteBatch.objects.filter(visit_date__gte=today).values_list(
            "responsible_user", "visit_date"
        )
    )
    visits_without_route_batch = len(planned_days - routed_days)

    # 2. School missing coordinates AND weak/absent shipping address.
    schools_weak_location = (
        School.objects.filter(
            Q(latitude__isnull=True) | Q(longitude__isnull=True),
            sub_county__isnull=True,
            parish__isnull=True,
        )
        .filter(Q(shipping_address__isnull=True) | Q(shipping_address=""))
        .count()
    )

    batches = DailyVisitRouteBatch.objects.filter(visit_date__gte=today)
    # 3. Daily visit route mixes primary and secondary districts.
    mixed_district_days = (
        batches.filter(issues__code="mixed_district_types").distinct().count()
    )
    # 4. Secondary districts grouped without an approved route group.
    ungrouped_secondary_days = (
        batches.filter(issues__code="secondary_group_unapproved").distinct().count()
    )
    # 5. Route load exceeds the working day.
    overloaded_days = batches.filter(feasible=False).count()
    # 6. Fewer schools than the CD target without a recorded reason.
    below_target_no_reason = 0
    for rb in batches.filter(target_snapshot__isnull=False).select_related(
        "cost_batch"
    ):
        if rb.school_count < (rb.target_snapshot or 0):
            reason = rb.cost_batch.reason if rb.cost_batch else None
            if not (reason or "").strip():
                below_target_no_reason += 1
    # 7. Cost batch and route batch school counts do not match.
    count_mismatch = 0
    for rb in DailyVisitRouteBatch.objects.exclude(
        cost_batch__isnull=True
    ).select_related("cost_batch"):
        if rb.cost_batch and rb.school_count != rb.cost_batch.school_count:
            count_mismatch += 1
    # 8. Low location confidence on a scheduled visit day.
    low_confidence_days = batches.filter(
        confidence__in=["low", "needs_cleanup"]
    ).count()

    return {
        "plannedVisitNoRouteBatch": visits_without_route_batch,
        "schoolsWeakLocation": schools_weak_location,
        "mixedDistrictRouteDays": mixed_district_days,
        "ungroupedSecondaryDays": ungrouped_secondary_days,
        "routeLoadExceedsDay": overloaded_days,
        "belowTargetNoReason": below_target_no_reason,
        "costRouteCountMismatch": count_mismatch,
        "lowConfidenceScheduledDays": low_confidence_days,
    }


__all__ = ["route_intelligence_checks"]
