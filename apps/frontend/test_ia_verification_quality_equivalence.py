"""Old-against-new oracle for the Verification Quality speed-up (2026-09-24).

The Verification Quality tab (`_ia_dashboard_context`) and the dashboard's Map
view were changed for speed only:
  - the school-district and school-region roll-ups come from one GROUP BY
    (`_ia_activity_rollup_pair`) instead of two scans of the reach;
  - the evidence waiting for review is summed from the per-kind panel's
    query, and today's SSA uploads ride on the review donut's aggregate;
  - the school-reach rows are read without the model's default ordering.
The five functions involved are copied below verbatim from ee3fe7a as frozen
references, and the tests assert the whole view-model is unchanged — values,
types and order — for the IA, Country Director, Programme Lead and another
country's IA scopes, on a world with schools lacking a district, a region or
a cluster, event-district and cluster work with no school, partner work,
quarantined evidence, and SSA and evidence uploaded today and earlier.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from django.db.models import F, Q  # noqa: F401 - read by the frozen copies
from django.test import RequestFactory, TestCase
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.accounts.staff_matching import on_staff
from apps.activities.models import (
    Activity,
    DuplicateActivity,
    VerificationDecision,
    VerificationHistory,
)
from apps.clusters.models import Cluster
from apps.core.donut import build_gauge, build_rings
from apps.core.enums import ActivityStatus
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.frontend.views import ia_views
from apps.frontend.views.ia_views import (
    IA_VERIFICATION_SLA_HOURS,
    _ia_activities,
    _ia_districts,
    _ia_header_context,
    _ia_merge_rollups,
    _ia_merge_school_reach,
    _ia_performance_activities,
    _ia_reach_from_sets,
    _ia_regions,
    _ia_scope,
    _ia_school_scope,
    _ia_staff_queue,
    _ia_uploads,
    _ia_week_window,
)
from apps.geography.models import District, Region, SubRegion
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

#: A Thursday, mid-morning in Kampala; operational FY 2026.
FROZEN = "2026-09-24 06:30:00"


# ── Frozen references: the implementations at ee3fe7a, verbatim ─────────────


def _reference_ia_activity_rollup(queryset, geography_field):
    from django.db.models import Count

    from apps.targets.performance import ACHIEVED_STATUSES

    return {
        row[geography_field]: row
        for row in queryset.exclude(**{f"{geography_field}__isnull": True})
        .values(geography_field)
        .annotate(
            planned=Count("id"),
            achieved=Count("id", filter=Q(status__in=ACHIEVED_STATUSES)),
            verified=Count("id", filter=Q(ia_verification_status="confirmed")),
            waiting=Count(
                "id", filter=Q(status=ActivityStatus.AWAITING_IA_VERIFICATION)
            ),
            returned=Count("id", filter=Q(status=ActivityStatus.RETURNED_BY_IA)),
        )
    }


def _reference_ia_school_reach_sets(request, performance_qs):
    """School reach (owner, 2026-09-05): active schools per district, and the
    schools with planned and achieved work per district and per owner.

    Two queries serve every row on the page: the active schools in scope with
    their district, and the year's activities with owner, school, district and
    status; everything else is set arithmetic, so the query count stays a
    constant."""
    from apps.schools.lifecycle_service import active_schools
    from apps.targets.performance import ACHIEVED_STATUSES

    active_school_ids = set()
    schools_by_district: dict = {}
    for school_id, district_id in active_schools(_ia_school_scope(request)).values_list(
        "id", "district_id"
    ):
        active_school_ids.add(school_id)
        if district_id:
            schools_by_district[district_id] = (
                schools_by_district.get(district_id, 0) + 1
            )
    planned_by_district: dict = {}
    achieved_by_district: dict = {}
    planned_by_owner: dict = {}
    achieved_by_owner: dict = {}
    for owner_id, school_id, district_id, status in performance_qs.exclude(
        school_id__isnull=True
    ).values_list("responsible_staff_id", "school_id", "school__district_id", "status"):
        planned_by_owner.setdefault(owner_id, set()).add(school_id)
        if district_id:
            planned_by_district.setdefault(district_id, set()).add(school_id)
        if status in ACHIEVED_STATUSES:
            achieved_by_owner.setdefault(owner_id, set()).add(school_id)
            if district_id:
                achieved_by_district.setdefault(district_id, set()).add(school_id)
    return {
        "active_school_ids": active_school_ids,
        "schools_by_district": schools_by_district,
        "planned_by_district": planned_by_district,
        "achieved_by_district": achieved_by_district,
        "planned_by_owner": planned_by_owner,
        "achieved_by_owner": achieved_by_owner,
    }


def _reference_ia_geography_context(
    request, performance_qs=None, reach_sets=None
) -> dict:
    """Regional performance and district monitoring, bounded to the reader's
    country: the Map view's tables and the Verification Quality tab's cards.

    These are completion/verification facts from the Activity ledger, not a
    separate reporting store. Programme activities without a school inherit
    geography through event_district, so central work is not lost from the
    regional and district views.
    """
    if performance_qs is None:
        performance_qs = _ia_performance_activities(request)
    if reach_sets is None:
        reach_sets = _reference_ia_school_reach_sets(request, performance_qs)

    school_district_rollup = _reference_ia_activity_rollup(
        performance_qs, "school__district_id"
    )
    event_district_rollup = _reference_ia_activity_rollup(
        performance_qs, "event_district_id"
    )

    def _school_reach(district_id):
        schools = reach_sets["schools_by_district"].get(district_id, 0)
        achieved = len(reach_sets["achieved_by_district"].get(district_id, set()))
        return {
            "schools": schools,
            "schools_planned": len(
                reach_sets["planned_by_district"].get(district_id, set())
            ),
            "schools_achieved": achieved,
            "schools_pct": round(achieved / schools * 100) if schools else 0,
        }

    district_performance = []
    # Districts fold under their sub-region, the way clusters fold under the
    # person who holds them: one row per sub-region carrying the roll-up,
    # opened into its districts (owner, 2026-09-05). A district with no
    # sub-region sits under "Other districts" in its region rather than
    # vanishing.
    district_groups_by_key: dict = {}
    for district in (
        _ia_districts(request)
        .select_related("region", "sub_region")
        .order_by("region__name", "sub_region__name", "name")
    ):
        metrics = _ia_merge_rollups(
            school_district_rollup.get(district.id),
            event_district_rollup.get(district.id),
        )
        row = {
            "name": district.name,
            "region": district.region.name,
            "sub_region": district.sub_region.name if district.sub_region else None,
            **metrics,
            **_school_reach(district.id),
        }
        district_performance.append(row)
        key = (district.region.name, row["sub_region"] or "")
        group = district_groups_by_key.setdefault(
            key,
            {
                "key": f"{district.region_id}-{district.sub_region_id or 'other'}",
                "name": row["sub_region"] or "Other districts",
                "region": district.region.name,
                "districts": [],
            },
        )
        group["districts"].append(row)
    district_groups = []
    for group in district_groups_by_key.values():
        group.update(_ia_merge_rollups(*group["districts"]))
        group.update(_ia_merge_school_reach(group["districts"]))
        group["count"] = len(group["districts"])
        district_groups.append(group)

    school_region_rollup = _reference_ia_activity_rollup(
        performance_qs, "school__region_id"
    )
    event_region_rollup = _reference_ia_activity_rollup(
        performance_qs, "event_district__region_id"
    )
    region_performance = [
        {
            "name": region.name,
            **_ia_merge_rollups(
                school_region_rollup.get(region.id), event_region_rollup.get(region.id)
            ),
        }
        for region in _ia_regions(request).order_by("name")
    ]
    return {
        "district_performance": district_performance,
        "district_groups": district_groups,
        "region_performance": region_performance,
    }


def _reference_ia_operations_context(request, header: dict) -> dict:
    """The verification operations beneath the fixed header: the queue, open
    queues, exceptions, activity flow, CCEO and Programme Lead performance,
    quality, coverage and SSA review — every figure bounded to the reader's
    country (IA review, 2026-09-13), where they used to read the deployment."""
    from django.db.models import Avg, Count
    from django.db.models.functions import TruncWeek
    from django.utils.timesince import timesince

    from apps.accounts.models import (
        StaffProfile,
        StaffSchoolAssignment,
        StaffSupervisorAssignment,
        User,
    )
    from apps.core.enums import EvidenceKind, SsaIntervention
    from apps.core.fy import get_operational_fy
    from apps.core.rbac import EdifyRole
    from apps.debriefs.rollup_service import field_debrief_intelligence_summary
    from apps.evidence.models import EvidenceRecord
    from apps.partners.models import Partner
    from apps.ssa.models import SsaRecord, SsaScore

    now, today_start, week_start, _week_end = _ia_week_window()
    fy = get_operational_fy()
    scope = _ia_scope(request)

    activities = _ia_activities(request)
    reach_ids = activities.values("id")
    waiting_qs = _ia_staff_queue(request, activities)
    schools = _ia_school_scope(request)
    kpis = header["kpis"]
    waiting_cnt = kpis["waiting"]
    missing_sf_id = kpis["sf_queue"]
    returned_open = kpis["returned_open"]

    history = VerificationHistory.objects.filter(activity_id__in=reach_ids)
    decisions = VerificationDecision.objects.filter(
        verification__activity_id__in=reach_ids
    )
    verified_today = history.filter(verified_at__gte=today_start).count()
    verified_week = history.filter(verified_at__gte=week_start).count()

    # Verification SLA is measured from the moment an activity enters the IA
    # queue to its recorded verification.  Keep the query bounded to the
    # current and previous week so the dashboard remains constant-cost while
    # still providing an honest week-over-week comparison.
    previous_week_start = week_start - timedelta(days=7)
    sla_rows = history.filter(
        verified_at__gte=previous_week_start,
        verified_at__lte=now,
        activity__submitted_to_ia_at__isnull=False,
    ).values_list("verified_at", "activity__submitted_to_ia_at")
    current_sla_durations = []
    previous_sla_durations = []
    for verified_at, submitted_at in sla_rows:
        duration_hours = (verified_at - submitted_at).total_seconds() / 3600
        if verified_at >= week_start:
            current_sla_durations.append(duration_hours)
        else:
            previous_sla_durations.append(duration_hours)

    def _sla_percentage(durations):
        if not durations:
            return None
        return round(
            sum(duration <= IA_VERIFICATION_SLA_HOURS for duration in durations)
            / len(durations)
            * 100,
            1,
        )

    current_sla_pct = _sla_percentage(current_sla_durations)
    previous_sla_pct = _sla_percentage(previous_sla_durations)
    sla_delta = (
        round(current_sla_pct - previous_sla_pct, 1)
        if current_sla_pct is not None and previous_sla_pct is not None
        else None
    )
    verification_sla = {
        "pct": current_sla_pct,
        "sample_size": len(current_sla_durations),
        "previous_pct": previous_sla_pct,
        "delta": sla_delta,
    }
    verification_sla["gauge"] = (
        build_gauge(
            current_sla_pct,
            label="Within SLA",
            color="var(--edify-success)",
        )
        if current_sla_pct is not None
        else None
    )
    returned_today = decisions.filter(
        decision="RETURN", decided_at__gte=today_start
    ).count()
    returned_open_school_cnt = (
        activities.filter(status=ActivityStatus.RETURNED_BY_IA)
        .exclude(school_id__isnull=True)
        .values("school_id")
        .distinct()
        .count()
    )
    duplicate_risk_cnt = DuplicateActivity.objects.filter(
        status="potential", activity_id__in=reach_ids
    ).count()

    # ── Awaiting Follow-up (Grid Row 5) — real return→correction cycle time,
    # pairing each RETURN decision with the next APPROVE on the same
    # verification (a second RETURN before that APPROVE starts a new cycle).
    decision_rows = list(
        decisions.filter(decision__in=("RETURN", "APPROVE"))
        .order_by("verification_id", "decided_at")
        .values("verification_id", "decision", "decided_at")
    )
    decisions_by_verification = {}
    for row in decision_rows:
        decisions_by_verification.setdefault(row["verification_id"], []).append(row)
    resolution_days = []
    for rows in decisions_by_verification.values():
        pending_return_at = None
        for row in rows:
            if row["decision"] == "RETURN":
                pending_return_at = row["decided_at"]
            elif row["decision"] == "APPROVE" and pending_return_at:
                resolution_days.append(
                    (row["decided_at"] - pending_return_at).total_seconds() / 86400
                )
                pending_return_at = None
    avg_resolution_days = (
        round(sum(resolution_days) / len(resolution_days), 1)
        if resolution_days
        else None
    )

    # ── School-derived KPIs, one aggregate over the schools in scope ────────
    school_facts = schools.aggregate(
        total=Count("id"),
        ssa_done=Count("id", filter=Q(current_fy_ssa_status="done")),
        ssa_scheduled=Count(
            "id", filter=Q(current_fy_ssa_status__in=["scheduled", "partner_assigned"])
        ),
        duplicates=Count(
            "id", filter=Q(duplicate_status__in=["potential", "confirmed"])
        ),
        not_clean=Count("id", filter=~Q(data_quality_status="Clean")),
        quality_avg=Avg("data_quality_score"),
    )
    school_total = school_facts["total"]
    ssa_done_cnt = school_facts["ssa_done"]
    ssa_scheduled_cnt = school_facts["ssa_scheduled"]
    ssa_not_done_cnt = school_total - ssa_done_cnt - ssa_scheduled_cnt
    ssa_coverage = round(ssa_done_cnt / school_total * 100, 1) if school_total else 0.0
    quality_avg = school_facts["quality_avg"]
    quality_pct = round(quality_avg) if quality_avg is not None else 0
    dup_school_cnt = school_facts["duplicates"]

    ssa_records = SsaRecord.objects.filter(deleted_at__isnull=True, school__in=schools)
    evidence = EvidenceRecord.objects.filter(
        quarantined=False, activity_id__in=reach_ids
    )
    evidence_pending = evidence.filter(status="uploaded").count()
    uploads_today = (
        ssa_records.filter(created_at__gte=today_start).count()
        + EvidenceRecord.objects.filter(
            created_at__gte=today_start, activity_id__in=reach_ids
        ).count()
    )

    # ── District SSA completion stats (shared by exceptions + leaderboard) ──
    district_stats = list(
        _ia_districts(request)
        .annotate(
            total=Count("schools", filter=Q(schools__in=schools)),
            done=Count(
                "schools",
                filter=Q(schools__in=schools, schools__current_fy_ssa_status="done"),
            ),
        )
        .filter(total__gt=0)
    )
    districts_below_target = sum(1 for d in district_stats if d.done / d.total < 0.5)

    # ── Alerts / Exceptions (only real, non-zero conditions) ────────────────
    overdue_returns = activities.filter(
        status=ActivityStatus.RETURNED_BY_IA, updated_at__lt=now - timedelta(days=7)
    ).count()
    failed_uploads = (
        _ia_uploads(request).filter(status__in=["failed", "rejected"]).count()
    )
    exceptions = [
        e
        for e in [
            {
                "count": missing_sf_id,
                "text": "completed/verified activities missing Salesforce IDs",
                "severity": "error",
                "href": "/ia/verification/?sf_id=missing",
            },
            {
                "count": duplicate_risk_cnt,
                "text": "activities flagged as potential duplicates",
                "severity": "warning",
                "href": "/ia/duplicates/",
            },
            {
                "count": dup_school_cnt,
                "text": "schools flagged as potential duplicates",
                "severity": "warning",
                "href": "/data-quality/duplicates",
            },
            {
                # SSA Performance, reached from IA's workspace strip; the
                # generic Analytics hub is not an Impact Assessment door.
                "count": districts_below_target,
                "text": "districts below 50% SSA completion",
                "severity": "info",
                "href": "/ssa",
            },
            {
                "count": overdue_returns,
                "text": "activities returned for correction over 7 days ago",
                "severity": "warning",
                "href": "/ia/returned/",
            },
            {
                "count": failed_uploads,
                "text": "bulk uploads failed validation",
                "severity": "error",
                "href": "/uploads?tab=imports",
            },
        ]
        if e["count"] > 0
    ]

    # ── Data Quality & Compliance panel ─────────────────────────────────────
    dq_metrics = [
        {"label": "Schools Missing SSA", "value": school_total - ssa_done_cnt},
        {
            "label": "Duplicate Records Detected",
            "value": duplicate_risk_cnt + dup_school_cnt,
        },
        {"label": "Schools with Missing Fields", "value": school_facts["not_clean"]},
        {"label": "Activities Missing Salesforce IDs", "value": missing_sf_id},
    ]

    # ── SSA monitoring: lowest-performing interventions (0–10 score scale) ──
    # Confirmed-only (an unverified upload must not rank interventions), and
    # scoped strictly to the selected FY. There used to be a silent
    # all-time fallback here when the current FY had no rows, which
    # presented historical scores under a current-FY heading with nothing
    # telling the reader the period had changed — better to show an honest
    # empty state.
    score_rows = SsaScore.objects.filter(
        ssa_record__deleted_at__isnull=True,
        ssa_record__fy=fy,
        ssa_record__verification_status="confirmed",
        ssa_record__school__in=schools,
    )
    intervention_labels = dict(SsaIntervention.choices)
    lowest_performing = [
        {
            "name": intervention_labels.get(r["intervention"], r["intervention"]),
            "rate": round(r["avg"] / 10 * 100),
        }
        for r in score_rows.values("intervention")
        .annotate(avg=Avg("score"))
        .order_by("avg")[:5]
    ]

    # ── District SSA completion leaderboard (min 5 schools) ─────────────────
    leaderboard_dc = sorted(
        (
            {"name": d.name, "rate": round(d.done / d.total * 100)}
            for d in district_stats
            if d.total >= 5
        ),
        key=lambda item: -item["rate"],
    )[:5]

    # ── SSA donuts: school coverage + record review status ──────────────────
    from apps.core.metrics import percentage_or_zero as _pct

    ssa_overview = {
        "total": school_total,
        "done": ssa_done_cnt,
        "done_pct": _pct(ssa_done_cnt, school_total),
        "scheduled": ssa_scheduled_cnt,
        "scheduled_pct": _pct(ssa_scheduled_cnt, school_total),
        "not_done": ssa_not_done_cnt,
        "not_done_pct": _pct(ssa_not_done_cnt, school_total),
    }
    ssa_overview["scheduled_offset"] = -ssa_overview["done_pct"]
    ssa_overview["not_done_offset"] = -(
        ssa_overview["done_pct"] + ssa_overview["scheduled_pct"]
    )
    # Concentric rings: each state a share of the schools in scope, with "not
    # done" carried too — the gap is the point of this chart.
    ssa_overview["rings"] = build_rings(
        [
            {
                "key": "done",
                "label": "SSA done",
                "value": ssa_done_cnt,
                "color": "var(--edify-success)",
            },
            {
                "key": "scheduled",
                "label": "Scheduled",
                "value": ssa_scheduled_cnt,
                "color": "var(--edify-warning)",
            },
            {
                "key": "not_done",
                "label": "Not done",
                "value": ssa_not_done_cnt,
                "color": "var(--edify-danger)",
            },
        ],
        share_of=school_total or None,
    )

    ssa_record_facts = ssa_records.aggregate(
        total=Count("id"),
        confirmed=Count("id", filter=Q(verification_status="confirmed")),
        pending=Count("id", filter=Q(verification_status="pending")),
    )
    ssa_rec_total = ssa_record_facts["total"]
    ssa_rec_confirmed = ssa_record_facts["confirmed"]
    ssa_rec_pending = ssa_record_facts["pending"]
    ssa_rec_other = ssa_rec_total - ssa_rec_confirmed - ssa_rec_pending
    ssa_review = {
        "total": ssa_rec_total,
        "confirmed": ssa_rec_confirmed,
        "confirmed_pct": _pct(ssa_rec_confirmed, ssa_rec_total),
        "pending": ssa_rec_pending,
        "pending_pct": _pct(ssa_rec_pending, ssa_rec_total),
        "other": ssa_rec_other,
        "other_pct": _pct(ssa_rec_other, ssa_rec_total),
    }
    ssa_review["rings"] = build_rings(
        [
            {
                "key": "confirmed",
                "label": "Confirmed",
                "value": ssa_rec_confirmed,
                "color": "var(--edify-chart-teal)",
            },
            {
                "key": "pending",
                "label": "Pending",
                "value": ssa_rec_pending,
                "color": "var(--edify-warning)",
            },
            {
                "key": "other",
                "label": "Returned / flagged",
                "value": ssa_rec_other,
                "color": "var(--edify-danger)",
            },
        ],
        share_of=ssa_rec_total or None,
    )

    # ── Evidence review panel (grouped by kind, split by review status) ─────
    kind_labels = dict(EvidenceKind.choices)
    evidence_metrics = [
        {
            "category": kind_labels.get(row["kind"], row["kind"]),
            "submitted": row["submitted"],
            "verified": row["verified"],
            "returned": row["returned"],
            "rejected": row["rejected"],
        }
        for row in evidence.values("kind")
        .annotate(
            submitted=Count("id"),
            verified=Count("id", filter=Q(status="accepted")),
            returned=Count("id", filter=Q(status="returned")),
            rejected=Count("id", filter=Q(status="rejected")),
        )
        .order_by("-submitted")
    ]
    evidence_totals = {
        "submitted": sum(m["submitted"] for m in evidence_metrics),
        "verified": sum(m["verified"] for m in evidence_metrics),
        "returned": sum(m["returned"] for m in evidence_metrics),
        "rejected": sum(m["rejected"] for m in evidence_metrics),
    }

    # ── Recent activity feed (verifications + returns, merged by time) ──────
    def _activity_detail(a):
        school = a.school.name if a.school else "Cluster"
        district = a.school.district.name if a.school and a.school.district_id else ""
        return f"{school}, {district}" if district else school

    events = []
    for vh in history.select_related(
        "activity", "activity__school", "activity__school__district"
    ).order_by("-verified_at")[:5]:
        events.append(
            {
                "title": f"{vh.activity.get_activity_type_display()} verified",
                "detail": _activity_detail(vh.activity),
                "ts": vh.verified_at,
            }
        )
    for vd in (
        decisions.filter(decision="RETURN")
        .select_related(
            "verification__activity",
            "verification__activity__school",
            "verification__activity__school__district",
        )
        .order_by("-decided_at")[:5]
    ):
        events.append(
            {
                "title": f"{vd.verification.activity.get_activity_type_display()} returned for correction",
                "detail": _activity_detail(vd.verification.activity),
                "ts": vd.decided_at,
            }
        )
    events.sort(key=lambda e: e["ts"], reverse=True)
    recent_activities = [
        {
            "title": e["title"],
            "detail": e["detail"],
            "time": f"{timesince(e['ts'])} ago",
        }
        for e in events[:5]
    ]

    # ── Field monitoring leaderboards ───────────────────────────────────────
    pending_rows = list(
        waiting_qs.exclude(responsible_staff_id__isnull=True)
        .exclude(responsible_staff_id="")
        .values("responsible_staff_id")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    )
    verifier_rows = list(
        history.filter(verified_at__gte=week_start)
        .values("verified_by")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    )
    fm_user_ids = {r["responsible_staff_id"] for r in pending_rows} | {
        r["verified_by"] for r in verifier_rows
    }
    fm_names = (
        dict(User.objects.filter(id__in=fm_user_ids).values_list("id", "name"))
        if fm_user_ids
        else {}
    )

    # Partner submissions wait in their own queue, so they are read from the
    # reach directly rather than from the staff queue above.
    partner_rows = list(
        activities.filter(
            status=ActivityStatus.AWAITING_IA_VERIFICATION, delivery_type="partner"
        )
        .exclude(assigned_partner_id__isnull=True)
        .exclude(assigned_partner_id="")
        .values("assigned_partner_id")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    )
    partner_names = (
        dict(
            Partner.objects.filter(
                id__in=[r["assigned_partner_id"] for r in partner_rows]
            ).values_list("id", "name")
        )
        if partner_rows
        else {}
    )

    field_monitoring = {
        "highest_pending": [
            {
                "name": fm_names.get(
                    r["responsible_staff_id"], r["responsible_staff_id"]
                ),
                "count": r["c"],
            }
            for r in pending_rows
        ],
        "partner_submissions": [
            {
                "name": partner_names.get(
                    r["assigned_partner_id"], r["assigned_partner_id"]
                ),
                "count": r["c"],
            }
            for r in partner_rows
        ],
        "top_verifiers": [
            {"name": fm_names.get(r["verified_by"], r["verified_by"]), "count": r["c"]}
            for r in verifier_rows
        ],
    }

    # ── IA country oversight: every CCEO and PL in the country ──────────────
    performance_qs = _ia_performance_activities(request)
    reach_sets = _reference_ia_school_reach_sets(request, performance_qs)

    # Activity.responsible_staff_id deliberately accepts either StaffProfile
    # or User ids for compatibility. Aggregate once, then resolve both id
    # spaces in memory so the roster remains constant-query at any team size.
    owner_rollup = _reference_ia_activity_rollup(performance_qs, "responsible_staff_id")
    from apps.core.scoping import country_bound

    roster = on_staff(StaffProfile.objects)
    if country_bound(scope):
        roster = roster.filter(country=scope.country)
    active_staff_roster = list(
        # on_staff, not is_active: a pending-invite CCEO created by a school upload already holds their portfolio.
        roster.select_related("user").order_by("user__name")
    )
    monitored_staff = [
        staff
        for staff in active_staff_roster
        if {EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value}.intersection(
            set(staff.user.roles or []) | {staff.user.active_role}
        )
    ]
    staff_by_id = {staff.id: staff for staff in active_staff_roster}
    team_ids_by_pl = {}
    pl_by_supervisee: dict = {}
    for supervisor_id, supervisee_id in StaffSupervisorAssignment.objects.filter(
        supervisor_id__in=[
            staff.id
            for staff in monitored_staff
            if EdifyRole.COUNTRY_PROGRAM_LEAD.value
            in (set(staff.user.roles or []) | {staff.user.active_role})
        ]
    ).values_list("supervisor_id", "supervisee_id"):
        supervisee = staff_by_id.get(supervisee_id)
        if supervisee:
            team_ids_by_pl.setdefault(supervisor_id, set()).update(
                {supervisee.id, supervisee.user_id}
            )
            pl_by_supervisee.setdefault(supervisee.id, supervisor_id)

    # School reach per leader (owner, 2026-09-05): the schools in a CCEO's
    # portfolio, how many of them have planned and achieved work this year,
    # and the share. A Program Lead's figures are the team's, consolidated as
    # SETS — a school two CCEOs both touched is one school reached, and the
    # portfolio is the union of the team's portfolios plus the lead's own.
    assigned_schools_by_staff: dict = {}
    for staff_id, school_id in StaffSchoolAssignment.objects.filter(
        staff_id__in=[staff.id for staff in monitored_staff]
    ).values_list("staff_id", "school_id"):
        if school_id in reach_sets["active_school_ids"]:
            assigned_schools_by_staff.setdefault(staff_id, set()).add(school_id)
    leadership_performance = []
    school_sets_by_staff: dict = {}
    for staff in monitored_staff:
        roles = set(staff.user.roles or []) | {staff.user.active_role}
        is_pl = EdifyRole.COUNTRY_PROGRAM_LEAD.value in roles
        owner_ids = (
            team_ids_by_pl.get(staff.id, set()) | {staff.id, staff.user_id}
            if is_pl
            else {staff.id, staff.user_id}
        )
        metrics = _ia_merge_rollups(
            *(owner_rollup.get(owner_id) for owner_id in owner_ids)
        )
        # Portfolio holders are StaffProfile ids; activity owners may be either
        # id space, so reach is read across both.
        portfolio_ids = {staff.id} | (
            {oid for oid in owner_ids if oid in assigned_schools_by_staff}
            if is_pl
            else set()
        )
        sets = (
            set().union(
                *(assigned_schools_by_staff.get(sid, set()) for sid in portfolio_ids)
            ),
            set().union(
                *(reach_sets["planned_by_owner"].get(oid, set()) for oid in owner_ids)
            ),
            set().union(
                *(reach_sets["achieved_by_owner"].get(oid, set()) for oid in owner_ids)
            ),
        )
        school_sets_by_staff[staff.id] = sets
        leadership_performance.append(
            {
                "staff_id": staff.id,
                "name": staff.user.name,
                "role": "Program Lead" if is_pl else "CCEO",
                "scope": "Team portfolio" if is_pl else "Owned activities",
                "supervisor_id": None if is_pl else pl_by_supervisee.get(staff.id),
                **metrics,
                **_ia_reach_from_sets(*sets),
            }
        )
    leadership_performance.sort(
        key=lambda row: (row["role"] != "Program Lead", row["name"].casefold())
    )

    # CCEOs fold under the Program Lead who supervises them, the way clusters
    # fold under the person who holds them: the Program Lead's row is the
    # header, carrying the team portfolio, opened into the team (owner,
    # 2026-09-05). A CCEO nobody supervises sits under "No Program Lead".
    leaders_by_id = {
        row["staff_id"]: row
        for row in leadership_performance
        if row["role"] == "Program Lead"
    }
    leadership_groups = [
        {**row, "key": row["staff_id"], "members": []} for row in leaders_by_id.values()
    ]
    unsupervised = {
        "key": "unsupervised",
        "name": "No Program Lead",
        "role": None,
        "scope": "CCEOs without a supervisor",
        "members": [],
    }
    for row in leadership_performance:
        if row["role"] != "CCEO":
            continue
        home = next(
            (
                group
                for group in leadership_groups
                if group["key"] == row["supervisor_id"]
            ),
            None,
        )
        (home or unsupervised)["members"].append(row)
    if unsupervised["members"]:
        unsupervised.update(_ia_merge_rollups(*unsupervised["members"]))
        member_sets = [
            school_sets_by_staff[m["staff_id"]] for m in unsupervised["members"]
        ]
        unsupervised.update(
            _ia_reach_from_sets(
                *(set().union(*(sets[i] for sets in member_sets)) for i in range(3))
            )
        )
        leadership_groups.append(unsupervised)
    for group in leadership_groups:
        group["count"] = len(group["members"])

    # Eight-week planned-versus-IA-verified line chart, drawn by the chart
    # system from these weekly values (2026-09-05), with text/table
    # equivalents retained for accessibility and zero-JavaScript rendering.
    trend_start = week_start - timedelta(weeks=7)
    planned_by_week = {
        row["week_bucket"].date()
        if hasattr(row["week_bucket"], "date")
        else row["week_bucket"]: row["count"]
        for row in performance_qs.filter(planned_date__gte=trend_start.date())
        .annotate(week_bucket=TruncWeek("planned_date"))
        .values("week_bucket")
        .annotate(count=Count("id"))
    }
    verified_by_week = {
        row["week_bucket"].date()
        if hasattr(row["week_bucket"], "date")
        else row["week_bucket"]: row["count"]
        for row in history.filter(verified_at__gte=trend_start)
        .annotate(week_bucket=TruncWeek("verified_at"))
        .values("week_bucket")
        .annotate(count=Count("id"))
    }
    weekly_values = []
    for offset in range(8):
        start = (trend_start + timedelta(weeks=offset)).date()
        weekly_values.append(
            {
                "label": start.strftime("%d %b"),
                "planned": planned_by_week.get(start, 0),
                "verified": verified_by_week.get(start, 0),
            }
        )
    trend_max = max(
        [1]
        + [row["planned"] for row in weekly_values]
        + [row["verified"] for row in weekly_values]
    )
    activity_trend = {"weeks": weekly_values, "max": trend_max}

    return {
        "fy": fy,
        "kpis": {
            **kpis,
            "waiting": waiting_cnt,
            "verified_today": verified_today,
            "verified_week": verified_week,
            "returned_today": returned_today,
            "returned_open": returned_open,
            "duplicate_risk": duplicate_risk_cnt,
            "ssa_coverage": f"{ssa_coverage}%",
            "quality": f"{quality_pct}%",
            "quality_pct": quality_pct,
            "uploads_today": uploads_today,
            "sf_queue": missing_sf_id,
            "ssa_pending_review": ssa_rec_pending,
            "evidence_pending": evidence_pending,
        },
        "exceptions": exceptions,
        "dq_metrics": dq_metrics,
        "lowest_performing": lowest_performing,
        "leaderboard_dc": leaderboard_dc,
        "ssa_overview": ssa_overview,
        "ssa_review": ssa_review,
        "evidence_metrics": evidence_metrics,
        "evidence_totals": evidence_totals,
        "recent_activities": recent_activities,
        "field_monitoring": field_monitoring,
        "leadership_performance": leadership_performance,
        "leadership_groups": leadership_groups,
        "activity_trend": activity_trend,
        "upload_status": {**header["upload_status"], "failed": failed_uploads},
        "returned_open_school_cnt": returned_open_school_cnt,
        "avg_resolution_days": avg_resolution_days,
        "verification_sla": verification_sla,
        "field_debrief_intel": field_debrief_intelligence_summary(request.user),
        # Carried for the operations roll-ups below the queue and the
        # Verification Quality tab's geography cards.
        "_performance_qs": performance_qs,
        "_reach_sets": reach_sets,
    }


def _reference_ia_dashboard_context(request) -> dict:
    """Everything the IA dashboard shows, computed live, for the Analytics
    workspace's Verification Quality tab (owner, 2026-09-05): the fixed header
    context, the operations and the geography cards together.

    /ia/dashboard/ itself builds only the part each view renders
    (IA_DASHBOARD_VIEW_BUILDERS below).
    """
    context = _ia_header_context(request)
    operations = _reference_ia_operations_context(request, context)
    performance_qs = operations.pop("_performance_qs")
    reach_sets = operations.pop("_reach_sets")
    context.update(operations)
    context.update(_reference_ia_geography_context(request, performance_qs, reach_sets))
    return context


# ── Helpers ─────────────────────────────────────────────────────────────────

IA = EdifyRole.IMPACT_ASSESSMENT.value


def _typed(value):
    """A value with the exact type of everything in it, so 1 never equals 1.0
    and a date never equals a datetime by accident; dict order counts."""
    if isinstance(value, dict):
        return ("dict", [(_typed(key), _typed(item)) for key, item in value.items()])
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, [_typed(item) for item in value])
    if isinstance(value, (set, frozenset)):
        return (type(value).__name__, sorted(repr(_typed(item)) for item in value))
    if isinstance(value, float) and value != value:
        return ("float", "nan")
    if value is None or isinstance(
        value, (str, int, float, Decimal, date, time, timedelta)
    ):
        return (type(value).__name__, value)
    if hasattr(value, "__dict__"):
        public = {k: v for k, v in vars(value).items() if not k.startswith("_")}
        return (type(value).__name__, _typed(public))
    return (type(value).__name__, repr(value))


def _by_key(value):
    """Dicts and sets compared by content alone, for data read by lookup."""
    if isinstance(value, dict):
        return sorted((repr(key), _by_key(item)) for key, item in value.items())
    if isinstance(value, (set, frozenset)):
        return sorted(repr(item) for item in value)
    return _typed(value)


def _user(email, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].replace("-", " ").title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country=country)
    return User.objects.select_related("staff_profile").get(pk=user.pk)


def _request(user):
    request = RequestFactory().get("/analytics/verification-quality")
    request.user = user
    return request


@freeze_time(FROZEN)
class VerificationQualityOracleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        today = now.date()
        central = Region.objects.create(name="VQ Central", country="Uganda")
        west = Region.objects.create(name="VQ West", country="Uganda")
        coast = Region.objects.create(name="VQ Coast", country="Kenya")
        acholi = SubRegion.objects.create(
            name="VQ Acholi", normalized_name="vq acholi", region=central
        )
        d1 = District.objects.create(
            name="VQ Wakiso", region=central, sub_region=acholi
        )
        d2 = District.objects.create(name="VQ Kasese", region=west)
        # Event-district work only: no school sits here.
        d3 = District.objects.create(name="VQ Gulu", region=central, sub_region=acholi)
        kd = District.objects.create(name="VQ Mombasa", region=coast)
        cluster = Cluster.objects.create(name="VQ Cluster", region=central, district=d1)

        def school(code, region=None, district=None, **fields):
            row = School.objects.create(
                name=f"VQ {code}", school_id=code, region=region, district=district
            )
            if fields:
                School.objects.filter(pk=row.pk).update(**fields)
            return row

        schools = [
            school(
                "VQ-A1",
                central,
                d1,
                cluster_id=cluster.id,
                current_fy_ssa_status="done",
            ),
            school(
                "VQ-A2",
                central,
                d1,
                current_fy_ssa_status="scheduled",
                duplicate_status="potential",
            ),
            school(
                "VQ-B1",
                west,
                d2,
                current_fy_ssa_status="done",
                data_quality_status="Missing Critical Data",
                data_quality_score=35,
            ),
            school("VQ-B2", west, d2, current_fy_ssa_status="partner_assigned"),
            # No district; no region either (every country lens reaches it).
            school("VQ-REGION", central),
            school("VQ-UNPLACED"),
            school("VQ-KE", coast, kd, current_fy_ssa_status="done"),
        ]
        a1, a2, b1, b2, region_only, unplaced, kenya = schools

        cls.ia = _user("vq-ia@t.org", IA)
        cls.ia2 = _user("vq-ia2@t.org", IA)
        cls.cd = _user("vq-cd@t.org", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.pl = _user("vq-pl@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.ke_ia = _user("vq-ke-ia@t.org", IA, "Kenya")
        cceos = [_user(f"vq-cceo{i}@t.org", EdifyRole.CCEO.value) for i in range(3)]
        for cceo in cceos[:2]:  # the third has no Programme Lead
            StaffSupervisorAssignment.objects.create(
                supervisor=cls.pl.staff_profile, supervisee=cceo.staff_profile
            )
        for staff, owned in (
            (cceos[0], [a1, a2]),
            (cceos[1], [b1]),
            (cceos[2], [b2]),
            (cls.pl, [region_only]),
        ):
            for row in owned:
                StaffSchoolAssignment.objects.create(
                    staff=staff.staff_profile, school_id=row.id
                )

        # Owners in both id spaces (staff profile and user), and IA's own work.
        owners = [
            cceos[0].staff_profile.id,
            cceos[1].staff_profile.id,
            cceos[2].id,
            cls.pl.staff_profile.id,
            cls.pl.id,
            cls.ia.staff_profile.id,
        ]
        statuses = [
            "planned",
            "completed",
            "ia_verified",
            "awaiting_ia_verification",
            "returned_by_ia",
            "accountant_confirmed",
            "closed",
            "cancelled",
            "evidence_uploaded",
        ]
        activities = []
        for i, row in enumerate(schools):
            for j, status in enumerate(statuses):
                k = i * len(statuses) + j
                activities.append(
                    Activity.objects.create(
                        school=row,
                        activity_type="school_visit",
                        delivery_type="partner" if k % 7 == 3 else "staff",
                        status=status,
                        responsible_staff_id=owners[k % len(owners)],
                        fy="2026",
                        quarter="Q4",
                        planned_date=today - timedelta(days=(3 * k) % 55),
                        salesforce_activity_id=(
                            None if k % 5 == 1 and status != "closed" else f"SF-VQ-{k}"
                        ),
                        ia_verification_status=(
                            "confirmed"
                            if status
                            in ("ia_verified", "closed", "accountant_confirmed")
                            else "pending"
                        ),
                        submitted_to_ia_at=(
                            now - timedelta(hours=5 + 9 * k)
                            if status == "awaiting_ia_verification"
                            else None
                        ),
                    )
                )
        # Work with no school: event districts (one with no school at all) and
        # a cluster meeting; then last year's work and a deleted row.
        for k, (district, status) in enumerate(
            [
                (d3, "ia_verified"),
                (d3, "planned"),
                (d2, "completed"),
                (d3, "returned_by_ia"),
            ]
        ):
            activities.append(
                Activity.objects.create(
                    activity_type="cluster_training",
                    status=status,
                    responsible_staff_id=cceos[k % 2].staff_profile.id,
                    event_district=district,
                    fy="2026",
                    quarter="Q4",
                    planned_date=today - timedelta(days=4 * k),
                    salesforce_activity_id=f"SF-VQ-E{k}",
                    ia_verification_status="confirmed"
                    if status == "ia_verified"
                    else "pending",
                )
            )
        activities.append(
            Activity.objects.create(
                cluster=cluster,
                activity_type="cluster_meeting",
                status="ia_verified",
                responsible_staff_id=cceos[0].staff_profile.id,
                fy="2026",
                quarter="Q4",
                planned_date=today - timedelta(days=9),
                salesforce_activity_id="SF-VQ-C1",
                ia_verification_status="confirmed",
            )
        )
        Activity.objects.create(
            school=a1,
            activity_type="school_visit",
            status="ia_verified",
            responsible_staff_id=cceos[0].staff_profile.id,
            fy="2025",
            quarter="Q4",
            planned_date=date(2025, 8, 1),
            salesforce_activity_id="SF-VQ-OLD",
        )
        Activity.objects.create(
            school=b1,
            activity_type="school_visit",
            status="planned",
            responsible_staff_id=cceos[1].staff_profile.id,
            fy="2026",
            quarter="Q4",
            planned_date=today,
            deleted_at=now,
        )

        # Evidence: several kinds and review states, quarantined files, and
        # uploads from today and from earlier in the week.
        kinds = ["photo", "visit_form", "attendance_form"]
        states = [
            "uploaded",
            "accepted",
            "returned",
            "rejected",
            "uploaded",
            "accepted",
        ]
        earlier = []
        for m, activity in enumerate(activities):
            for n in range(1 + m % 2):
                record = EvidenceRecord.objects.create(
                    activity=activity,
                    kind=kinds[(m + n) % 3],
                    status=states[(m + 2 * n) % 6],
                    quarantined=(m + n) % 11 == 4,
                    uploaded_by=cceos[0].id,
                    uri=f"vq-{m}-{n}",
                )
                if (m + n) % 3 == 0:
                    earlier.append(record.pk)
        EvidenceRecord.objects.filter(pk__in=earlier).update(
            created_at=now - timedelta(days=3)
        )

        # SSA records in three review states, uploaded today and earlier, with
        # and without an average score; one soft-deleted.
        codes = [
            "christlike_behaviour",
            "exposure_to_word_of_god",
            "leadership",
            "financial_health",
        ]
        before = []
        for m, row in enumerate(schools):
            for status in ("confirmed", "pending", "returned"):
                record = SsaRecord.objects.create(
                    school=row,
                    fy="2026",
                    quarter="Q3",
                    date_of_ssa=now - timedelta(days=30 + m),
                    verification_status=status,
                    average_score=None if m % 3 == 0 else 5.5,
                    uploaded_by="vq",
                )
                SsaScore.objects.bulk_create(
                    SsaScore(
                        ssa_record=record, intervention=code, score=((m + j) % 9) + 0.25
                    )
                    for j, code in enumerate(codes)
                )
                if m % 2:
                    before.append(record.pk)
        SsaRecord.objects.filter(pk__in=before).update(
            created_at=now - timedelta(days=2)
        )
        SsaRecord.objects.filter(school=b2, verification_status="pending").update(
            deleted_at=now
        )

        # A verification cycle, a return and a potential duplicate.
        verified = activities[2]
        VerificationHistory.objects.create(
            activity=verified,
            verified_by=cls.ia2.id,
            verified_at=now - timedelta(hours=3),
        )
        Activity.objects.filter(pk=verified.pk).update(
            submitted_to_ia_at=now - timedelta(hours=30)
        )
        DuplicateActivity.objects.create(
            activity=activities[0], duplicate_of=activities[1], reason="same day"
        )
        cls.users = (cls.ia, cls.cd, cls.pl, cls.ke_ia)

    def test_the_world_reaches_every_changed_figure(self):
        context = _reference_ia_dashboard_context(_request(self.ia))
        self.assertGreater(context["kpis"]["evidence_pending"], 0)
        self.assertGreater(context["kpis"]["uploads_today"], 0)
        self.assertGreaterEqual(len(context["evidence_metrics"]), 3)
        self.assertTrue(any(row["planned"] for row in context["district_performance"]))
        self.assertTrue(any(row["planned"] for row in context["region_performance"]))
        gulu = next(
            r for r in context["district_performance"] if r["name"] == "VQ Gulu"
        )
        self.assertGreater(gulu["planned"], 0)  # event-district work only
        self.assertEqual(gulu["schools"], 0)
        self.assertTrue(
            any(g["name"] == "No Program Lead" for g in context["leadership_groups"])
        )

    def test_the_verification_quality_view_model_matches_the_reference(self):
        for user in self.users:
            with self.subTest(
                role=user.active_role, country=user.staff_profile.country
            ):
                reference = _reference_ia_dashboard_context(_request(user))
                new = ia_views._ia_dashboard_context(_request(user))
                self.assertEqual(_typed(new), _typed(reference))

    def test_the_map_views_geography_matches_the_reference(self):
        for user in self.users:
            with self.subTest(
                role=user.active_role, country=user.staff_profile.country
            ):
                reference = _reference_ia_geography_context(_request(user))
                new = ia_views._ia_geography_context(_request(user))
                self.assertEqual(_typed(new), _typed(reference))

    def test_rollups_and_school_reach_match_the_reference(self):
        request = _request(self.ia)
        performance = _ia_performance_activities(request)
        for fields in (
            ("school__district_id", "school__region_id"),
            ("event_district_id", "event_district__region_id"),
        ):
            with self.subTest(fields=fields):
                pair = ia_views._ia_activity_rollup_pair(performance, *fields)
                reference = tuple(
                    _reference_ia_activity_rollup(performance, field)
                    for field in fields
                )
                # Keyed lookups only: the pair is read by id, never iterated.
                self.assertEqual(
                    [_typed(dict(sorted(rollup.items()))) for rollup in pair],
                    [_typed(dict(sorted(rollup.items()))) for rollup in reference],
                )
        for field in (
            "responsible_staff_id",
            "school__district_id",
            "event_district_id",
        ):
            with self.subTest(field=field):
                self.assertEqual(
                    _typed(ia_views._ia_activity_rollup(performance, field)),
                    _typed(_reference_ia_activity_rollup(performance, field)),
                )
        # Read by key only (never iterated), so compared by key.
        self.assertEqual(
            _by_key(ia_views._ia_school_reach_sets(request, performance)),
            _by_key(_reference_ia_school_reach_sets(request, performance)),
        )
