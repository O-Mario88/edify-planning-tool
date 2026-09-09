from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .models import (
    MilestoneActivityRule,
    MilestonePeriodTarget,
    MilestoneProgressCredit,
)


logger = logging.getLogger("edify.milestone_progress")

QUALIFYING_STATES = {"ia_verified", "accountant_confirmed", "closed"}

# Measurement types whose achievement is a RATE, and which therefore need a
# denominator to mean anything. Named once because it was written out by hand
# in four places and one of them disagreed: the allocation workspace populated
# the denominator only for "percentage", while this module and
# performance_scores both treat "ratio" as a rate too. Every ratio milestone
# allocated through that page was left without the number its own achievement
# calculation requires, and scored zero for ever (2026-08 audit TGT-01).
RATE_MEASUREMENT_TYPES = frozenset({"percentage", "ratio"})

# Counting bases grouped by the UNIT they produce. Bases inside one family
# share an aggregation and combine correctly (two school bases both count
# distinct schools). Bases across families do not: schools and teachers are
# different things and have no shared total.
SCHOOL_BASES = frozenset(
    {
        "UNIQUE_SCHOOLS_SUPPORTED",
        "UNIQUE_SCHOOLS_TRAINED",
        "PERCENT_OF_ELIGIBLE_SCHOOLS",
    }
)
TEACHER_BASES = frozenset({"UNIQUE_PARTICIPANTS", "TEACHERS_TRAINED"})
LEADER_BASES = frozenset({"SCHOOL_LEADERS_TRAINED"})

# The bases whose figure is a count of DISTINCT ENTITIES rather than a running
# total — exactly the bases `_aggregate_credits` answers with `distinct=True`.
# 2026-08 audit, TGT-03: annual and quarterly achievement was built by adding
# up the stored period rows, which is right for a total and wrong for a
# distinct count. A school supported in October and again in March is one
# unique school, and the figure whose own name says "unique" was reporting
# two. Any figure spanning more than one stored period therefore has to come
# from a single distinct query over that whole span (see `range_actual`). The
# teacher and leader bases sum attendance headcounts and are genuinely
# additive, so they stay as they are.
DISTINCT_ENTITY_BASES = SCHOOL_BASES


def counting_basis_families(bases) -> set[str]:
    """Which unit families a set of counting bases spans."""
    families = set()
    for family, members in (
        ("schools", SCHOOL_BASES),
        ("teachers", TEACHER_BASES),
        ("leaders", LEADER_BASES),
    ):
        if set(bases) & members:
            families.add(family)
    if set(bases) - (SCHOOL_BASES | TEACHER_BASES | LEADER_BASES):
        families.add("credited_value")
    return families


# Record types that legitimately carry no Salesforce Activity ID. Same set the
# `closed_activity_must_have_sf_id` database constraint exempts — stated once
# here so the credit rule and the constraint cannot drift apart.
SALESFORCE_EXEMPT_RECORD_TYPES = {"NONE", "SSA_DATA_GATHERING"}


def _salesforce_reference_satisfied(activity) -> bool:
    """Whether this activity carries the external proof its type requires.

    The personal ledger has always required a Salesforce ID before counting
    work as validated (apps/targets/my_targets.py); the milestone cascade did
    not, so the same verified activity could be counted by one engine and held
    provisional by the other (2026-08 audit, AUD-009). The platform law is the
    database constraint's: every record type except the exempt ones must carry
    the reference.
    """
    if activity.salesforce_record_type_snapshot in SALESFORCE_EXEMPT_RECORD_TYPES:
        return True
    return bool((activity.salesforce_activity_id or "").strip())


def _rule_matches(rule, activity) -> bool:
    if activity.catalogue_item_id != rule.catalogue_item_id:
        return False
    if rule.project_id and str(activity.project_id or "") != str(rule.project_id):
        return False
    if (
        rule.required_executor_type
        and activity.delivery_type != rule.required_executor_type
    ):
        return False
    if (
        rule.required_delivery_method
        and activity.delivery_method_snapshot != rule.required_delivery_method
    ):
        return False
    if rule.school_type:
        from .target_distribution import school_type_family

        if not activity.school or activity.school.school_type not in school_type_family(
            rule.school_type
        ):
            return False
    if rule.school_level and (
        not activity.school
        or getattr(activity.school, "school_level", None) != rule.school_level
    ):
        return False
    if (
        rule.target_intervention
        and activity.focus_intervention != rule.target_intervention
    ):
        return False
    return activity.status in QUALIFYING_STATES


@transaction.atomic
def reverse_activity_progress(
    activity, *, reason: str = "IA returned/invalidated"
) -> int:
    """Reverse the credits of an activity that is no longer verified.

    Called when IA returns a completion. 2026-08-20 audit: credits are
    APPEND-ONLY — the row survives with `reversed_at`/`reversed_reason` so
    the value and its source snapshot remain auditable history. Every
    consumer excludes reversed rows, and a later re-verification un-reverses
    the same row instead of duplicating it.
    """

    from django.utils import timezone as _tz

    credits = list(
        MilestoneProgressCredit.objects.filter(
            activity=activity, reversed_at__isnull=True
        ).select_related("rule")
    )
    if not credits:
        return 0
    milestone_ids = {credit.rule.milestone_id for credit in credits}
    MilestoneProgressCredit.objects.filter(
        id__in=[credit.id for credit in credits]
    ).update(reversed_at=_tz.now(), reversed_reason=reason[:255])
    for milestone_id in milestone_ids:
        refresh_period_targets(milestone_id)
    from .accountability_cache import changed

    changed()
    return len(credits)


