"""Sessionisation, daily rollup and the aggregate report.

The measurement method here is versioned with docs/STAFF_TIME_STANDARD.md —
changing a constant below is an amendment to the standard, not a tuning
knob.

Method: a person-day's events are sorted; consecutive events closer than
``IDLE_CAP_SECONDS`` belong to one active session and contribute their real
gap; a longer gap starts a new session and contributes nothing (the person
was teaching, driving, or living — not administering). Each session earns
``FINAL_ACTION_CREDIT_SECONDS`` for its last interaction, which server-side
timestamps cannot otherwise see (this also makes a lone check-in count as
~30 seconds rather than zero). The result is an estimate by construction,
used as a trend-and-ceiling instrument.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.rbac import EdifyRole

from .models import RAW_EVENT_RETENTION_DAYS, InteractionDay, InteractionEvent

IDLE_CAP_SECONDS = 180
FINAL_ACTION_CREDIT_SECONDS = 30

# The Staff Time Standard's 95%-of-days ceiling, in seconds.
STANDARD_CEILING_SECONDS = 15 * 60

# Roles the 15-minute ceiling covers (STAFF_TIME_STANDARD.md §2). Other
# roles are still measured — the report shows them for context — but the
# SLO share is computed over these.
FIELD_ROLES = (
    EdifyRole.CCEO.value,
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EdifyRole.PROJECT_COORDINATOR.value,
    EdifyRole.PARTNER_FIELD_OFFICER.value,
)

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

# Route-pattern classification for the §3a split. Versioned with the
# standard: PLANNING surfaces are preparation the roadmap exists to take
# off staff (plan construction, costing, fund preparation, distribution);
# EXECUTION surfaces are the six sanctioned interactions — schedule,
# assign, debrief, evidence, and the SF/NetSuite proof pastes. Everything
# unmatched is OTHER (dashboards, targets, messages, settings). Prefixes
# match the resolver's route pattern, which never contains concrete values.
# Amended 2026-08-15 after the alignment audit classified all 483 live
# route patterns: dead prefixes removed (they matched nothing), and the
# routes §3a sanctions — the Today workbench, the partner field surface,
# SSA collection, the To-Do queue, PL review — attributed to execution.
PLANNING_ROUTE_PREFIXES = (
    "planning",
    "work-plan",
    "fund-requests",
    "budget",
    "target-distribution",
    "clusters/schedule",
    "core-schools/schedule",
    "core-schools/assign-partner",
)
EXECUTION_ROUTE_PREFIXES = (
    "my-plan",
    "activities",
    "evidence",
    "debrief",
    "actions",
    "today",
    "todos",
    "partner",
    "ssa",
    "pl/review-queue",
    "accounts/activities",  # NetSuite/SF reference + finance proof endpoints
    "accounts/activity-evidence",
)

CATEGORY_PLANNING = "planning"
CATEGORY_EXECUTION = "execution"
CATEGORY_OTHER = "other"


def classify_route(route: str) -> str:
    """Which side of the §3a contract a route pattern sits on."""

    trimmed = (route or "").lstrip("/")
    # Execution wins ties: a route like accounts/activities/... must never
    # be swallowed by a broader planning prefix.
    if trimmed.startswith(EXECUTION_ROUTE_PREFIXES):
        return CATEGORY_EXECUTION
    if trimmed.startswith(PLANNING_ROUTE_PREFIXES):
        return CATEGORY_PLANNING
    return CATEGORY_OTHER


def active_seconds(timestamps: list[datetime]) -> int:
    """Sessionised active time for one person-day's sorted event times."""

    if not timestamps:
        return 0
    ordered = sorted(timestamps)
    total = 0.0
    sessions = 1
    for previous, current in zip(ordered, ordered[1:]):
        gap = (current - previous).total_seconds()
        if gap > IDLE_CAP_SECONDS:
            sessions += 1
        else:
            total += gap
    return int(total + sessions * FINAL_ACTION_CREDIT_SECONDS)


def active_seconds_by_category(events: list[tuple[datetime, str]]) -> dict:
    """Sessionised active time attributed to §3a categories.

    Each intra-session gap is attributed to the PRECEDING event's category —
    the time after a page was opened is time spent working on it. Each
    session's final-action credit goes to its last event's category. The
    category totals sum exactly to active_seconds() for the same events.
    """

    totals = {
        CATEGORY_PLANNING: 0.0,
        CATEGORY_EXECUTION: 0.0,
        CATEGORY_OTHER: 0.0,
    }
    if not events:
        return {key: 0 for key in totals}
    ordered = sorted(events, key=lambda pair: pair[0])
    for (prev_time, prev_route), (cur_time, _route) in zip(ordered, ordered[1:]):
        gap = (cur_time - prev_time).total_seconds()
        if gap > IDLE_CAP_SECONDS:
            # Session ended: credit the closing interaction.
            totals[classify_route(prev_route)] += FINAL_ACTION_CREDIT_SECONDS
        else:
            totals[classify_route(prev_route)] += gap
    totals[classify_route(ordered[-1][1])] += FINAL_ACTION_CREDIT_SECONDS
    return {key: int(value) for key, value in totals.items()}


