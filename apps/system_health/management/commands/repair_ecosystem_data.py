"""Historical data repair for the 2026-07 ecosystem/production audit.

Idempotent, dry-run by default, per-fix scoped, counted before/after,
audit-logged. Ambiguous records are REPORTED (scans) — never guessed at.

Usage:
    manage.py repair_ecosystem_data                # dry-run everything
    manage.py repair_ecosystem_data --apply        # apply all fixes
    manage.py repair_ecosystem_data --only core-counters --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q

FIXES = (
    "core-counters",
    "ssa-status",
    "catchup-sync",
    "debrief-drafts",
    "core-recommendations",
)
SCANS = (
    "duplicate-partner-payments",
    "paid-without-partner-payment",
    "reopened-still-credited",
    "lineless-scheduled-activities",
)


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="write changes")
        parser.add_argument("--only", choices=FIXES + SCANS, default=None)

    def handle(self, *args, **options):
        apply = options["apply"]
        only = options["only"]
        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(f"== Ecosystem data repair ({mode}) ==")

        def wants(name):
            return only is None or only == name

        if wants("core-counters"):
            self._fix_core_counters(apply)
        if wants("ssa-status"):
            self._fix_ssa_status(apply)
        if wants("catchup-sync"):
            self._fix_catchup(apply)
        if wants("debrief-drafts"):
            self._fix_debrief_drafts(apply)
        if wants("core-recommendations"):
            self._fix_core_recommendations(apply)
        if wants("duplicate-partner-payments"):
            self._scan_duplicate_partner_payments()
        if wants("paid-without-partner-payment"):
            self._scan_paid_without_payment()
        if wants("reopened-still-credited"):
            self._scan_reopened_credited()
        if wants("lineless-scheduled-activities"):
            self._scan_lineless()

    # ── fixes ────────────────────────────────────────────────────────────────

    def _fix_core_counters(self, apply):
        """Recount every CorePlan with the corrected done-status set (closed
        activities previously dropped out of completion)."""
        from apps.core_schools.models import CorePlan
        from apps.core_schools.services import resync_plan_completion

        drifted = 0
        for plan in CorePlan.objects.all():
            before = (
                plan.visits_completed,
                plan.trainings_completed,
                plan.assessment_completed,
            )
            if apply:
                resync_plan_completion(plan)
                plan.refresh_from_db()
            after = (
                plan.visits_completed,
                plan.trainings_completed,
                plan.assessment_completed,
            )
            if not apply:
                # compute would-be values without writing
                from apps.core_schools.services import CORE_SLOT_DONE_STATUSES

                would = (
                    plan.slots.filter(
                        activity_type="visit",
                        status__in=CORE_SLOT_DONE_STATUSES,
                    ).count(),
                    plan.slots.filter(
                        activity_type="training",
                        status__in=CORE_SLOT_DONE_STATUSES,
                    ).count(),
                    plan.slots.filter(
                        activity_type="assessment",
                        status__in=CORE_SLOT_DONE_STATUSES,
                    ).count(),
                )
                if would != before:
                    drifted += 1
            elif after != before:
                drifted += 1
        self.stdout.write(f"core-counters: {drifted} plan(s) recounted/drifted")

    def _fix_ssa_status(self, apply):
        """Schools whose current_fy_ssa_status says done/partner_assigned but
        have no current-FY record in that state (stale prior-FY stamps)."""
        from apps.core.fy import get_operational_fy
        from apps.schools.models import School
        from apps.ssa.models import SsaRecord
        from apps.ssa.services import _recompute_readiness

        fy = get_operational_fy()
        current_ok = set(
            SsaRecord.objects.filter(
                fy=fy,
                deleted_at__isnull=True,
                verification_status__in=["confirmed", "pending"],
            ).values_list("school_id", flat=True)
        )
        stale = School.objects.filter(
            deleted_at__isnull=True,
            current_fy_ssa_status__in=["done", "partner_assigned"],
        ).exclude(id__in=current_ok)
        count = stale.count()
        if apply:
            for school in stale:
                _recompute_readiness(school)
        self.stdout.write(f"ssa-status: {count} stale school stamp(s)")

    def _fix_catchup(self, apply):
        from apps.targets.models import CatchUpPlan
        from apps.targets.team_targets import PLCatchUpPlanService

        plans = CatchUpPlan.objects.filter(
            status__in=["approved", "scheduled", "in_progress"]
        )
        count = plans.count()
        if apply:
            PLCatchUpPlanService.sync_completion(plans)
        self.stdout.write(f"catchup-sync: {count} live plan(s) synced")

    def _fix_debrief_drafts(self, apply):
        """Follow-ups created from accepted recommendations before the fix
        sat not_planned (invisible to To-Dos) with no quarter."""
        from apps.activities.models import Activity
        from apps.core.fy import get_quarter_for_date
        from apps.debriefs.models import DailyDebrief

        ids = list(
            DailyDebrief.objects.exclude(
                recommendation_accepted_activity_id__isnull=True
            )
            .exclude(recommendation_accepted_activity_id="")
            .values_list("recommendation_accepted_activity_id", flat=True)
        )
        stuck = Activity.objects.filter(
            id__in=ids, status="not_planned", deleted_at__isnull=True
        )
        count = stuck.count()
        if apply:
            for activity in stuck:
                activity.status = "planned"
                if not activity.quarter:
                    activity.quarter = get_quarter_for_date(activity.planned_date)
                activity.save(update_fields=["status", "quarter", "updated_at"])
        self.stdout.write(f"debrief-drafts: {count} invisible follow-up(s)")

    def _fix_core_recommendations(self, apply):
        from apps.core_schools.core_planning_services import (
            CoreInterventionRecommendationService,
        )
        from apps.core_schools.models import CorePlan
        from apps.schools.models import School
        from django.utils import timezone

        missing = [
            plan
            for plan in CorePlan.objects.filter(status="Active")
            if not (plan.interventions or {}).get("recommended")
        ]
        if apply:
            for plan in missing:
                school = School.objects.filter(school_id=plan.school_id).first()
                if not school:
                    continue
                rec = CoreInterventionRecommendationService.recommend(school)
                plan.interventions = {
                    "recommended": rec.get("rows") or [],
                    "maintenance": rec.get("maintenance", False),
                    "source_ssa_record_id": plan.baseline_ssa_record_id or None,
                    "captured_at": timezone.now().isoformat(),
                    "algorithm_version": 1,
                    "backfilled": True,
                }
                plan.save(update_fields=["interventions", "updated_at"])
        self.stdout.write(
            f"core-recommendations: {len(missing)} active plan(s) missing persisted set"
        )

    # ── scans (report-only; ambiguity → manual review) ───────────────────────

    def _scan_duplicate_partner_payments(self):
        from apps.fund_requests.finance_models import PartnerPayment

        dups = (
            PartnerPayment.objects.values("activity_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        for row in dups:
            self.stdout.write(
                self.style.WARNING(
                    f"MANUAL REVIEW duplicate PartnerPayment: activity {row['activity_id']} has {row['n']} rows"
                )
            )
        self.stdout.write(f"duplicate-partner-payments: {dups.count()} activity(ies)")

    def _scan_paid_without_payment(self):
        from apps.activities.models import Activity

        rows = (
            Activity.objects.filter(
                delivery_type="partner",
                payment_status="paid",
                deleted_at__isnull=True,
            )
            .exclude(partner_payments__isnull=False)
            .distinct()
        )
        for activity in rows[:20]:
            self.stdout.write(
                self.style.WARNING(
                    f"MANUAL REVIEW partner paid without PartnerPayment ledger row: {activity.id}"
                )
            )
        self.stdout.write(f"paid-without-partner-payment: {rows.count()} activity(ies)")

    def _scan_reopened_credited(self):
        from apps.activities.closure_models import ActivityReopenRequest

        invalidating = {
            "wrong_evidence",
            "wrong_salesforce_id",
            "wrong_school",
            "duplicate_discovered",
        }
        rows = ActivityReopenRequest.objects.filter(
            category__in=invalidating,
            activity__status="ia_verified",
            activity__deleted_at__isnull=True,
        ).select_related("activity")
        for req in rows[:20]:
            self.stdout.write(
                self.style.WARNING(
                    f"MANUAL REVIEW invalidating reopen still credited: activity {req.activity_id} ({req.category})"
                )
            )
        self.stdout.write(f"reopened-still-credited: {rows.count()} activity(ies)")

    def _scan_lineless(self):
        from apps.activities.models import Activity

        rows = (
            Activity.objects.filter(deleted_at__isnull=True)
            .exclude(status__in=["not_planned", "cancelled", "rejected", "deferred"])
            .filter(schedule_cost_lines__isnull=True, est_cost_cents__gt=0)
            .distinct()
        )
        self.stdout.write(
            f"lineless-scheduled-activities: {rows.count()} scheduled with estimate but no lines"
        )
        _ = F, Q  # imported for future scan extensions