@transaction.atomic
def record_activity_progress(activity) -> int:
    """Create at most one milestone credit per rule for this Activity."""

    if not activity.catalogue_item_id or activity.status not in QUALIFYING_STATES:
        return 0
    if not _salesforce_reference_satisfied(activity):
        return 0
    rules = MilestoneActivityRule.objects.filter(
        active=True,
        catalogue_item_id=activity.catalogue_item_id,
        milestone__active=True,
        milestone__requires_definition=False,
    ).select_related("milestone", "catalogue_item")
    created_count = 0
    # A previously reversed credit for this source comes back to life rather
    # than duplicating (append-only history) — but only when its rule STILL
    # matches the re-verified activity.
    revive_ids, revived_milestones = [], []
    for _cr in MilestoneProgressCredit.objects.filter(
        activity=activity, reversed_at__isnull=False
    ).select_related("rule"):
        if _rule_matches(_cr.rule, activity):
            revive_ids.append(_cr.id)
            revived_milestones.append(_cr.rule.milestone_id)
    if revive_ids:
        MilestoneProgressCredit.objects.filter(id__in=revive_ids).update(
            reversed_at=None, reversed_reason=""
        )
        for _mid in set(revived_milestones):
            refresh_period_targets(_mid)
        created_count += len(revive_ids)
        from .accountability_cache import changed

        changed()
    credited_milestones = set(
        MilestoneProgressCredit.objects.filter(
            activity=activity, reversed_at__isnull=True
        ).values_list("rule__milestone_id", flat=True)
    )
    for rule in rules:
        if not _rule_matches(rule, activity):
            continue
        # 2026-08-20 audit: one source earns ONE credit per MILESTONE. Two
        # rules on the same milestone (a project-specific one plus a general
        # one whose null project matches everything) both matched a
        # project-bearing activity and double-counted it.
        if rule.milestone_id in credited_milestones:
            continue
        _credit, created = MilestoneProgressCredit.objects.get_or_create(
            rule=rule,
            activity=activity,
            defaults={
                "credited_value": rule.weight or Decimal("1"),
                "source_snapshot": {
                    "activityId": activity.id,
                    "catalogueItemId": activity.catalogue_item_id,
                    "catalogueVersion": activity.catalogue_version,
                    "intervention": activity.focus_intervention,
                    "projectId": activity.project_id,
                    "executorType": activity.delivery_type,
                    "status": activity.status,
                },
                "credited_at": timezone.now(),
            },
        )
        created_count += int(created)
        credited_milestones.add(rule.milestone_id)
        refresh_period_targets(rule.milestone_id)
    return created_count


def _scoped_credits(milestone_id, *, scope, start, end, employee, project_id, team_id):
    """Credit the accountable recipient, including monitored partner delivery."""
    from apps.activities.models import Activity
    from .contribution_scope import scope_activities

    activities = Activity.objects.filter(deleted_at__isnull=True)
    if scope == "employee" and employee is not None:
        activities = scope_activities(activities, staff=employee)
    elif scope == "team" and team_id:
        activities = scope_activities(activities, staff=team_id, include_team=True)
    elif scope == "project" and project_id:
        activities = activities.filter(project_id=project_id)
    else:
        from .models import PriorityMilestone

        country = PriorityMilestone.objects.values_list(
            "priority__country_id", flat=True
        ).get(id=milestone_id)
        activities = scope_activities(activities, country=country)
    return MilestoneProgressCredit.objects.filter(
        rule__milestone_id=milestone_id,
        rule__active=True,
        reversed_at__isnull=True,
        activity_id__in=activities.values("id"),
        activity__planned_date__gte=start,
        activity__planned_date__lte=end,
    )


def _aggregate_credits(credits, bases):
    """The verified figure these credits produce, in their basis' own unit."""
    if bases & SCHOOL_BASES:
        return credits.exclude(activity__school__isnull=True).aggregate(
            value=Count("activity__school", distinct=True)
        )["value"]
    # Multiple rules can match the same event; credit that event once in a
    # recipient/country rollup, including attendance measures.
    from django.db.models import Max

    field = (
        "activity__teachers_attended"
        if bases & TEACHER_BASES
        else "activity__leaders_attended"
        if bases & LEADER_BASES
        else "credited_value"
    )
    per_activity = (
        credits.order_by().values("activity_id").annotate(event_value=Max(field))
    )
    return per_activity.aggregate(total=Sum("event_value"))["total"]


def counts_distinct_entities(milestone) -> bool:
    """Whether this milestone's figure counts entities, not occurrences."""
    return bool(
        {rule.counting_basis for rule in milestone.activity_rules.all() if rule.active}
        & DISTINCT_ENTITY_BASES
    )


