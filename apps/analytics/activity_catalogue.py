"""Catalogue-keyed execution and verified-impact analytics."""

from django.db.models import Avg, Count, Q, Sum

from apps.activities.models import Activity


VERIFIED_STATES = ("ia_verified", "accountant_confirmed", "closed")


def activity_catalogue_metrics(*, fy=None, project_id=None):
    qs = Activity.objects.filter(
        catalogue_item__isnull=False,
        deleted_at__isnull=True,
    )
    if fy:
        qs = qs.filter(fy=fy)
    if project_id:
        qs = qs.filter(project_id=project_id)
    return list(
        qs.values(
            "catalogue_item_id",
            "catalogue_item__stable_code",
            "activity_name_snapshot",
            "activity_type_snapshot",
            "delivery_method_snapshot",
        )
        .annotate(
            scheduled=Count("id"),
            verified=Count("id", filter=Q(status__in=VERIFIED_STATES)),
            schools_reached=Count("school_id", distinct=True),
            participants=Sum("teachers_attended", default=0)
            + Sum("leaders_attended", default=0)
            + Sum("other_participants", default=0),
            average_source_score=Avg("source_score"),
            total_cost=Sum("est_cost_cents", default=0),
        )
        .order_by("activity_name_snapshot")
    )


def verified_ssa_change_by_catalogue(*, fy=None, project_id=None):
    """Same-School, same-intervention change after verified support."""
    from apps.ssa.models import SsaRecord

    activities = (
        Activity.objects.filter(
            catalogue_item__isnull=False,
            source_ssa__isnull=False,
            focus_intervention__isnull=False,
            status__in=VERIFIED_STATES,
            deleted_at__isnull=True,
        )
        .select_related("catalogue_item", "source_ssa", "school")
        .prefetch_related("source_ssa__scores")
    )
    if fy:
        activities = activities.filter(fy=fy)
    if project_id:
        activities = activities.filter(project_id=project_id)
    rows = {}
    for activity in activities:
        source_score = activity.source_score
        if source_score is None:
            continue
        later = (
            SsaRecord.objects.filter(
                school=activity.school,
                verification_status="confirmed",
                deleted_at__isnull=True,
                date_of_ssa__gt=activity.source_ssa.date_of_ssa,
                scores__intervention=activity.focus_intervention,
            )
            .order_by("date_of_ssa")
            .values_list("scores__score", flat=True)
            .first()
        )
        if later is None:
            continue
        bucket = rows.setdefault(
            activity.catalogue_item_id,
            {
                "catalogueItemId": activity.catalogue_item_id,
                "stableCode": activity.catalogue_item.stable_code,
                "displayName": activity.activity_name_snapshot,
                "comparisons": 0,
                "totalChange": 0.0,
                "totalCost": 0,
            },
        )
        bucket["comparisons"] += 1
        bucket["totalChange"] += float(later) - float(source_score)
        bucket["totalCost"] += activity.est_cost_cents or 0
    result = []
    for bucket in rows.values():
        bucket["averageVerifiedSsaChange"] = round(
            bucket.pop("totalChange") / bucket["comparisons"], 2
        )
        bucket["costPerSsaPointImproved"] = (
            round(
                bucket["totalCost"]
                / (bucket["averageVerifiedSsaChange"] * bucket["comparisons"])
            )
            if bucket["averageVerifiedSsaChange"] > 0
            else None
        )
        result.append(bucket)
    return sorted(result, key=lambda row: row["displayName"].casefold())
