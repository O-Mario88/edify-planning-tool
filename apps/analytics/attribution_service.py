"""Intervention attribution: did the work move the scores? (2026-09-03)

For each SSA intervention, compare confirmed assessment scores in the
selected fiscal year with confirmed scores in the year before, across the
schools that have both, and set that movement beside the trainings and
visits delivered with that intervention in focus. Confirmed records only;
the share of confirmed assessments is stated so nobody reads an unverified
year as a verified one.
"""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Q

from apps.core.activity_types import COMPLETED_WORK_STATUSES
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope, scoped_school_queryset

TRAINING_TYPES = (
    "cluster_training",
    "general_training",
    "core_training",
    "in_school_training",
)
VISIT_TYPES = ("school_visit", "follow_up_visit", "coaching_visit", "core_visit")


def _latest_confirmed_scores(school_ids, fy):
    """{school_id: {intervention: score}} from the latest confirmed SSA in fy."""
    from apps.ssa.models import SsaRecord, SsaScore

    # Plain values, and the record→school map inverted once: the previous
    # shape built 16,000 score instances and searched the latest-record dict
    # for each of them (2.3 million comparisons, 1.5s a page, 2026-09-06).
    latest: dict = {}
    for school_id, record_id in (
        SsaRecord.objects.filter(
            school_id__in=school_ids,
            fy=fy,
            verification_status="confirmed",
            deleted_at__isnull=True,
        )
        .order_by("school_id", "-date_of_ssa")
        .values_list("school_id", "id")
    ):
        latest.setdefault(school_id, record_id)
    school_by_record = {record_id: school_id for school_id, record_id in latest.items()}
    scores = defaultdict(dict)
    for record_id, intervention, score in SsaScore.objects.filter(
        ssa_record_id__in=list(school_by_record)
    ).values_list("ssa_record_id", "intervention", "score"):
        scores[school_by_record[record_id]][intervention] = score
    return scores


def attribution(
    principal, fy: str | None = None, district_id: str | None = None
) -> dict:
    from apps.activities.models import Activity
    from apps.ssa.models import SsaRecord

    fy = fy or get_operational_fy()
    prior_fy = str(int(fy) - 1)
    scope = resolve_user_scope(principal)
    schools = scoped_school_queryset(scope)
    if district_id:
        schools = schools.filter(district_id=district_id)
    school_ids = list(schools.values_list("id", flat=True))
    district_of = dict(schools.values_list("id", "district__name"))

    latest = _latest_confirmed_scores(school_ids, fy)
    prior = _latest_confirmed_scores(school_ids, prior_fy)

    all_records = SsaRecord.objects.filter(
        school_id__in=school_ids, fy=fy, deleted_at__isnull=True
    )
    total_records = all_records.count()
    confirmed_records = all_records.filter(verification_status="confirmed").count()

    completed = Activity.objects.filter(
        deleted_at__isnull=True,
        fy=fy,
        status__in=COMPLETED_WORK_STATUSES,
        focus_intervention__isnull=False,
    ).filter(Q(school_id__in=school_ids) | Q(school__isnull=True))
    delivered = defaultdict(lambda: {"trainings": 0, "visits": 0})
    for atype, focus in completed.values_list("activity_type", "focus_intervention"):
        if atype in TRAINING_TYPES:
            delivered[focus]["trainings"] += 1
        elif atype in VISIT_TYPES:
            delivered[focus]["visits"] += 1

    rows = []
    district_movement = defaultdict(list)
    for value, label in SsaIntervention.choices:
        pairs = []
        for school_id, now_scores in latest.items():
            then = prior.get(school_id, {})
            if value in now_scores and value in then:
                delta = now_scores[value] - then[value]
                pairs.append(delta)
                district_movement[district_of.get(school_id) or "No district"].append(
                    delta
                )
        measured = len(pairs)
        avg_prior = (
            round(
                sum(
                    prior[s][value]
                    for s in latest
                    if value in prior.get(s, {}) and value in latest[s]
                )
                / measured,
                2,
            )
            if measured
            else None
        )
        avg_latest = (
            round(
                sum(
                    latest[s][value]
                    for s in latest
                    if value in prior.get(s, {}) and value in latest[s]
                )
                / measured,
                2,
            )
            if measured
            else None
        )
        movement = round(sum(pairs) / measured, 2) if measured else None
        improved = sum(1 for d in pairs if d > 0)
        rows.append(
            {
                "intervention": value,
                "label": label,
                "schools_measured": measured,
                "avg_prior": avg_prior,
                "avg_latest": avg_latest,
                "movement": movement,
                "improved_pct": round(improved / measured * 100) if measured else None,
                "trainings": delivered[value]["trainings"],
                "visits": delivered[value]["visits"],
                "tone": (
                    "success"
                    if movement is not None and movement > 0
                    else "danger"
                    if movement is not None and movement < 0
                    else "neutral"
                ),
            }
        )
    rows.sort(key=lambda r: (r["movement"] is None, -(r["movement"] or 0)))

    districts = [
        {
            "name": name,
            "measurements": len(deltas),
            "movement": round(sum(deltas) / len(deltas), 2),
            "improved_pct": round(sum(1 for d in deltas if d > 0) / len(deltas) * 100),
        }
        for name, deltas in district_movement.items()
    ]
    districts.sort(key=lambda r: -r["movement"])

    return {
        "fy": fy,
        "prior_fy": prior_fy,
        "schools_in_scope": len(school_ids),
        "schools_with_both_years": len([s for s in latest if s in prior]),
        "total_records": total_records,
        "confirmed_records": confirmed_records,
        "confirmed_share": round(confirmed_records / total_records * 100)
        if total_records
        else 0,
        "rows": rows,
        "districts": districts,
    }