def range_actual(allocation, rows, *, milestone=None) -> Decimal:
    """One allocation's verified figure over the whole span `rows` cover.

    TGT-03: every quarterly and annual roll-up used to add the stored period
    rows together. That is correct for an additive measure and wrong for a
    distinct one, so a distinct measure is re-read here with ONE distinct
    query over the full span instead. The stored rows are left exactly as the
    progress engine wrote them — each is the honest distinct count for its own
    month, which is what the monthly view asks for — and only the roll-up
    changes.

    `milestone` lets a caller hand over an instance whose activity rules are
    already prefetched; it is always the allocation's own milestone.
    """
    rows = list(rows)
    milestone = milestone if milestone is not None else allocation.milestone
    if not rows:
        return Decimal(0)
    credits = _scoped_credits(
        milestone.id,
        scope=allocation.allocated_to_type,
        start=min(row.period_start for row in rows),
        end=max(row.period_end for row in rows),
        employee=allocation.employee,
        project_id=allocation.project_id,
        team_id=allocation.team_id,
    )
    bases = {
        rule.counting_basis for rule in milestone.activity_rules.all() if rule.active
    }
    return Decimal(_aggregate_credits(credits, bases) or 0)


def refresh_period_targets(milestone_id: str) -> None:
    """Recompute every period's verified actual from the surviving credits.

    Each row is computed over its OWN date range, so a stored quarter row is
    already a distinct count across the quarter. Only roll-ups assembled from
    several rows need `range_actual` (TGT-03).
    """
    targets = MilestonePeriodTarget.objects.filter(
        milestone_id=milestone_id
    ).select_related("employee", "allocation", "milestone")
    for target in targets:
        credits = _scoped_credits(
            milestone_id,
            scope=target.scope,
            start=target.period_start,
            end=target.period_end,
            employee=target.employee if target.employee_id else None,
            project_id=target.allocation.project_id if target.allocation_id else None,
            team_id=target.team_id,
        )
        bases = set(credits.values_list("rule__counting_basis", flat=True).distinct())
        families = counting_basis_families(bases)
        if len(families) > 1:
            # Two counting bases from different UNIT families on one milestone
            # (schools and teachers, say) have no common total: the branch
            # order in `_aggregate_credits` would silently keep one and discard
            # the rest, and a target would read as under-delivered for a reason
            # nobody could see. This is a definition error in the rules, not a
            # number to guess at, so say so loudly and name the milestone. The
            # figure still computes from the first family, unchanged, so
            # surfacing it never destabilises an existing number.
            logger.error(
                "milestone %s mixes counting-basis families %s — its verified "
                "actual counts only %s; the rules must agree on one unit",
                milestone_id,
                sorted(families),
                sorted(families)[0],
            )
        target.actual_value = Decimal(_aggregate_credits(credits, bases) or 0)
        if target.milestone.measurement_type in RATE_MEASUREMENT_TYPES:
            if target.allocation_id and target.allocation.denominator:
                # A rate target holds the rate (e.g. 90) as planned_value
                # while credits arrive as raw units (schools reached).
                # Coverage is units/denominator; achievement is coverage
                # against the committed rate — dividing units by a percentage
                # would be dimensional nonsense.
                coverage = target.actual_value / target.allocation.denominator * 100
                if target.milestone.cap_at_100 and coverage > 100:
                    # The cap belongs HERE, on coverage — nobody covers more
                    # than all of their schools, so anything past 100 is a
                    # data problem. It must not be applied to the achievement
                    # ratio below: a CCEO covering 100% of a 90% commitment
                    # has achieved 111%, and that surplus is the entire
                    # point of committing to a rate below the ceiling.
                    coverage = Decimal("100")
                target.achievement_percentage = (
                    (coverage / target.planned_value * 100)
                    if target.planned_value
                    else Decimal("0")
                )
            else:
                # No denominator means the coverage cannot be computed at
                # all. The old fallback divided raw units by the rate, which
                # scored a 45-school CCEO at 50% of a 90% target their
                # 50-school portfolio had fully met. An honest zero plus a
                # loud log beats a confidently wrong figure.
                logger.error(
                    "rate milestone %s allocation %s has no denominator — "
                    "achievement cannot be computed from %s raw units",
                    milestone_id,
                    target.allocation_id,
                    target.actual_value,
                )
                target.achievement_percentage = Decimal("0")
        else:
            target.achievement_percentage = (
                (target.actual_value / target.planned_value * 100)
                if target.planned_value
                else Decimal("0")
            )
        target.actual_source = "MilestoneProgressCredit"
        target.snapshot_at = timezone.now()
        # achievement_percentage is dimension-safe for counts AND rates;
        # comparing raw units to a percentage target is not.
        target.status = (
            "achieved"
            if target.planned_value and target.achievement_percentage >= 100
            else "in_progress"
            if target.actual_value
            else "not_started"
        )
        target.save(
            update_fields=[
                "actual_value",
                "achievement_percentage",
                "actual_source",
                "snapshot_at",
                "status",
                "updated_at",
            ]
        )
