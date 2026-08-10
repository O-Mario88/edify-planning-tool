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
    "cluster-meeting-cost-key",
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
        if wants("cluster-meeting-cost-key"):
            self._fix_cluster_meeting_cost_key(apply)
        if wants("duplicate-partner-payments"):
            self._scan_duplicate_partner_payments()
        if wants("paid-without-partner-payment"):
            self._scan_paid_without_payment()
        if wants("reopened-still-credited"):
            self._scan_reopened_credited()
        if wants("lineless-scheduled-activities"):
            self._scan_lineless()

    # ── fixes ────────────────────────────────────────────────────────────────

    @staticmethod
    def _audit(name, subject_kind, subject_id, before, after):
        from apps.audit.services import log as audit_log

        audit_log(
            action=f"data_repair.{name}",
            subject_kind=subject_kind,
            subject_id=str(subject_id),
            payload={"before": before, "after": after},
        )

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
            if apply and after != before:
                self._audit(
                    "core_counters",
                    "CorePlan",
                    plan.id,
                    list(before),
                    list(after),
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
                before = {
                    "current_fy_ssa_status": school.current_fy_ssa_status,
                    "planning_readiness": school.planning_readiness,
                }
                _recompute_readiness(school)
                school.refresh_from_db()
                self._audit(
                    "ssa_status",
                    "School",
                    school.school_id,
                    before,
                    {
                        "current_fy_ssa_status": school.current_fy_ssa_status,
                        "planning_readiness": school.planning_readiness,
                    },
                )
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
            if count:
                self._audit(
                    "catchup_sync",
                    "CatchUpPlanSet",
                    "live",
                    {"candidate_count": count},
                    {"synchronized": True},
                )
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
                before = {"status": activity.status, "quarter": activity.quarter}
                activity.status = "planned"
                if not activity.quarter:
                    activity.quarter = get_quarter_for_date(activity.planned_date)
                activity.save(update_fields=["status", "quarter", "updated_at"])
                self._audit(
                    "debrief_draft",
                    "Activity",
                    activity.id,
                    before,
                    {"status": activity.status, "quarter": activity.quarter},
                )
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
            and not (plan.interventions or {}).get("maintenance")
        ]
        needs_ssa: list[str] = []
        no_school: list[str] = []
        written = 0
        for plan in missing:
            school = School.objects.filter(school_id=plan.school_id).first()
            if not school:
                # An orphan plan is a different defect with its own repair.
                no_school.append(plan.school_id)
                continue
            rec = CoreInterventionRecommendationService.recommend(school)
            rows = rec.get("rows") or []
            maintenance = bool(rec.get("maintenance"))
            # A school with no verified SSA yields available=False and no rows.
            # Persisting that wrote {"recommended": []} stamped with captured_at
            # and algorithm_version — an EMPTY recommendation wearing the shape
            # of a real one, for a school nobody has assessed. The recommendation
            # decides which four interventions a package targets and which two
            # go to a Partner, so leave it unwritten and report it instead.
            if not rec.get("available") or (not rows and not maintenance):
                needs_ssa.append(plan.school_id)
                continue
            written += 1
            if not apply:
                continue
            plan.interventions = {
                "recommended": rows,
                "maintenance": maintenance,
                "source_ssa_record_id": plan.baseline_ssa_record_id or None,
                "captured_at": timezone.now().isoformat(),
                "algorithm_version": 1,
                "backfilled": True,
            }
            plan.save(update_fields=["interventions", "updated_at"])
            self._audit(
                "core_recommendation",
                "CorePlan",
                plan.id,
                {"recommended": []},
                {
                    "recommended_count": len(rows),
                    "maintenance": maintenance,
                    "algorithm_version": 1,
                    "backfilled": True,
                },
            )
        self.stdout.write(
            f"core-recommendations: {len(missing)} active plan(s) missing persisted "
            f"set; {written} derivable; {len(needs_ssa)} MANUAL REVIEW (no verified "
            f"SSA); {len(no_school)} MANUAL REVIEW (no School row)"
        )

    def _fix_cluster_meeting_cost_key(self, apply):
        """Rename the one legacy cluster-meeting rate key when provenance and
        amount prove it is the canonical Participant snacks rate.

        A different amount/catalogue is ambiguous and remains reported for
        manual review; the command never guesses or rewrites money.
        """
        from apps.activities.models import ActivityScheduleCostLine
        from apps.budget.models import CostSetting

        canonical_key = "cluster_meeting_participant_meal_cost_per_head"
        canonical = CostSetting.objects.filter(key=canonical_key).first()
        candidates = ActivityScheduleCostLine.objects.filter(
            activity__activity_type__in=[
                "cluster_meeting",
                "cluster_meeting_ssa_review",
            ]
        ).exclude(cost_setting_key=canonical_key)

        eligible_ids = []
        ambiguous = 0
        for line in candidates:
            matches_provenance = (
                canonical is not None
                and line.catalogue_id == canonical.catalogue_id
                and line.catalogue_version
                == getattr(canonical.catalogue, "version", None)
                and line.unit_cost == canonical.unit_cost
                and line.amount == canonical.unit_cost * line.quantity
            )
            if matches_provenance:
                eligible_ids.append(line.id)
            else:
                ambiguous += 1

        if apply and canonical:
            for line in ActivityScheduleCostLine.objects.filter(id__in=eligible_ids):
                before = {
                    "cost_setting_key": line.cost_setting_key,
                    "label": line.label,
                }
                line.cost_setting_key = canonical_key
                line.label = canonical.label
                line.line_item_type = "participant_meals"
                line.save(
                    update_fields=[
                        "cost_setting_key",
                        "label",
                        "line_item_type",
                        "updated_at",
                    ]
                )
                self._audit(
                    "cluster_meeting_cost_key",
                    "ActivityScheduleCostLine",
                    line.id,
                    before,
                    {
                        "cost_setting_key": line.cost_setting_key,
                        "label": line.label,
                    },
                )

        self.stdout.write(
            "cluster-meeting-cost-key: "
            f"{len(eligible_ids)} deterministic rename(s); "
            f"{ambiguous} manual-review row(s)"
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
