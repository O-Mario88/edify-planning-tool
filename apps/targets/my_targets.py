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
    """Return the official active target areas, repairing only missing rows."""
    areas = list(TargetArea.objects.filter(active=True).order_by("sort_order"))
    active_keys = {area.key for area in areas}
    missing = [area for area in OFFICIAL_TARGET_AREAS if area[0] not in active_keys]
    if not missing:
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
    return list(TargetArea.objects.filter(active=True).order_by("sort_order"))


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
    out = {}
    for u in users:
        TargetAchievementService.rebuild(u, fy)
        t = MyTargetQueryService.monthly_targets(u, fy)
        a = MyTargetQueryService.monthly_achievements(u, fy)
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


class TargetAchievementService:
    """Rebuild the ledger for one user + FY from real workflow records.
    Idempotent: each source gets exactly one row whose validation_status is
    recomputed every rebuild (so IA returns reverse credits automatically)."""

    @staticmethod
    def rebuild(user, fy: str) -> None:
        areas = {a.key: a for a in active_target_areas()}
        ids = _user_ids(user)
        # Activity and ledger periods use calendar dates; SSA is timestamped.
        # Query each with the matching canonical FY boundary type so Django
        # never silently coerces a date into a naïve midnight datetime.
        fy_start, fy_end = get_fy_date_range(fy)
        seen: set[tuple[str, str]] = set()

        def upsert(area_key, source_type, source_id, when: date, status: str):
            seen.add((source_type, str(source_id)))
            month = Cal.month_of_fy_for(when, fy)
            if month is None or area_key not in areas:
                return
            row, created = TargetAchievementLedger.objects.get_or_create(
                user_id=user.id,
                area=areas[area_key],
                source_type=source_type,
                source_id=str(source_id),
                defaults={
                    "activity_date": when,
                    "fy": fy,
                    "credited_month": month,
                    "credited_quarter": Cal.quarter_of_month(month),
                    "validation_status": status,
                    "validated_at": timezone.now() if status == "validated" else None,
                },
            )
            if not created and (
                row.validation_status != status or row.activity_date != when
            ):
                row.activity_date = when
                row.credited_month = month
                row.credited_quarter = Cal.quarter_of_month(month)
                row.validation_status = status
                if status == "validated" and not row.validated_at:
                    row.validated_at = timezone.now()
                row.save(
                    update_fields=[
                        "activity_date",
                        "credited_month",
                        "credited_quarter",
                        "validation_status",
                        "validated_at",
                        "updated_at",
                    ]
                )

        # ── Activity-based areas (visits, meetings, trainings) ──────────────
        for area_key, (stype, types) in AREA_SOURCES.items():
            if stype != "activity":
                continue
            # Partner-delivered work is Partner Contribution, never personal
            # target credit (policy: no silent partner→CCEO credit).
            acts = (
                Activity.objects.filter(
                    responsible_staff_id__in=ids,
                    fy=fy,
                    activity_type__in=types,
                    deleted_at__isnull=True,
                )
                .exclude(planned_date__isnull=True)
                .exclude(delivery_type="partner")
            )
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
        ssa = SsaRecord.objects.filter(
            collected_by_user_id__in=ids,
            deleted_at__isnull=True,
            date_of_ssa__gte=fy_start,
            date_of_ssa__lt=fy_end,
        )
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
        for story in MostSignificantChangeStory.objects.filter(user_id=user.id):
            if story.status == "approved":
                status = "validated"
            elif story.status in ("submitted", "returned", "draft"):
                status = "provisional"
            else:  # rejected / archived
                status = "reversed"
            upsert("mscs", "mscs", story.id, story.story_date, status)

        # ── Stale credits: a ledger row whose source record no longer exists
        #    (or dropped out of the workflow) loses its credit — a rebuild can
        #    never leave orphaned achievement behind. ─────────────────────────
        for row in TargetAchievementLedger.objects.filter(
            user_id=user.id, fy=fy
        ).exclude(validation_status="reversed"):
            if (row.source_type, row.source_id) not in seen:
                row.validation_status = "reversed"
                row.save(update_fields=["validation_status", "updated_at"])


class MyTargetQueryService:
    """Everything the My Targets page renders, scoped to request.user only."""

    @staticmethod
    def monthly_targets(user, fy: str) -> dict[str, list[int]]:
        """{area_key: [12 monthly targets]} — explicit rows win; otherwise the
        annual profile is split so the 12 months sum to the annual value."""
        areas = active_target_areas()
        explicit: dict[str, dict[int, int]] = {}
        for row in MonthlyPersonalTarget.objects.filter(user_id=user.id, fy=fy):
            explicit.setdefault(row.area.key, {})[row.month_of_fy] = row.target

        sp_id = getattr(user, "staff_profile_id", None)
        tp = (
            StaffTargetProfile.objects.filter(staff_id=sp_id, fy=fy).first()
            if sp_id
            else None
        )

        out: dict[str, list[int]] = {}
        for area in areas:
            if area.key in explicit:
                out[area.key] = [explicit[area.key].get(m, 0) for m in range(1, 13)]
                continue
            annual = ANNUAL_FALLBACK[area.key](tp) if tp else 0
            base, rem = divmod(annual, 12)
            out[area.key] = [base + (1 if m <= rem else 0) for m in range(1, 13)]
        return out

    @staticmethod
    def monthly_achievements(user, fy: str) -> dict[str, list[int]]:
        out = {a.key: [0] * 12 for a in active_target_areas()}
        rows = TargetAchievementLedger.objects.filter(
            user_id=user.id, fy=fy, validation_status="validated"
        ).select_related("area")
        for r in rows:
            if 1 <= r.credited_month <= 12:
                out.setdefault(r.area.key, [0] * 12)[r.credited_month - 1] += r.quantity
        return out

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
        areas = active_target_areas()
        targets = MyTargetQueryService.monthly_targets(user, fy)
        achieved = MyTargetQueryService.monthly_achievements(user, fy)

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

        return {
            "fy": fy,
            "month_of_fy": month_of_fy,
            "month_label": Cal.month_label(fy, month_of_fy),
            "current_quarter": current_quarter,
            "is_current_fy": is_current_fy,
            "period_cards": cards,
            "area_cards": area_cards,
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
        area = next(
            (item for item in active_target_areas() if item.key == area_key), None
        )
        if not area:
            return {"ok": False}
        targets = MyTargetQueryService.monthly_targets(user, fy)
        achieved = MyTargetQueryService.monthly_achievements(user, fy)
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
        targets = MyTargetQueryService.monthly_targets(user, fy)
        achieved = MyTargetQueryService.monthly_achievements(user, fy)
        rows = [["Target Area", "Period", "Target", "Achieved", "%"]]
        for a in active_target_areas():
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