@transaction.atomic
def rollup_interaction_days(*, day: date | None = None) -> int:
    """Recompute the person-day aggregates for ``day`` (default: yesterday),
    then prune raw events past retention. Idempotent: a rerun rewrites the
    same rows from the same events."""

    target = day or (timezone.localdate() - timedelta(days=1))
    tz = timezone.get_current_timezone()
    start = datetime.combine(target, dt_time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    events = InteractionEvent.objects.filter(
        occurred_at__gte=start, occurred_at__lt=end
    ).values_list("user_id", "role", "occurred_at", "method", "route")
    by_user: dict[str, dict] = {}
    for user_id, role, occurred_at, method, route in events:
        bucket = by_user.setdefault(user_id, {"role": role, "events": [], "writes": 0})
        # The most recent role wins for the day — role switches mid-day are
        # rare and the day is attributed to how it was mostly worked.
        bucket["role"] = role
        bucket["events"].append((occurred_at, route))
        if method in WRITE_METHODS:
            bucket["writes"] += 1
    written = 0
    for user_id, bucket in by_user.items():
        categories = active_seconds_by_category(bucket["events"])
        InteractionDay.objects.update_or_create(
            user_id=user_id,
            day=target,
            defaults={
                "role": bucket["role"],
                # Sum of the category splits, so the §3a attribution always
                # reconciles exactly to the day's total.
                "active_seconds": sum(categories.values()),
                "planning_seconds": categories[CATEGORY_PLANNING],
                "execution_seconds": categories[CATEGORY_EXECUTION],
                "request_count": len(bucket["events"]),
                "write_count": bucket["writes"],
            },
        )
        written += 1
    InteractionEvent.objects.filter(
        occurred_at__lt=timezone.now() - timedelta(days=RAW_EVENT_RETENTION_DAYS)
    ).delete()
    return written


def _percentile(sorted_values: list[int], pct: float) -> int:
    """Nearest-rank percentile — simple, honest, and stable for small N."""

    if not sorted_values:
        return 0
    rank = max(1, math.ceil(pct / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


@dataclass(frozen=True)
class RoleInteractionSummary:
    role: str
    person_days: int
    p50_minutes: float
    p90_minutes: float
    p95_minutes: float
    within_standard_pct: float | None
    planning_share_pct: float | None
    covered_by_standard: bool


def interaction_report(*, window_days: int = 14) -> dict:
    """The Staff Time Standard's aggregate report (§4/§5): role-population
    percentiles and the within-15-minutes share. Deliberately contains no
    user identifiers — the anti-surveillance constraint is enforced here,
    at the only read path, not left to consumers."""

    since = timezone.localdate() - timedelta(days=window_days)
    rows = InteractionDay.objects.filter(day__gte=since).values_list(
        "role", "active_seconds", "planning_seconds"
    )
    by_role: dict[str, dict] = {}
    for role, seconds, planning in rows:
        bucket = by_role.setdefault(
            role or "Unknown", {"seconds": [], "active": 0, "planning": 0}
        )
        bucket["seconds"].append(seconds)
        bucket["active"] += seconds
        bucket["planning"] += planning
    summaries = []
    field_days = 0
    field_within = 0
    field_active = 0
    field_planning = 0
    for role, bucket in sorted(by_role.items()):
        ordered = sorted(bucket["seconds"])
        covered = role in FIELD_ROLES
        within = sum(1 for s in ordered if s <= STANDARD_CEILING_SECONDS)
        if covered:
            field_days += len(ordered)
            field_within += within
            field_active += bucket["active"]
            field_planning += bucket["planning"]
        summaries.append(
            RoleInteractionSummary(
                role=role,
                person_days=len(ordered),
                p50_minutes=round(_percentile(ordered, 50) / 60, 1),
                p90_minutes=round(_percentile(ordered, 90) / 60, 1),
                p95_minutes=round(_percentile(ordered, 95) / 60, 1),
                within_standard_pct=(
                    round(within / len(ordered) * 100, 1) if ordered else None
                ),
                planning_share_pct=(
                    round(bucket["planning"] / bucket["active"] * 100, 1)
                    if bucket["active"]
                    else None
                ),
                covered_by_standard=covered,
            )
        )
    return {
        "windowDays": window_days,
        "ceilingMinutes": STANDARD_CEILING_SECONDS // 60,
        "roles": [summary.__dict__ for summary in summaries],
        "fieldPersonDays": field_days,
        "fieldWithinStandardPct": (
            round(field_within / field_days * 100, 1) if field_days else None
        ),
        # §3a: the share of field active time spent on planning surfaces —
        # the preparation the roadmap exists to take off staff. Target: down.
        "fieldPlanningSharePct": (
            round(field_planning / field_active * 100, 1) if field_active else None
        ),
        "meetsStandard": (
            (field_within / field_days * 100) >= 95.0 if field_days else None
        ),
    }
