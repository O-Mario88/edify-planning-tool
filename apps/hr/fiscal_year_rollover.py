"""Idempotent October 1 fiscal-year rollover.

The rollover opens new containers; it never resets old rows in place.  That
is what makes an FY start at zero while keeping the prior year's performance
and school-progress evidence available through the existing FY selectors.
"""

from __future__ import annotations

from datetime import date

from django.db import models, transaction
from django.utils import timezone

from apps.core.fy import get_operational_fy


def _priority_deadline(fy: str) -> date:
    return date(int(fy) - 1, 10, 31)


def _notify_priority_setting(*, fy: str, users) -> int:
    from apps.notifications.services import WorkflowNotificationService

    created = WorkflowNotificationService.trigger(
        event_type="fiscal_year_priority_setting",
        category="hr",
        priority="high",
        title=f"Set your FY{fy} priorities",
        body=(
            "The new fiscal year has started. Agree every applicable non-student "
            "activity target—including visits, SSA, training and MSCS—with your "
            "manager. Prior-year results remain available as history."
        ),
        context_type="PerformanceCycle",
        context_id=fy,
        recipients=list(users),
    )
    return len(created)


def rollover_fiscal_year(
    *,
    fy: str | None = None,
    as_of: date | None = None,
    initiated_by: str = "system",
    dry_run: bool = False,
) -> dict:
    """Ensure one complete rollover for ``fy`` and return its reconciliation.

    Safe to call from a scheduler, deployment command, or the first web
    request after October 1.  The unique marker plus row lock serializes
    concurrent callers; a committed rerun is a read-only no-op.
    """

    as_of = as_of or timezone.localdate()
    fy = fy or get_operational_fy(as_of)
    if not (fy.isdigit() and len(fy) == 4):
        raise ValueError("Fiscal year must be a four-digit ending year.")
    if get_operational_fy(as_of) != fy:
        raise ValueError(
            f"{as_of.isoformat()} belongs to FY{get_operational_fy(as_of)}, not FY{fy}."
        )

    from apps.accounts.models import StaffProfile
    from apps.activities.models import Activity
    from apps.hr.models import (
        FiscalYearRollover,
        PerformanceCycle,
        PerformanceReview,
        PerformanceSnapshot,
        StrategicPriority,
        StrategicPriorityCycle,
    )
    from apps.hr.performance_engine import build_draft_agreement, take_snapshot
    from apps.schools.models import School
    from apps.ssa.models import SsaRecord
    from apps.targets.models import TargetAchievementLedger

    previous_fy = str(int(fy) - 1)
    now = timezone.now()
    users_to_notify = []
    completed_now = False

    with transaction.atomic():
        marker, _ = FiscalYearRollover.objects.get_or_create(
            fy=fy,
            defaults={
                "previous_fy": previous_fy,
                "initiated_by": initiated_by,
                "started_at": now,
            },
        )
        marker = FiscalYearRollover.objects.select_for_update().get(pk=marker.pk)
        if marker.completed_at:
            return {
                **marker.summary,
                "fy": fy,
                "previousFy": previous_fy,
                "alreadyCompleted": True,
                "dryRun": dry_run,
            }

        previous_snapshots = 0
        previous_cycle = PerformanceCycle.objects.filter(fy=previous_fy).first()
        if previous_cycle:
            snapshotted_review_ids = set(
                PerformanceSnapshot.objects.filter(
                    review__fy=previous_fy, window="year_end"
                ).values_list("review_id", flat=True)
            )
            reviews_to_snapshot = list(
                PerformanceReview.objects.filter(
                    fy=previous_fy, review_type="annual_priorities"
                )
                .exclude(id__in=snapshotted_review_ids)
                .select_related("staff__user")
            )
            for review in reviews_to_snapshot:
                take_snapshot(review, "year_end", known_missing=True)
                previous_snapshots += 1
            previous_cycle.active_window = "none"
            previous_cycle.status = "closed"
            previous_cycle.save(update_fields=["active_window", "status", "updated_at"])

        StrategicPriorityCycle.objects.filter(financial_year=previous_fy).exclude(
            status__in=("closed", "archived")
        ).update(status="closed", updated_at=now)

        strategic_cycle, _ = StrategicPriorityCycle.objects.get_or_create(
            financial_year=fy,
            defaults={
                "title": f"FY{fy} Strategic Priorities",
                "scope_type": "regional",
                "status": "draft",
                "created_by": initiated_by,
                "updated_by": initiated_by,
            },
        )
        # Priorities authored through the user-facing cascade before this
        # cycle existed are still user-set FY priorities. Attach them rather
        # than replacing or duplicating them.
        StrategicPriority.objects.filter(fy=fy, cycle__isnull=True).update(
            cycle=strategic_cycle
        )

        performance_cycle, _ = PerformanceCycle.objects.get_or_create(
            fy=fy,
            defaults={
                "strategic_priority_cycle": strategic_cycle,
                "active_window": "priority_setting",
                "window_opened_at": now,
                "window_deadline": _priority_deadline(fy),
                "status": "open",
            },
        )
        changed_fields = []
        if performance_cycle.strategic_priority_cycle_id != strategic_cycle.id:
            performance_cycle.strategic_priority_cycle = strategic_cycle
            changed_fields.append("strategic_priority_cycle")
        if performance_cycle.status == "closed":
            performance_cycle.status = "open"
            changed_fields.append("status")
        if performance_cycle.active_window == "none":
            performance_cycle.active_window = "priority_setting"
            performance_cycle.window_opened_at = now
            performance_cycle.window_deadline = _priority_deadline(fy)
            changed_fields.extend(
                ["active_window", "window_opened_at", "window_deadline"]
            )
        if changed_fields:
            performance_cycle.save(update_fields=[*changed_fields, "updated_at"])

        # ``School.current_fy_ssa_status`` is a denormalized projection.  The
        # source SsaRecord rows are already FY-scoped, but without refreshing
        # this field on October 1 a school assessed last year still reads
        # "done" throughout the app in the new year.  Preserve any genuinely
        # preloaded new-FY records and reset only the stale projection.
        confirmed_school_ids = set(
            SsaRecord.objects.filter(
                fy=fy,
                verification_status="confirmed",
                deleted_at__isnull=True,
            ).values_list("school_id", flat=True)
        )
        pending_school_ids = set(
            SsaRecord.objects.filter(
                fy=fy,
                verification_status="pending",
                deleted_at__isnull=True,
            )
            .exclude(school_id__in=confirmed_school_ids)
            .values_list("school_id", flat=True)
        )
        stale_ssa = School.objects.filter(
            current_fy_ssa_status__in=("done", "partner_assigned")
        ).exclude(id__in=confirmed_school_ids | pending_school_ids)
        stale_school_ids = list(stale_ssa.values_list("id", flat=True))
        schools_reset = stale_ssa.update(
            current_fy_ssa_status="not_done", updated_at=now
        )
        if pending_school_ids:
            School.objects.filter(id__in=pending_school_ids).update(
                current_fy_ssa_status="partner_assigned", updated_at=now
            )
        if confirmed_school_ids:
            School.objects.filter(id__in=confirmed_school_ids).update(
                current_fy_ssa_status="done", updated_at=now
            )

        # Refresh only SSA-derived readiness states.  A school already in a
        # scheduled/finance/evidence workflow keeps that workflow state.
        from apps.core.enums import PlanningReadiness
        from django.db.models import Case, CharField, Value, When

        ssa_readiness_states = (
            PlanningReadiness.REQUIRES_CLUSTER,
            PlanningReadiness.READY_FOR_BASELINE_SSA,
            PlanningReadiness.READY_FOR_SUPPORT_PLANNING,
        )
        affected_school_ids = (
            set(stale_school_ids) | confirmed_school_ids | pending_school_ids
        )
        if affected_school_ids:
            School.objects.filter(
                id__in=affected_school_ids,
                planning_readiness__in=ssa_readiness_states,
            ).update(
                planning_readiness=Case(
                    When(
                        models.Q(cluster_id__isnull=True) | models.Q(cluster_id=""),
                        then=Value(PlanningReadiness.REQUIRES_CLUSTER),
                    ),
                    When(
                        id__in=confirmed_school_ids,
                        then=Value(PlanningReadiness.READY_FOR_SUPPORT_PLANNING),
                    ),
                    default=Value(PlanningReadiness.READY_FOR_BASELINE_SSA),
                    output_field=CharField(),
                ),
                updated_at=now,
            )

        active_staff = list(
            StaffProfile.objects.filter(
                deleted_at__isnull=True,
                onboarding_state="active",
                user__is_active=True,
                user__deleted_at__isnull=True,
            )
            .select_related("user")
            .order_by("id")
        )
        existing_review_staff_ids = set(
            PerformanceReview.objects.filter(
                staff_id__in=[staff.id for staff in active_staff],
                fy=fy,
                review_type="annual_priorities",
            ).values_list("staff_id", flat=True)
        )
        drafts_created = 0
        for staff in active_staff:
            if staff.id in existing_review_staff_ids:
                continue
            build_draft_agreement(
                staff,
                performance_cycle,
                principal=None,
                include_role_templates=False,
                due_date=_priority_deadline(fy),
            )
            drafts_created += 1

        summary = {
            "fy": fy,
            "previousFy": previous_fy,
            "previousActivities": Activity.objects.filter(fy=previous_fy).count(),
            "previousValidatedCredits": TargetAchievementLedger.objects.filter(
                fy=previous_fy, validation_status="validated"
            ).count(),
            "previousYearSnapshotsCreated": previous_snapshots,
            "activeStaff": len(active_staff),
            "draftAgreementsCreated": drafts_created,
            "currentVerifiedActivities": Activity.objects.filter(
                fy=fy,
                deleted_at__isnull=True,
                status__in=("ia_verified", "accountant_confirmed", "closed"),
            ).count(),
            "currentValidatedCredits": TargetAchievementLedger.objects.filter(
                fy=fy, validation_status="validated"
            ).count(),
            "schoolsResetToSsaRequired": schools_reset,
            "prioritySource": "user_set_strategic_priorities_and_agreements",
        }
        marker.previous_fy = previous_fy
        marker.initiated_by = initiated_by
        marker.performance_cycle = performance_cycle
        marker.strategic_priority_cycle = strategic_cycle
        marker.summary = summary
        marker.completed_at = now
        marker.save()
        completed_now = True
        users_to_notify = [staff.user for staff in active_staff]

        if dry_run:
            transaction.set_rollback(True)

    notified = 0
    if completed_now and not dry_run:
        notified = _notify_priority_setting(fy=fy, users=users_to_notify)
        from apps.audit.services import log as audit_log

        audit_log(
            action="hr.fiscal_year_rolled_over",
            subject_kind="FiscalYearRollover",
            subject_id=fy,
            actor_id=initiated_by,
            actor_role=None,
            payload={**summary, "notifications": notified},
        )

    return {
        **summary,
        "notifications": notified,
        "alreadyCompleted": False,
        "dryRun": dry_run,
    }


def ensure_current_fiscal_year(*, initiated_by: str = "system") -> dict:
    return rollover_fiscal_year(initiated_by=initiated_by)
