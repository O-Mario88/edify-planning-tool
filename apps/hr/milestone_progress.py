from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    MilestoneActivityRule,
    MilestonePeriodTarget,
    MilestoneProgressCredit,
)


QUALIFYING_STATES = {"ia_verified", "accountant_confirmed", "closed"}


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
def reverse_activity_progress(activity) -> int:
    """Remove the credits of an activity that is no longer verified.

    Called when IA returns a completion. The credit rows are deleted (they are
    derived, dedup'd facts, not history — the audit trail lives on the
    Activity and the verification records) and every affected milestone's
    period actuals are recomputed, so verified figures never keep counting
    rejected work.
    """

    credits = list(
        MilestoneProgressCredit.objects.filter(activity=activity).select_related("rule")
    )
    if not credits:
        return 0
    milestone_ids = {credit.rule.milestone_id for credit in credits}
    MilestoneProgressCredit.objects.filter(
        id__in=[credit.id for credit in credits]
    ).delete()
    for milestone_id in milestone_ids:
        refresh_period_targets(milestone_id)
    return len(credits)


@transaction.atomic
def record_activity_progress(activity) -> int:
    """Create at most one milestone credit per rule for this Activity."""

    if not activity.catalogue_item_id or activity.status not in QUALIFYING_STATES:
        return 0
    rules = MilestoneActivityRule.objects.filter(
        active=True,
        catalogue_item_id=activity.catalogue_item_id,
        milestone__active=True,
        milestone__requires_definition=False,
    ).select_related("milestone", "catalogue_item")
    created_count = 0
    for rule in rules:
        if not _rule_matches(rule, activity):
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
        refresh_period_targets(rule.milestone_id)
    return created_count


def refresh_period_targets(milestone_id: str) -> None:
    targets = MilestonePeriodTarget.objects.filter(
        milestone_id=milestone_id
    ).select_related("employee", "allocation", "milestone")
    for target in targets:
        credits = MilestoneProgressCredit.objects.filter(
            rule__milestone_id=milestone_id,
            activity__planned_date__gte=target.period_start,
            activity__planned_date__lte=target.period_end,
        )
        if target.scope == "employee" and target.employee_id:
            owner_ids = {
                str(target.employee_id),
                str(target.employee.user_id or ""),
            }
            credits = credits.filter(
                Q(activity__responsible_staff_id__in=owner_ids)
                | Q(activity__monitored_by_staff_id__in=owner_ids)
            )
        elif target.scope == "project" and target.allocation.project_id:
            credits = credits.filter(activity__project_id=target.allocation.project_id)
        elif target.scope == "team" and target.team_id:
            from apps.accounts.models import StaffSupervisorAssignment

            member_ids = list(
                StaffSupervisorAssignment.objects.filter(
                    supervisor_id=target.team_id
                ).values_list("supervisee_id", flat=True)
            )
            credits = credits.filter(
                Q(activity__responsible_staff_id__in=member_ids)
                | Q(activity__monitored_by_staff_id__in=member_ids)
            )
        bases = set(credits.values_list("rule__counting_basis", flat=True).distinct())
        if bases & {
            "UNIQUE_SCHOOLS_SUPPORTED",
            "UNIQUE_SCHOOLS_TRAINED",
            "PERCENT_OF_ELIGIBLE_SCHOOLS",
        }:
            actual = credits.exclude(activity__school__isnull=True).aggregate(
                value=Count("activity__school", distinct=True)
            )["value"]
        elif bases & {"UNIQUE_PARTICIPANTS", "TEACHERS_TRAINED"}:
            actual = credits.aggregate(value=Sum("activity__teachers_attended"))[
                "value"
            ]
        elif "SCHOOL_LEADERS_TRAINED" in bases:
            actual = credits.aggregate(value=Sum("activity__leaders_attended"))["value"]
        else:
            actual = credits.aggregate(value=Sum("credited_value"))["value"]
        target.actual_value = Decimal(actual or 0)
        if (
            target.milestone.measurement_type in {"percentage", "ratio"}
            and target.allocation_id
            and target.allocation.denominator
        ):
            # A rate target holds the rate (e.g. 90) as planned_value while
            # credits arrive as raw units (schools reached). Coverage is
            # units/denominator; achievement is coverage against the committed
            # rate — dividing units by a percentage would be dimensional
            # nonsense.
            coverage = target.actual_value / target.allocation.denominator * 100
            target.achievement_percentage = (
                (coverage / target.planned_value * 100)
                if target.planned_value
                else Decimal("0")
            )
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
