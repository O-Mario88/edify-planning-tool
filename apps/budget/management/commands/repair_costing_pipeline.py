"""Repair the planning→costing→budget pipeline's historical data.

Targets the defect classes closed by the 2026-07-30 financial-integrity
audit, for rows written before the fixes:

1. Partner-delivered cost lines mirrored into staff funding channels
   (AdvanceRequests / draft WeeklyFundRequest lines) — the double-funding
   seam; partner work is payable only via PartnerPayment.
2. Country-scope period FundRequests with an underspecified period key (the
   Friday cron's FY-wide "weekly" request whose disbursement would flip every
   advance in the FY).
3. Scheduled, funded-eligible activities with no cost set at all.
4. Staff batch-eligible school visits priced solo at the full day pool
   instead of the pooled 1/N share (only while their week is still in draft).
5. Dangling monthly FundRequestItems whose source cost line was deleted by a
   re-price (draft requests only — submitted ones are reported for manual
   review, never rewritten).

Dry-run by default; pass --apply to write. Locked/approved finance is never
silently rewritten — those rows are counted under "manual review".
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.fund_requests.models import (
    MONEY_MOVED_ADVANCE_STATUSES,
    AdvanceRequest,
    FundRequest,
    FundRequestItem,
    FundRequestStatus,
    WeeklyFundRequestLine,
)


class Command(BaseCommand):
    help = "Repair pipeline data damaged before the 2026-07-30 audit fixes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the repairs (default is a dry run that only reports).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        mode = "APPLY" if apply else "DRY RUN"
        self.stdout.write(f"repair_costing_pipeline — {mode}")
        report = {}

        report["partner_lines"] = self._repair_partner_lines(apply)
        report["rogue_period_requests"] = self._repair_rogue_period_requests(apply)
        report["costless_scheduled"] = self._repair_costless_scheduled(apply)
        report["unpooled_visits"] = self._repair_unpooled_visits(apply)
        report["dangling_items"] = self._repair_dangling_items(apply)

        self.stdout.write("summary:")
        for key, stats in report.items():
            self.stdout.write(f"  {key}: {stats}")
        if not apply:
            self.stdout.write("dry run — re-run with --apply to write repairs.")

    # ── 1. partner lines in staff channels ───────────────────────────────
    def _repair_partner_lines(self, apply: bool) -> dict:
        from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activity
        from apps.fund_requests.weekly_service import sync_weekly_requests_for_activity

        advances = AdvanceRequest.objects.filter(
            activity__delivery_type="partner"
        ).exclude(status__in=MONEY_MOVED_ADVANCE_STATUSES)
        moved = AdvanceRequest.objects.filter(
            activity__delivery_type="partner",
            status__in=MONEY_MOVED_ADVANCE_STATUSES,
        ).count()
        weekly_lines = WeeklyFundRequestLine.objects.filter(
            activity_budget_line__activity__delivery_type="partner"
        )
        locked_weekly = weekly_lines.exclude(
            weekly_fund_request__status="pending_responsible_confirmation"
        ).count()
        affected_activities = set(advances.values_list("activity_id", flat=True)) | set(
            weekly_lines.filter(
                weekly_fund_request__status="pending_responsible_confirmation"
            ).values_list("activity_budget_line__activity_id", flat=True)
        )
        stats = {
            "advances_found": advances.count(),
            "weekly_lines_found": weekly_lines.count(),
            "money_moved_manual_review": moved,
            "locked_weekly_manual_review": locked_weekly,
            "repaired_activities": 0,
        }
        if apply:
            with transaction.atomic():
                advances.delete()
                for activity in Activity.objects.filter(id__in=affected_activities):
                    prior = list(
                        ActivityScheduleCostLine.objects.filter(
                            activity=activity
                        ).values_list(
                            "responsible_user",
                            "fiscal_year",
                            "month",
                            "week_start_date",
                        )
                    )
                    sync_weekly_requests_for_activity(activity, prior_buckets=prior)
                    sync_monthly_drafts_for_activity(activity, prior_buckets=prior)
                    stats["repaired_activities"] += 1
        return stats

    # ── 2. FY-wide / underspecified period requests ──────────────────────
    def _repair_rogue_period_requests(self, apply: bool) -> dict:
        rogues = FundRequest.objects.filter(period="weekly").exclude(
            period_key__contains="-W"
        )
        deletable = rogues.filter(
            status__in=[FundRequestStatus.DRAFT, FundRequestStatus.SUBMITTED]
        )
        manual = rogues.exclude(
            status__in=[FundRequestStatus.DRAFT, FundRequestStatus.SUBMITTED]
        ).count()
        stats = {
            "found": rogues.count(),
            "deletable": deletable.count(),
            "manual_review": manual,
        }
        if apply:
            with transaction.atomic():
                FundRequestItem.objects.filter(fund_request__in=deletable).delete()
                deletable.delete()
        return stats

    # ── 3. scheduled activities with no cost set ─────────────────────────
    def _repair_costless_scheduled(self, apply: bool) -> dict:
        from apps.activities.services import _apply_schedule_cost_snapshot
        from apps.core.exceptions import BadRequest

        costless = (
            Activity.objects.filter(
                deleted_at__isnull=True,
                scheduled_date__isnull=False,
            )
            .exclude(paired_in_school_training__isnull=False)
            .exclude(
                status__in=[
                    "cancelled",
                    "rejected",
                    "deferred",
                    # Historical/settled work predating the costing engine is
                    # reported, not re-priced — money for it never flowed
                    # through this pipeline.
                    "closed",
                    "ia_verified",
                    "accountant_confirmed",
                    "completed",
                ]
            )
            .annotate(n_lines=Count("schedule_cost_lines"))
            .filter(n_lines=0)
        )
        stats = {"found": costless.count(), "repriced": 0, "manual_review": 0}
        if apply:
            for activity in costless:
                try:
                    with transaction.atomic():
                        _apply_schedule_cost_snapshot(activity, {}, principal=None)
                        activity.save(
                            update_fields=[
                                "est_cost_cents",
                                "cost_missing",
                                "updated_at",
                            ]
                        )
                    stats["repriced"] += 1
                except (BadRequest, Exception) as exc:  # noqa: BLE001
                    stats["manual_review"] += 1
                    self.stdout.write(f"  costless {activity.id}: {exc}")
        return stats

    # ── 4. unpooled staff visits (full day pool billed per school) ───────
    def _repair_unpooled_visits(self, apply: bool) -> dict:
        from apps.daily_visit_batches.pricing import DAILY_BATCH_ELIGIBLE_TYPES
        from apps.daily_visit_batches.services import attach_activity_to_batch
        from apps.activities.services import _funding_owner_id
        from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activity
        from apps.fund_requests.weekly_service import sync_weekly_requests_for_activity

        candidates = (
            Activity.objects.filter(
                deleted_at__isnull=True,
                delivery_type="staff",
                daily_visit_batch__isnull=True,
                scheduled_date__isnull=False,
                activity_type__in=DAILY_BATCH_ELIGIBLE_TYPES,
                school__isnull=False,
                status__in=["scheduled", "rescheduled", "planned"],
            )
            .select_related("school__district")
            .order_by("planned_date", "id")
        )
        stats = {"found": candidates.count(), "pooled": 0, "manual_review": 0}
        if apply:
            for activity in candidates:
                try:
                    with transaction.atomic():
                        prior = list(
                            ActivityScheduleCostLine.objects.filter(
                                activity=activity
                            ).values_list(
                                "responsible_user",
                                "fiscal_year",
                                "month",
                                "week_start_date",
                            )
                        )
                        pooled = attach_activity_to_batch(
                            activity,
                            responsible_user_id=_funding_owner_id(activity, None),
                            reason="repair_costing_pipeline",
                        )
                        if pooled:
                            sync_weekly_requests_for_activity(
                                activity, prior_buckets=prior
                            )
                            sync_monthly_drafts_for_activity(
                                activity, prior_buckets=prior
                            )
                            stats["pooled"] += 1
                        else:
                            stats["manual_review"] += 1
                except Exception as exc:  # noqa: BLE001
                    stats["manual_review"] += 1
                    self.stdout.write(f"  unpooled {activity.id}: {exc}")
        return stats

    # ── 5. dangling monthly fund-request items ───────────────────────────
    def _repair_dangling_items(self, apply: bool) -> dict:
        from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activity

        item_line_ids = set(
            FundRequestItem.objects.exclude(activity_schedule_cost_line_id=None)
            .exclude(activity_schedule_cost_line_id="")
            .values_list("activity_schedule_cost_line_id", flat=True)
        )
        live = set(
            ActivityScheduleCostLine.objects.filter(id__in=item_line_ids).values_list(
                "id", flat=True
            )
        )
        dangling_ids = item_line_ids - live
        dangling = FundRequestItem.objects.filter(
            activity_schedule_cost_line_id__in=dangling_ids
        )
        draft_items = dangling.filter(fund_request__status=FundRequestStatus.DRAFT)
        manual = dangling.exclude(fund_request__status=FundRequestStatus.DRAFT).count()
        stats = {
            "found": dangling.count(),
            "draft_repairable": draft_items.count(),
            "manual_review": manual,
            "regenerated_activities": 0,
        }
        if apply:
            by_activity = defaultdict(list)
            for item in draft_items.select_related("fund_request"):
                by_activity[item.activity_id].append(item.id)
            with transaction.atomic():
                draft_items.delete()
                for activity in Activity.objects.filter(id__in=by_activity):
                    sync_monthly_drafts_for_activity(activity)
                    stats["regenerated_activities"] += 1
        return stats
