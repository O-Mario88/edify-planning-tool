"""MyTargetQueryService — the personal performance operating page engine.

This is the individual "My Targets" system -- separate from the leadership
scope-level TargetSetting system in apps/targets/services.py. The two share
the word "target" but not a data model; neither reads nor writes the other.

Monthly targets are the source of truth (explicit MonthlyPersonalTarget rows,
else the annual StaffTargetProfile split across the 12 FY months so the FY sum
still equals the annual value). Q1–Q4 and FY Cumulative are ALWAYS derived
sums. Achievements come only from the TargetAchievementLedger, which is
rebuilt idempotently from real workflow records and credits each record to the
month the work actually happened — a late validation credits the original
month, a return reverses the credit. Every number is traceable to a source
record; every gap has a reason; every focus area has a real next action.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from apps.accounts.models import StaffTargetProfile
from apps.activities.models import Activity
from apps.core.fy import get_fy_date_range, get_month_date_range
from apps.ssa.models import SsaRecord

from apps.targets.fy_calendar import (
    MONTH_LABELS,
    QUARTERS,
    FinancialYearCalendarService as Cal,
)
from apps.targets.models import (
    MonthlyPersonalTarget,
    MostSignificantChangeStory,
    TargetAchievementLedger,
    TargetArea,
)

# Workflow vocabularies (shared with the analytics layer).
from apps.analytics.pl_analytics_service import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)

# Target CREDIT requires IA verification (§8: "no target or impact result may
# be treated as verified before IA approval"). COMPLETED_STATUSES is broader —
# it counts pre-IA execution for the PL execution-progress metric — so the
# ledger uses this stricter set to decide "validated" (credited) vs
# "provisional" (executed, visible, but not yet counted).
IA_VERIFIED_STATUSES = ("ia_verified", "closed", "accountant_confirmed")

RETURNED_STATUSES = ("returned_by_pl", "returned_by_ia", "cancelled", "rejected")

# Pacing thresholds (mandate §11) — configurable in one place.
ON_TRACK_BAND = 5  # within ±5pp of expected pace
AT_RISK_BAND = 20  # 6–20pp below pace

AREA_SOURCES = {
    "school_visits": ("activity", VISIT_TYPES),
    "cluster_meetings": ("activity", CLUSTER_MEETING_TYPES),
    "cluster_trainings": ("activity", TRAINING_TYPES),
    "ssa_completed": ("ssa_record", None),
    "mscs": ("mscs", None),
}

# Performance agreements are the authority for which measurable priorities
# appear on My Targets and Team Targets.  TargetArea remains the canonical
# achievement-ledger dimension; it no longer decides which rows a person sees.
PERFORMANCE_METRIC_TO_AREA = {
    "direct_visits": "school_visits",
    "cluster_meetings": "cluster_meetings",
    "trainings": "cluster_trainings",
    "ssa_coverage": "ssa_completed",
    "mscs": "mscs",
}


@dataclass(frozen=True)
class PriorityTargetArea:
    """A user-owned performance priority projected onto the target ledger."""

    key: str
    label: str
    weight: int
    sort_order: int
    annual_target: int | None = None
    priority_id: str | None = None
    source: str = "performance_priority"


# Annual StaffTargetProfile fallback per area (used only when no explicit
# monthly targets exist — split across 12 months, remainder to early months,
# so the FY rollup still equals the configured annual target).
ANNUAL_FALLBACK = {
    "school_visits": lambda tp: tp.visits_target or 0,
    "cluster_meetings": lambda tp: tp.cluster_meetings_target or 0,
    "cluster_trainings": lambda tp: (tp.trainings_target or 0)
    + (tp.group_trainings_target or 0),
    "ssa_completed": lambda tp: tp.ssa_target or 0,
    "mscs": lambda tp: 0,  # MSCS has no annual field — monthly assignment only
}

# These are platform reference data, not optional user-entered configuration.
# The migration seeds them for an installation, while this small repair guard
# restores a missing row if a database restore, test flush, or historic manual
# deletion removed it. Existing rows (including their configured weights) are
# never overwritten here.
OFFICIAL_TARGET_AREAS = (
    ("school_visits", "School Visits", 30, 1),
    ("cluster_meetings", "Cluster Meetings", 15, 2),
    ("cluster_trainings", "Cluster Trainings", 20, 3),
    ("ssa_completed", "SSA Completed", 25, 4),
    ("mscs", "MSCS", 10, 5),
)


def active_target_areas() -> list[TargetArea]:
    """Return the official active target areas, repairing only missing rows.

    Memoized for the life of a request. This is org-wide configuration, not
    per-user data, but it was re-read on every ledger rebuild — 96 identical
    queries on a single Country Director dashboard, which resolves the whole
    country's staff. Outside a request there is no cache at all, so the
    self-repair below still sees live data.
    """
    from apps.core.request_cache import store

    bucket = store()
    if bucket is not None and "target_areas" in bucket:
        return bucket["target_areas"]
    areas = list(TargetArea.objects.filter(active=True).order_by("sort_order"))
    active_keys = {area.key for area in areas}
    missing = [area for area in OFFICIAL_TARGET_AREAS if area[0] not in active_keys]
    if not missing:
        if bucket is not None:
            bucket["target_areas"] = areas
        return areas

    existing_keys = set(
        TargetArea.objects.filter(key__in=[area[0] for area in missing]).values_list(
            "key", flat=True
        )
    )
    for key, label, weight, sort_order in missing:
        # An explicitly inactive record is an administrator's policy choice;
        # only a genuinely absent reference row is repaired automatically.
        if key not in existing_keys:
            TargetArea.objects.get_or_create(
                key=key,
                defaults={
                    "label": label,
                    "weight": weight,
                    "sort_order": sort_order,
                    "active": True,
                },
            )
    repaired = list(TargetArea.objects.filter(active=True).order_by("sort_order"))
    if bucket is not None:
        bucket["target_areas"] = repaired
    return repaired


def priority_target_areas_for_users(
    users, fy: str
) -> dict[str, list[PriorityTargetArea]]:
    """Return the measurable target rows each user actually owns for ``fy``.

    An agreed annual performance review is authoritative.  Older installations
    may have monthly targets that pre-date performance agreements; those rows
    are retained as a per-user compatibility fallback, but the global
    TargetArea catalogue is never used by itself to invent dashboard rows.

    The team service calls this once for its complete roster, so the review,
    priority, and legacy-target lookups remain bounded rather than becoming an
    N+1 query per supervised employee.
    """

    users = [user for user in users if getattr(user, "staff_profile_id", None)]
    result = {str(user.id): [] for user in users}
    if not users:
        return result

    from django.db.models import Prefetch

    from apps.hr.models import (
        PerformancePriority,
        PerformanceReview,
        ReviewStage,
        ReviewType,
    )

    users_by_staff = {str(user.staff_profile_id): user for user in users}
    priority_qs = PerformancePriority.objects.order_by("sequence", "created_at")
    reviews = (
        PerformanceReview.objects.filter(
            staff_id__in=list(users_by_staff),
            fy=fy,
            review_type=ReviewType.ANNUAL_PRIORITIES,
        )
        .exclude(
            stage__in=(
                ReviewStage.NOT_STARTED,
                ReviewStage.PRIORITIES_DRAFT,
                ReviewStage.PRIORITIES_MANAGER_REVIEW,
            )
        )
        .prefetch_related(Prefetch("priorities", queryset=priority_qs))
        .order_by("staff_id", "-updated_at")
    )

    # Only the most recently updated agreed review for a staff/FY can drive a
    # dashboard.  Historic duplicate reviews remain auditable but cannot add
    # duplicate target rows.
    review_by_staff = {}
    for review in reviews:
        review_by_staff.setdefault(str(review.staff_id), review)
    agreed_user_ids = {
        str(users_by_staff[staff_id].id)
        for staff_id in review_by_staff
        if staff_id in users_by_staff
    }

    canonical = {area.key: area for area in active_target_areas()}
    for staff_id, review in review_by_staff.items():
        user = users_by_staff.get(staff_id)
        if user is None:
            continue
        seen_keys = set()
        rows = []
        for priority in review.priorities.all():
            area_key = PERFORMANCE_METRIC_TO_AREA.get(priority.metric_key or "")
            annual_target = priority.target_number or 0
            if (
                not area_key
                or area_key not in canonical
                or area_key in seen_keys
                or annual_target <= 0
            ):
                continue
            seen_keys.add(area_key)
            rows.append(
                PriorityTargetArea(
                    key=area_key,
                    label=priority.outcome_statement,
                    weight=priority.weight,
                    sort_order=priority.sequence,
                    annual_target=annual_target,
                    priority_id=str(priority.id),
                )
            )
        result[str(user.id)] = rows

    # Compatibility for data created before agreements became the source of
    # truth: use only areas with an explicit target for that user/FY.  This is
    # still user-scoped data, never the five-row global catalogue.
    fallback_user_ids = [
        user_id
        for user_id, rows in result.items()
        if not rows and user_id not in agreed_user_ids
    ]
    if fallback_user_ids:
        legacy_rows = (
            MonthlyPersonalTarget.objects.filter(
                user_id__in=fallback_user_ids,
                fy=fy,
                target__gt=0,
            )
            .select_related("area")
            .order_by("user_id", "area__sort_order", "month_of_fy")
        )
        seen_legacy = set()
        for target in legacy_rows:
            marker = (str(target.user_id), target.area.key)
            if marker in seen_legacy:
                continue
            seen_legacy.add(marker)
            result[str(target.user_id)].append(
                PriorityTargetArea(
                    key=target.area.key,
                    label=target.area.label,
                    weight=target.area.weight,
                    sort_order=target.area.sort_order,
                    source="legacy_monthly_target",
                )
            )
    return result


def priority_target_areas(user, fy: str) -> list[PriorityTargetArea]:
    return priority_target_areas_for_users([user], fy).get(str(user.id), [])


NEXT_ACTIONS = {
    "school_visits": ("Open Planning", "/planning"),
    "cluster_meetings": ("Open Planning", "/planning"),
    "cluster_trainings": ("Open Planning", "/planning"),
    "ssa_completed": ("Open My Plan", "/my-plan"),
    "mscs": ("Submit MSCS", "?mscs=new"),
}


def _user_ids(user) -> list[str]:
    ids = [user.id]
    sp = getattr(user, "staff_profile_id", None)
    if sp:
        ids.append(sp)
    return ids


def weighted_period_pct(
    areas,
    targets: dict,
    achieved: dict,
    month_list,
    none_if_unassigned: bool = False,
) -> tuple[int | None, int, int]:
    """THE canonical weighted-percent formula for personal and team target
    achievement (mandate: weighted Overall Progress across TargetArea.weight).

    Sums each area's target/achieved over `month_list`, then averages the
    per-area achievement % weighted by `TargetArea.weight` (areas with no
    target assigned are excluded from the weighted average, not zeroed out).

    `targets`/`achieved` are {area.key: [12 monthly values]} series — the same
    shape MyTargetQueryService.monthly_targets/monthly_achievements and
    PLTeamTargetsService.team_series produce, for one user or a team rollup.

    Used by My Targets (personal), Team Targets (per-member and team-wide
    rollup) — this is the single place the math lives; nothing else should
    reimplement it. Returns (weighted_pct, total_achieved, total_target).
    """
    wsum = psum = 0
    tot_a = tot_t = 0
    for a in areas:
        t = sum(targets[a.key][m - 1] for m in month_list)
        ach = sum(achieved[a.key][m - 1] for m in month_list)
        tot_a += ach
        tot_t += t
        if t > 0:
            wsum += a.weight
            psum += (ach / t * 100) * a.weight
    if not wsum:
        return (None if none_if_unassigned else 0), tot_a, tot_t
    return round(psum / wsum), tot_a, tot_t


def agreed_target_areas(users, fy: str) -> list:
    """The union of the target areas these people have actually agreed, deduped.

    The team-wide companion to :func:`priority_target_areas_for_users`, which
    answers per user. Every leadership surface that pools several people's
    numbers needs this same union, and until CONFLICT-001 was decided the
    Country Director's surfaces did not use it — they fell back to
    ``active_target_areas()``, the whole catalogue, and so counted a CCEO's
    work against targets nobody had assigned. For a team with no signed
    agreements that produced 200% on the CD dashboard while the same team's
    Programme Lead honestly showed "Not Assigned".

    An empty list is the correct answer for a team with no agreements, and the
    callers rely on it: :func:`weighted_period_pct` sees no area carrying a
    target, so it reports unassigned rather than inventing a denominator.

    Order follows the roster then each person's own priority sequence, so the
    first-listed area is stable between renders.
    """
    by_user = priority_target_areas_for_users(users, fy)
    seen: set[str] = set()
    areas: list = []
    for user in users:
        for area in by_user.get(str(user.id), []):
            if area.key in seen:
                continue
            seen.add(area.key)
            areas.append(area)
    return areas


def team_weighted_pct(user_ids, per_user_series, month_list, areas_for) -> tuple:
    """THE canonical way to roll several people's target performance into one %.

    Each person's own weighted percentage is computed first, then those are
    averaged. Someone with no target in the period contributes nothing to the
    average — ``none_if_unassigned`` marks them, and they are skipped.

    The alternative, summing everyone's targets and everyone's achievements
    and dividing once, is what CONFLICT-001 turned out to be. It lets a person
    who has no target this month still contribute their achievement to
    somebody else's denominator: one CCEO with target 1 and achievement 1,
    another with target 0 and achievement 1, pooled as 2 ÷ 1 = 200%. Both
    people did exactly what was asked of them and leadership read double.

    So this is the one implementation. ``areas_for(user_id)`` supplies each
    person's own measurable areas, because Team Targets narrows them per member
    when a category filter is applied and the Country Director does not.
    Returns ``(weighted_pct, total_achieved, total_target)`` — the same triple
    ``weighted_period_pct`` returns, so callers are interchangeable.
    """
    pcts: list[int] = []
    total_achieved = total_target = 0
    for user_id in user_ids:
        series = per_user_series.get(user_id)
        if series is None:
            continue
        targets, achieved = series
        pct, achieved_total, target_total = weighted_period_pct(
            areas_for(user_id),
            targets,
            achieved,
            month_list,
            none_if_unassigned=True,
        )
        total_achieved += achieved_total
        total_target += target_total
        if pct is not None:
            pcts.append(pct)
    return (
        (round(sum(pcts) / len(pcts)) if pcts else 0),
        total_achieved,
        total_target,
    )


def per_user_monthly_series(users, fy: str, areas=None) -> dict:
    """Per-person building block underneath pooled_monthly_series: rebuilds
    each user's achievement ledger and fetches their monthly_targets/
    monthly_achievements EXACTLY ONCE, keyed by user_id.

    Callers that need MULTIPLE overlapping subsets of the same people's
    numbers in one page load (CD/PL/RVP analytics: a country total, then a
    per-PL team total, then a per-CCEO row — all drawing from the same
    roster) should fetch this ONCE for the full roster and pass it to
    pool_series() for each subset, rather than calling pooled_monthly_series()
    once per subset — that would re-run rebuild() + the query pair for the
    same person as many times as they appear across subsets.

    Returns {user_id: ({area.key: [12 monthly targets]}, {area.key: [12
    monthly achieved]})}.
    """
    if areas is None:
        areas = active_target_areas()
    users = list(users)
    # One rebuild for the whole roster rather than one per head: the sources
    # every rebuild reads are the same four tables.
    TargetAchievementService.rebuild_many(users, fy)

    # Three reads for the roster, not three per person. `series_areas` is
    # deliberately the full active set rather than the caller's `areas`: the
    # per-user calls this replaced took no `areas` argument, so they computed
    # over everything active and the caller projected onto its own list below.
    # Narrowing here would change which areas fall back to an annual target.
    series_areas = active_target_areas()
    area_keys = [a.key for a in series_areas]
    explicit = MyTargetQueryService._explicit_targets(users, fy, area_keys)
    profiles = MyTargetQueryService._target_profiles(users, fy)
    ledger = MyTargetQueryService._validated_ledger(users, fy, area_keys)

    out = {}
    for u in users:
        t = MyTargetQueryService._targets_from(
            series_areas,
            explicit.get(u.id, {}),
            profiles.get(getattr(u, "staff_profile_id", None)),
        )
        a = MyTargetQueryService._achievements_from(series_areas, ledger.get(u.id, ()))
        out[u.id] = (
            {area.key: list(t.get(area.key, [0] * 12)) for area in areas},
            {area.key: list(a.get(area.key, [0] * 12)) for area in areas},
        )
    return out


def pool_series(user_ids, per_user: dict, areas) -> tuple[dict, dict]:
    """Pure-Python, zero-query: sums a SUBSET of user_ids' series (from a
    per_user_monthly_series() result) into pooled {area.key: [12]}
    targets/achieved dicts. user_ids not present in `per_user` are silently
    skipped (e.g. a person with no series data at all)."""
    t_out = {a.key: [0] * 12 for a in areas}
    a_out = {a.key: [0] * 12 for a in areas}
    for uid in user_ids:
        series = per_user.get(uid)
        if series is None:
            continue
        t, a = series
        for area in areas:
            for i in range(12):
                t_out[area.key][i] += t.get(area.key, [0] * 12)[i]
                a_out[area.key][i] += a.get(area.key, [0] * 12)[i]
    return t_out, a_out


def pooled_monthly_series(users, fy: str, areas=None) -> tuple[dict, dict]:
    """THE canonical multi-person pooling step: sums MyTargetQueryService's
    per-user monthly_targets/monthly_achievements series across `users`,
    rebuilding each user's achievement ledger first.

    This is the ONLY place multiple people's target/achieved series are
    combined before being handed to weighted_period_pct() — Team Targets
    (a PL's supervised CCEOs) and CD/RVP Analytics (a PL's team, or every
    CCEO in the country) both call this rather than hand-rolling their own
    per-user loop + sum, so "pool N people's targets" has exactly one
    implementation platform-wide. Do not reimplement annual-target
    proration, monthly-target resolution, or ledger aggregation anywhere
    else — those live in MyTargetQueryService.monthly_targets/
    monthly_achievements, called here per user (via per_user_monthly_series).

    Returns ({area.key: [12 summed monthly targets]}, {area.key: [12 summed
    monthly achieved]}) — pass straight into weighted_period_pct(areas,
    targets, achieved, month_list) for the pooled weighted percentage.

    NOTE: if you need SEVERAL overlapping subsets of the same roster (e.g.
    CD Analytics: country total + per-PL + per-CCEO), call
    per_user_monthly_series() once yourself and use pool_series() per
    subset instead of calling this repeatedly — see its docstring.
    """
    if areas is None:
        areas = active_target_areas()
    per_user = per_user_monthly_series(users, fy, areas=areas)
    return pool_series([u.id for u in users], per_user, areas)


class _RebuildSources:
    """Every source row `rebuild` reads, fetched once for a whole roster.

    `rebuild` runs per person on ordinary page loads, and a leadership page
    rebuilds everyone in scope: the Country Director's dashboard rebuilds 48
    CCEOs, which meant 48 activity sweeps, 48 SSA sweeps, 48 story reads and 48
    ledger reads — ~290 round trips to read four tables. Grouped in Python here
    they are four queries, and each person's rebuild then sees exactly the rows
    its own filters would have returned.

    Deliberately holds model instances, not values: the ledger rows are mutated
    and bulk-updated by the caller, and the source rows are read attribute-wise
    by logic that must not change shape just because the fetch did.
    """

    __slots__ = ("activities", "ssa", "mscs", "ledger")

    def __init__(self, activities, ssa, mscs, ledger):
        self.activities = activities  # responsible_staff_id -> [Activity]
        self.ssa = ssa  # collected_by_user_id -> [SsaRecord]
        self.mscs = mscs  # user_id -> [MostSignificantChangeStory]
        self.ledger = ledger  # user_id -> {(source_type, source_id): row}

    @classmethod
    def for_users(cls, users, fy: str) -> "_RebuildSources":
        # Activity and ledger periods use calendar dates; SSA is timestamped.
        # Query each with the matching canonical FY boundary type so Django
        # never silently coerces a date into a naïve midnight datetime.
        fy_start, fy_end = get_fy_date_range(fy)
        user_ids = [u.id for u in users]
        source_ids: list[str] = []
        for u in users:
            source_ids.extend(_user_ids(u))

        activity_types = [
            t
            for stype, types in AREA_SOURCES.values()
            if stype == "activity" and types
            for t in types
        ]
        activities: dict = {}
        for a in (
            Activity.objects.filter(
                responsible_staff_id__in=source_ids,
                fy=fy,
                activity_type__in=activity_types,
                deleted_at__isnull=True,
            )
            .exclude(planned_date__isnull=True)
            .exclude(delivery_type="partner")
        ):
            activities.setdefault(a.responsible_staff_id, []).append(a)

        ssa: dict = {}
        for r in SsaRecord.objects.filter(
            collected_by_user_id__in=source_ids,
            deleted_at__isnull=True,
            date_of_ssa__gte=fy_start,
            date_of_ssa__lt=fy_end,
        ):
            ssa.setdefault(r.collected_by_user_id, []).append(r)

        mscs: dict = {}
        for s in MostSignificantChangeStory.objects.filter(user_id__in=user_ids):
            mscs.setdefault(s.user_id, []).append(s)

        # The whole ledger, every FY — see the note on `existing` in _rebuild
        # for why the read is deliberately not scoped to `fy`.
        ledger: dict = {}
        for row in TargetAchievementLedger.objects.filter(user_id__in=user_ids):
            ledger.setdefault(row.user_id, {})[(row.source_type, row.source_id)] = row

        return cls(activities, ssa, mscs, ledger)


class TargetAchievementService:
    """Rebuild the ledger for one user + FY from real workflow records.
    Idempotent: each source gets exactly one row whose validation_status is
    recomputed every rebuild (so IA returns reverse credits automatically)."""

    @staticmethod
    def rebuild(user, fy: str) -> None:
        TargetAchievementService._rebuild(
            user, fy, _RebuildSources.for_users([user], fy)
        )

    @staticmethod
    def rebuild_many(users, fy: str) -> None:
        """Rebuild a whole roster, reading each source table once.

        Equivalent to calling `rebuild` for each user — the per-person logic is
        the same code — but without re-querying the same four tables per head.
        Users are de-duplicated because the pre-read ledger snapshot is taken
        before any writes, so rebuilding the same person twice from one
        snapshot would work from a stale view of their own rows.
        """
        seen_ids, roster = set(), []
        for u in users:
            if u.id not in seen_ids:
                seen_ids.add(u.id)
                roster.append(u)
        if not roster:
            return
        sources = _RebuildSources.for_users(roster, fy)
        for u in roster:
            TargetAchievementService._rebuild(u, fy, sources)

    @staticmethod
    def _rebuild(user, fy: str, sources: "_RebuildSources") -> None:
        areas = {a.key: a for a in active_target_areas()}
        ids = _user_ids(user)
        seen: set[tuple[str, str]] = set()

        # Collected in memory, then flushed in bulk. This was a
        # get_or_create PER SOURCE ROW, and rebuild() runs on ordinary page
        # loads for every user in scope — 1,016 of the 1,761 queries on the
        # Country Director dashboard came from here alone. Same semantics,
        # same idempotency; four queries instead of N.
        pending: dict[tuple[str, str], dict] = {}

        def upsert(area_key, source_type, source_id, when: date, status: str):
            seen.add((source_type, str(source_id)))
            month = Cal.month_of_fy_for(when, fy)
            if month is None or area_key not in areas:
                return
            pending[(source_type, str(source_id))] = {
                "area": areas[area_key],
                "activity_date": when,
                "credited_month": month,
                "credited_quarter": Cal.quarter_of_month(month),
                "validation_status": status,
            }

        # ── Activity-based areas (visits, meetings, trainings) ──────────────
        for area_key, (stype, types) in AREA_SOURCES.items():
            if stype != "activity":
                continue
            # Partner-delivered work is Partner Contribution, never personal
            # target credit (policy: no silent partner→CCEO credit) — enforced
            # by the `delivery_type` exclusion in _RebuildSources.for_users,
            # which is what the pre-read below is filtered by.
            type_set = set(types)
            acts = [
                a
                for sid in ids
                for a in sources.activities.get(sid, ())
                if a.activity_type in type_set
            ]
            for a in acts:
                if a.status in RETURNED_STATUSES:
                    status = "reversed"
                elif a.status in COMPLETED_STATUSES:
                    # Validated (credited) = IA-verified + Activity SF ID
                    # present. Merely executed/awaiting-IA work stays
                    # provisional — visible, never counted — until IA
                    # verification, per §8. IA return above reverses.
                    status = (
                        "validated"
                        if (
                            a.status in IA_VERIFIED_STATUSES
                            and (a.salesforce_activity_id or "").strip()
                        )
                        else "provisional"
                    )
                else:
                    continue  # scheduled/planned work is not an achievement
                upsert(area_key, "activity", a.id, a.planned_date, status)

        # ── SSA Completed: IA-confirmed SSA records, credited by assessment
        #    date (a late upload/verification credits the assessment month) ──
        ssa = [rec for sid in ids for rec in sources.ssa.get(sid, ())]
        for rec in ssa:
            d = (
                rec.date_of_ssa.date()
                if hasattr(rec.date_of_ssa, "date")
                else rec.date_of_ssa
            )
            status = (
                "validated" if rec.verification_status == "confirmed" else "provisional"
            )
            upsert("ssa_completed", "ssa_record", rec.id, d, status)

        # ── MSCS: only APPROVED stories count, credited by story date ───────
        for story in sources.mscs.get(user.id, ()):
            if story.status == "approved":
                status = "validated"
            elif story.status in ("submitted", "returned", "draft"):
                status = "provisional"
            else:  # rejected / archived
                status = "reversed"
            upsert("mscs", "mscs", story.id, story.story_date, status)

        # ── Flush: one read of the existing ledger, one bulk insert, one
        #    bulk update, one reversal sweep. ─────────────────────────────
        now = timezone.now()
        # Read the user's whole ledger, not just this FY's slice. The unique
        # constraint is deliberately FY-agnostic — one source credits once,
        # ever — so a source that moved across the FY boundary (an activity
        # whose date is corrected from September to October) already has a row
        # under the other year. Looking only within `fy` missed it, tried to
        # insert a second one, and `ignore_conflicts` below swallowed the
        # rejection: the new FY silently gained no credit and the old FY was
        # never reversed, leaving both years wrong with nothing logged.
        existing = sources.ledger.get(user.id, {})
        to_create, to_update = [], []
        for key, want in pending.items():
            row = existing.get(key)
            if row is None:
                to_create.append(
                    TargetAchievementLedger(
                        user_id=user.id,
                        area=want["area"],
                        source_type=key[0],
                        source_id=key[1],
                        fy=fy,
                        activity_date=want["activity_date"],
                        credited_month=want["credited_month"],
                        credited_quarter=want["credited_quarter"],
                        validation_status=want["validation_status"],
                        validated_at=(
                            now if want["validation_status"] == "validated" else None
                        ),
                    )
                )
            elif (
                row.validation_status != want["validation_status"]
                or row.activity_date != want["activity_date"]
                or row.fy != fy
            ):
                row.fy = fy
                row.activity_date = want["activity_date"]
                row.credited_month = want["credited_month"]
                row.credited_quarter = want["credited_quarter"]
                row.validation_status = want["validation_status"]
                if want["validation_status"] == "validated" and not row.validated_at:
                    row.validated_at = now
                to_update.append(row)
        if to_create:
            TargetAchievementLedger.objects.bulk_create(
                to_create, ignore_conflicts=True
            )
        if to_update:
            TargetAchievementLedger.objects.bulk_update(
                to_update,
                [
                    "fy",
                    "activity_date",
                    "credited_month",
                    "credited_quarter",
                    "validation_status",
                    "validated_at",
                    "updated_at",
                ],
            )

        # A ledger row whose source no longer exists (or dropped out of the
        # workflow) loses its credit — a rebuild never leaves orphaned
        # achievement behind.
        # Scoped to rows credited to the FY being rebuilt. `existing` now spans
        # every year, and this rebuild only knows which sources belong to `fy`
        # — sweeping the rest would reverse another year's credit.
        stale_ids = [
            r.id
            for key, r in existing.items()
            if r.fy == fy and key not in seen and r.validation_status != "reversed"
        ]
        if stale_ids:
            TargetAchievementLedger.objects.filter(id__in=stale_ids).update(
                validation_status="reversed", updated_at=now
            )


class MyTargetQueryService:
    """Everything the My Targets page renders, scoped to request.user only."""

    # The reads below are separated from the arithmetic so a roster can fetch
    # once and still compute each person's series through the identical code —
    # `_targets_from` / `_achievements_from` are the single implementation, and
    # the per-user entry points are thin wrappers that fetch a roster of one.
    # Duplicating the arithmetic for a batch path is how the batch and the
    # single quietly drift apart.
    @staticmethod
    def _explicit_targets(users, fy: str, area_keys) -> dict:
        out: dict = {}
        for row in MonthlyPersonalTarget.objects.filter(
            user_id__in=[u.id for u in users],
            fy=fy,
            area__key__in=area_keys,
        ).select_related("area"):
            out.setdefault(row.user_id, {}).setdefault(row.area.key, {})[
                row.month_of_fy
            ] = row.target
        return out

    @staticmethod
    def _target_profiles(users, fy: str) -> dict:
        staff_ids = [
            sp for sp in (getattr(u, "staff_profile_id", None) for u in users) if sp
        ]
        return {
            tp.staff_id: tp
            for tp in StaffTargetProfile.objects.filter(staff_id__in=staff_ids, fy=fy)
        }

    @staticmethod
    def _validated_ledger(users, fy: str, area_keys) -> dict:
        out: dict = {}
        for r in (
            TargetAchievementLedger.objects.filter(
                user_id__in=[u.id for u in users],
                fy=fy,
                validation_status="validated",
                area__key__in=area_keys,
            )
            .select_related("area")
            .order_by()
        ):
            out.setdefault(r.user_id, []).append(r)
        return out

    @staticmethod
    def _targets_from(areas, explicit, tp) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for area in areas:
            if area.key in explicit:
                out[area.key] = [explicit[area.key].get(m, 0) for m in range(1, 13)]
                continue
            annual = getattr(area, "annual_target", None)
            if annual is None:
                annual = ANNUAL_FALLBACK[area.key](tp) if tp else 0
            base, rem = divmod(annual, 12)
            out[area.key] = [base + (1 if m <= rem else 0) for m in range(1, 13)]
        return out

    @staticmethod
    def _achievements_from(areas, rows) -> dict[str, list[int]]:
        out = {a.key: [0] * 12 for a in areas}
        for r in rows:
            if 1 <= r.credited_month <= 12:
                out.setdefault(r.area.key, [0] * 12)[r.credited_month - 1] += r.quantity
        return out

    @staticmethod
    def monthly_targets(user, fy: str, areas=None) -> dict[str, list[int]]:
        """{area_key: [12 monthly targets]} — explicit rows win; otherwise the
        priority's annual target (or legacy annual profile) is split so the 12
        months sum to the annual value."""
        areas = list(areas) if areas is not None else active_target_areas()
        explicit = MyTargetQueryService._explicit_targets(
            [user], fy, [area.key for area in areas]
        ).get(user.id, {})
        profiles = MyTargetQueryService._target_profiles([user], fy)
        tp = profiles.get(getattr(user, "staff_profile_id", None))
        return MyTargetQueryService._targets_from(areas, explicit, tp)

    @staticmethod
    def monthly_achievements(user, fy: str, areas=None) -> dict[str, list[int]]:
        areas = list(areas) if areas is not None else active_target_areas()
        rows = MyTargetQueryService._validated_ledger(
            [user], fy, [a.key for a in areas]
        ).get(user.id, ())
        return MyTargetQueryService._achievements_from(areas, rows)

    # ── Status math ──────────────────────────────────────────────────────────
    @staticmethod
    def status_for(
        achieved: int, target: int, expected_pace: int, started: bool
    ) -> tuple[str, str]:
        if target == 0:
            return ("Not Assigned", "neutral")
        if not started:
            return ("Not Started", "neutral")
        pct = round(achieved / target * 100)
        if pct > 100:
            return ("Exceeded", "success")
        if pct == 100:
            return ("Complete", "success")
        gap = expected_pace - pct
        if gap <= ON_TRACK_BAND:
            return ("On Track", "success")
        if gap <= AT_RISK_BAND:
            return ("At Risk", "warning")
        return ("Off Track", "danger")

    # ── The full page payload ────────────────────────────────────────────────
    @staticmethod
    def get_page(user, fy: str | None = None, month_of_fy: int | None = None) -> dict:
        now = Cal.current()
        fy = fy or now["fy"]
        is_current_fy = fy == now["fy"]
        current_month = now["month_of_fy"] if is_current_fy else 12
        month_of_fy = month_of_fy or (now["month_of_fy"] if is_current_fy else 1)
        today = now["today"]

        TargetAchievementService.rebuild(user, fy)
        areas = priority_target_areas(user, fy)
        targets = MyTargetQueryService.monthly_targets(user, fy, areas=areas)
        achieved = MyTargetQueryService.monthly_achievements(user, fy, areas=areas)

        def span_sum(series, months):
            return sum(series[m - 1] for m in months)

        def weighted_pct(month_list) -> tuple[int, int, int]:
            """(weighted %, total achieved, total target) across assigned areas.
            Delegates to the canonical weighted_period_pct — the same formula
            Team Targets uses for its per-member and team-wide rollups."""
            return weighted_period_pct(areas, targets, achieved, month_list)

        # ── Period cards: Current Month → Q1..Q4 → FY Cumulative ───────────
        def period_card(kind, label, sublabel, months, start, end, emphasize=False):
            pct, ach, tgt = weighted_pct(months)
            started = today >= start
            pace = (
                Cal.expected_pace_pct(start, end, today, user)
                if is_current_fy
                else (100 if started else 0)
            )
            status, tone = (
                ("Not Assigned", "neutral") if started else ("Not Started", "neutral")
            )
            # Status uses the weighted pct against expected pace:
            if tgt:
                if not started:
                    status, tone = "Not Started", "neutral"
                elif pct > 100:
                    status, tone = "Exceeded", "success"
                elif pct == 100:
                    status, tone = "Complete", "success"
                else:
                    gap = pace - pct
                    if gap <= ON_TRACK_BAND:
                        status, tone = "On Track", "success"
                    elif gap <= AT_RISK_BAND:
                        status, tone = "At Risk", "warning"
                    else:
                        status, tone = "Off Track", "danger"
            return {
                "kind": kind,
                "label": label,
                "sublabel": sublabel,
                "pct": pct,
                "ring": min(pct, 100),
                "achieved": ach,
                "target": tgt,
                "status": status,
                "tone": tone,
                "pace": pace,
                "current": emphasize,
            }

        m_start, m_end = Cal.month_range(fy, month_of_fy)
        cards = [
            period_card(
                "month",
                Cal.month_label(fy, month_of_fy).split()[0]
                + f" {Cal.month_label(fy, month_of_fy).split()[1]}",
                "Monthly",
                [month_of_fy],
                m_start,
                m_end,
                emphasize=True,
            )
        ]
        current_quarter = Cal.quarter_of_month(month_of_fy)
        for q in QUARTERS:
            qs, qe = Cal.quarter_range(fy, q)
            cards.append(
                period_card(
                    "quarter",
                    q,
                    Cal.quarter_label(fy, q),
                    Cal.months_of_quarter(q),
                    qs,
                    qe,
                    emphasize=(q == current_quarter and is_current_fy),
                )
            )
        fy_s, fy_e = Cal.fy_range(fy)
        cards.append(
            period_card(
                "fy",
                f"FY {int(fy) - 1}/{str(fy)[-2:]}",
                "Full Year",
                list(range(1, 13)),
                fy_s,
                fy_e,
            )
        )

        # ── Target-area cards + matrix rows ─────────────────────────────────
        pace_month = (
            Cal.expected_pace_pct(m_start, m_end, today, user) if is_current_fy else 100
        )
        area_cards, matrix_rows = [], []
        assigned_statuses = []
        for a in areas:
            t_m = targets[a.key][month_of_fy - 1]
            a_m = achieved[a.key][month_of_fy - 1]
            status, tone = MyTargetQueryService.status_for(
                a_m, t_m, pace_month, today >= m_start
            )
            if t_m > 0:
                assigned_statuses.append((a, status, tone))
            spark = []
            run = 0
            for m in range(1, current_month + 1 if is_current_fy else 13):
                run += achieved[a.key][m - 1]
                spark.append(run)
            pts = ""
            if len(spark) > 1:
                hi = max(spark) or 1
                step = 60 / (len(spark) - 1)
                pts = " ".join(
                    f"{round(i * step, 1)},{round(18 - (v / hi) * 16, 1)}"
                    for i, v in enumerate(spark)
                )
            area_cards.append(
                {
                    "key": a.key,
                    "label": a.label,
                    "weight": a.weight,
                    "target": t_m,
                    "achieved": a_m,
                    "pct": round(a_m / t_m * 100) if t_m else None,
                    "status": status,
                    "tone": tone,
                    "spark_points": pts,
                }
            )
            cells = [
                {"t": t_m, "a": a_m, "pct": round(a_m / t_m * 100) if t_m else None}
            ]
            for q in QUARTERS:
                months = Cal.months_of_quarter(q)
                tq = span_sum(targets[a.key], months)
                aq = span_sum(achieved[a.key], months)
                cells.append(
                    {"t": tq, "a": aq, "pct": round(aq / tq * 100) if tq else None}
                )
            tf = sum(targets[a.key])
            af = sum(achieved[a.key])
            cells.append(
                {"t": tf, "a": af, "pct": round(af / tf * 100) if tf else None}
            )
            matrix_rows.append({"label": a.label, "key": a.key, "cells": cells})

        overall_cells = (
            [{"pct": cards[0]["pct"]}]
            + [{"pct": c["pct"]} for c in cards[1:5]]
            + [{"pct": cards[5]["pct"]}]
        )

        # ── Cumulative trend: weighted actual vs expected target pace ───────
        fy_target_total = {a.key: sum(targets[a.key]) for a in areas}
        actual_line, expected_line = [], []
        for m in range(1, 13):
            wsum = psum = esum = 0
            for a in areas:
                tf = fy_target_total[a.key]
                if tf > 0:
                    wsum += a.weight
                    psum += (
                        span_sum(achieved[a.key], range(1, m + 1)) / tf * 100
                    ) * a.weight
                    esum += (
                        span_sum(targets[a.key], range(1, m + 1)) / tf * 100
                    ) * a.weight
            actual = round(psum / wsum) if wsum else 0
            expected = round(esum / wsum) if wsum else 0
            expected_line.append(expected)
            actual_line.append(
                actual if (not is_current_fy or m <= current_month) else None
            )

        # ── Distribution + focus ─────────────────────────────────────────────
        dist = {
            "On Track": 0,
            "At Risk": 0,
            "Off Track": 0,
            "Complete / Exceeded": 0,
            "Not Started": 0,
        }
        for _a, status, _tone in assigned_statuses:
            if status in ("Complete", "Exceeded"):
                dist["Complete / Exceeded"] += 1
            elif status in dist:
                dist[status] += 1
            elif status == "Not Started":
                dist["Not Started"] += 1
        distribution = [{"label": k, "count": v} for k, v in dist.items() if v]

        focus = []
        for card in sorted(
            [c for c in area_cards if c["target"]],
            key=lambda c: (c["pct"] or 0) - pace_month,
        )[:3]:
            if card["status"] in ("Complete", "Exceeded", "On Track"):
                continue
            reason = MyTargetQueryService._gap_reason(
                user, card["key"], fy, month_of_fy
            )
            label, url = NEXT_ACTIONS[card["key"]]
            focus.append(
                {
                    "area": card["label"],
                    "pct": card["pct"] or 0,
                    "achieved": card["achieved"],
                    "target": card["target"],
                    "status": card["status"],
                    "tone": card["tone"],
                    "reason": reason,
                    "action_label": label,
                    "action_url": url,
                }
            )

        strategic_milestones = []
        strategic_priorities = []
        project_priorities = []
        if getattr(user, "staff_profile_id", None):
            from apps.hr.milestone_allocations import (
                personal_milestone_targets,
                strategic_priority_overview,
            )

            strategic_milestones = personal_milestone_targets(
                staff=user.staff_profile,
                fy=fy,
                month_of_fy=month_of_fy,
            )
            strategic_priorities = strategic_priority_overview(
                fy=fy,
                staff_ids=[user.staff_profile_id],
            )
            from apps.projects.staff_priorities import staff_project_priorities

            project_priorities = staff_project_priorities(user=user, fy=fy)

        from apps.hr.priority_portfolio import priority_portfolio

        priority_groups = priority_portfolio(
            user=user, fy=fy, strategic_milestones=strategic_milestones
        )

        from apps.core.metrics import PresentationKpi

        area_kpi_items = []
        for area in area_cards:
            helper = area["status"]
            if area["pct"] is not None:
                helper = f"{area['pct']}% · {helper}"
            value = f"{area['achieved']:,} / {area['target']:,}"
            area_kpi_items.append(
                PresentationKpi(
                    label=area["label"],
                    value=value,
                    display_value=value,
                    helper=helper,
                    tone=area["tone"],
                    icon="target",
                    hx_get=(
                        f"/my-targets/area-drawer?area={area['key']}"
                        f"&fy={fy}&month={month_of_fy}"
                    ),
                )
            )

        return {
            "fy": fy,
            "month_of_fy": month_of_fy,
            "month_label": Cal.month_label(fy, month_of_fy),
            "current_quarter": current_quarter,
            "is_current_fy": is_current_fy,
            "period_cards": cards,
            "area_cards": area_cards,
            "area_kpi_items": area_kpi_items,
            "matrix_rows": matrix_rows,
            "overall_cells": overall_cells,
            "matrix_heads": [
                {
                    "label": Cal.month_label(fy, month_of_fy).split()[0],
                    "sub": "Monthly",
                },
                *[{"label": q, "sub": Cal.quarter_label(fy, q)} for q in QUARTERS],
                {"label": f"FY {int(fy)-1}/{str(fy)[-2:]}", "sub": "Full Year"},
            ],
            "trend": {
                "labels": MONTH_LABELS,
                "actual": actual_line,
                "expected": expected_line,
                "current_index": current_month - 1 if is_current_fy else 11,
                "current_label": MONTH_LABELS[
                    current_month - 1 if is_current_fy else 11
                ],
                # Numeric series for the inline chart config (None → null).
                # Only quote-free JSON is attribute-safe inside x-data="…".
                "actual_json": json.dumps(actual_line),
                "expected_json": json.dumps(expected_line),
            },
            "distribution": distribution,
            "assigned_count": len(assigned_statuses),
            "focus": focus,
            "month_options": [
                {"value": m, "label": Cal.month_label(fy, m)} for m in range(1, 13)
            ],
            "last_refreshed": timezone.now(),
            "strategic_milestones": strategic_milestones,
            "strategic_priorities": strategic_priorities,
            "project_priorities": project_priorities,
            "priority_groups": priority_groups,
        }

    # ── Gap reasons + drawer detail (traceability) ───────────────────────────
    @staticmethod
    def _pipeline(user, area_key: str, fy: str, month_of_fy: int) -> dict:
        ids = _user_ids(user)
        m_start, m_end = Cal.month_range(fy, month_of_fy)
        ssa_start, ssa_end = get_month_date_range(fy, month_of_fy)
        stype, types = AREA_SOURCES[area_key]
        out = {
            "validated": [],
            "pending_sf": [],
            "ia_pending": [],
            "returned": [],
            "scheduled": [],
            "provisional": [],
        }
        if stype == "activity":
            acts = (
                Activity.objects.filter(
                    responsible_staff_id__in=ids,
                    fy=fy,
                    activity_type__in=types,
                    planned_date__gte=m_start,
                    planned_date__lt=m_end,
                    deleted_at__isnull=True,
                )
                .exclude(delivery_type="partner")
                .select_related("school", "cluster")
            )
            for a in acts:
                row = {
                    "name": (
                        a.school.name
                        if a.school_id
                        else (a.cluster.name if a.cluster_id else "—")
                    ),
                    "type": a.activity_type.replace("_", " ").title(),
                    "date": a.planned_date,
                    "status": a.status.replace("_", " ").title(),
                }
                if a.status in RETURNED_STATUSES:
                    row["why"] = "Returned — fix and resubmit"
                    out["returned"].append(row)
                elif a.status in COMPLETED_STATUSES:
                    if (a.salesforce_activity_id or "").strip():
                        if a.status == "awaiting_ia_verification":
                            row["why"] = "Awaiting IA verification"
                            out["ia_pending"].append(row)
                        else:
                            out["validated"].append(row)
                    else:
                        row["why"] = "Activity SF ID missing — not credited"
                        out["pending_sf"].append(row)
                else:
                    row["why"] = "Scheduled — not yet executed"
                    out["scheduled"].append(row)
        elif stype == "ssa_record":
            recs = SsaRecord.objects.filter(
                collected_by_user_id__in=ids,
                deleted_at__isnull=True,
                date_of_ssa__gte=ssa_start,
                date_of_ssa__lt=ssa_end,
            ).select_related("school")
            for r in recs:
                row = {
                    "name": r.school.name if r.school_id else "—",
                    "type": "SSA",
                    "date": r.date_of_ssa,
                    "status": r.verification_status.title(),
                }
                if r.verification_status == "confirmed":
                    out["validated"].append(row)
                else:
                    row["why"] = "Awaiting IA verification"
                    out["ia_pending"].append(row)
        else:  # mscs
            for s in MostSignificantChangeStory.objects.filter(
                user_id=user.id, story_date__gte=m_start, story_date__lt=m_end
            ):
                row = {
                    "name": s.title,
                    "type": "MSCS",
                    "date": s.story_date,
                    "status": s.get_status_display(),
                }
                if s.status == "approved":
                    out["validated"].append(row)
                elif s.status == "returned":
                    row["why"] = s.return_reason or "Returned for correction"
                    out["returned"].append(row)
                elif s.status in ("draft", "submitted"):
                    row["why"] = "Awaiting review approval"
                    out["provisional"].append(row)
        return out

    @staticmethod
    def _gap_reason(user, area_key: str, fy: str, month_of_fy: int) -> str:
        p = MyTargetQueryService._pipeline(user, area_key, fy, month_of_fy)
        if p["pending_sf"]:
            return f"{len(p['pending_sf'])} completed item(s) missing Activity SF IDs — not yet credited"
        if p["ia_pending"]:
            return f"{len(p['ia_pending'])} item(s) awaiting IA verification"
        if p["returned"]:
            return f"{len(p['returned'])} returned item(s) need correction"
        if p["provisional"]:
            return f"{len(p['provisional'])} item(s) awaiting review"
        if p["scheduled"]:
            return f"{len(p['scheduled'])} scheduled item(s) not yet executed"
        return "No activity planned yet this month"

    @staticmethod
    def area_drawer(user, area_key: str, fy: str, month_of_fy: int) -> dict:
        areas = priority_target_areas(user, fy)
        area = next((item for item in areas if item.key == area_key), None)
        if not area:
            return {"ok": False}
        targets = MyTargetQueryService.monthly_targets(user, fy, areas=areas)
        achieved = MyTargetQueryService.monthly_achievements(user, fy, areas=areas)
        t = targets[area_key][month_of_fy - 1]
        a = achieved[area_key][month_of_fy - 1]
        m_start, m_end = Cal.month_range(fy, month_of_fy)
        today = date.today()
        wd_left = (
            Cal.working_days(max(m_start, today), m_end, user) if today < m_end else 0
        )
        remaining = max(0, t - a)
        weekly_pace = (
            round(remaining / max(1, wd_left / 5), 1) if wd_left else remaining
        )
        return {
            "ok": True,
            "area": area.label,
            "key": area_key,
            "month_label": Cal.month_label(fy, month_of_fy),
            "target": t,
            "achieved": a,
            "pct": round(a / t * 100) if t else None,
            "remaining": remaining,
            "working_days_left": wd_left,
            "weekly_pace": weekly_pace,
            "pipeline": MyTargetQueryService._pipeline(user, area_key, fy, month_of_fy),
        }

    @staticmethod
    def export_rows(user, fy: str) -> list[list]:
        areas = priority_target_areas(user, fy)
        targets = MyTargetQueryService.monthly_targets(user, fy, areas=areas)
        achieved = MyTargetQueryService.monthly_achievements(user, fy, areas=areas)
        rows = [["Performance Priority", "Period", "Target", "Achieved", "%"]]
        for a in areas:
            for m in range(1, 13):
                t, ach = targets[a.key][m - 1], achieved[a.key][m - 1]
                rows.append(
                    [
                        a.label,
                        Cal.month_label(fy, m),
                        t,
                        ach,
                        round(ach / t * 100) if t else "",
                    ]
                )
            for q in QUARTERS:
                months = Cal.months_of_quarter(q)
                t = sum(targets[a.key][m - 1] for m in months)
                ach = sum(achieved[a.key][m - 1] for m in months)
                rows.append([a.label, q, t, ach, round(ach / t * 100) if t else ""])
            t, ach = sum(targets[a.key]), sum(achieved[a.key])
            rows.append(
                [a.label, "FY Cumulative", t, ach, round(ach / t * 100) if t else ""]
            )
        return rows
