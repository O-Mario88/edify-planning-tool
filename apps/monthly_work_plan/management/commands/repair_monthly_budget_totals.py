"""Repair drifted General Budget totals and locked-month snapshot violations.

Two financial-integrity invariants are enforced:

1. LIVE months (status not in LOCKED_STATUSES) must carry totals equal to the
   canonical recompute (program_total from the month's valid
   ActivityScheduleCostLines, admin_total from *active* AdminBudgetLines).
   Drift is reported; ``--apply`` recomputes and saves.

2. LOCKED months must have at least one immutable
   MonthlyBudgetSubmissionSnapshot — the guarded submit path always writes
   one. A locked month with zero snapshots reached its status through the old
   unguarded transition hole; ``--apply`` reverts it to ``draft_generated``
   (with an audit log line) so it must be resubmitted through the guarded
   path (country_budget_service.send_to_rvp).

Dry-run by default: prints what it would do. Pass ``--apply`` to write.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from apps.monthly_work_plan import services as mwp
from apps.monthly_work_plan.country_budget_service import LOCKED_STATUSES
from apps.monthly_work_plan.models import MonthlyWorkPlanBudget

logger = logging.getLogger("apps.monthly_work_plan.repair")


def _expected_totals(budget) -> tuple[int, int, int] | None:
    """Preview the canonical totals WITHOUT saving.

    Mirrors services.recompute_program_total (program side) and
    services.recompute_totals (active-admin-lines side). Returns
    (program_total, admin_total, total_amount), or None when the month_key
    cannot be parsed (recompute_program_total would no-op the same way).
    """
    from apps.activities.models import ActivityScheduleCostLine

    try:
        year, month = budget.month_key.split("-")
        int(year)
        month_i = int(month)
    except (ValueError, AttributeError):
        return None
    lines = ActivityScheduleCostLine.objects.filter(
        activity__deleted_at__isnull=True,
        activity__fy=budget.fy,
        month=month_i,
    ).exclude(activity__status__in=["cancelled", "rejected"])
    program = int(lines.aggregate(total=Sum("amount"))["total"] or 0)
    admin = int(
        budget.admin_lines.filter(status="active").aggregate(total=Sum("total_cost"))[
            "total"
        ]
        or 0
    )
    return program, admin, program + admin


class Command(BaseCommand):
    help = (
        "Report (and with --apply, repair) drifted live General Budget totals "
        "and locked months that have no submission snapshot."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Write the repairs. Without this flag the command is a dry run.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        mode = "APPLY" if apply_changes else "DRY RUN"
        self.stdout.write(f"repair_monthly_budget_totals — {mode}")

        scanned = drifted = repaired = reverted = 0

        for budget_id in MonthlyWorkPlanBudget.objects.order_by(
            "month_key"
        ).values_list("id", flat=True):
            with transaction.atomic():
                budget = (
                    MonthlyWorkPlanBudget.objects.select_for_update()
                    .filter(id=budget_id)
                    .first()
                )
                if budget is None:
                    continue
                scanned += 1

                if budget.status in LOCKED_STATUSES:
                    if not budget.snapshots.exists():
                        msg = (
                            f"[{budget.month_key}] LOCKED status "
                            f"'{budget.status}' with NO submission snapshot — "
                            "this month bypassed the guarded submit path"
                        )
                        if apply_changes:
                            previous = budget.status
                            budget.status = "draft_generated"
                            budget.save(update_fields=["status", "updated_at"])
                            reverted += 1
                            line = (
                                f"{msg}; REVERTED '{previous}' → "
                                "'draft_generated' — it must be resubmitted "
                                "through send_to_rvp."
                            )
                            logger.warning(
                                "repair_monthly_budget_totals: budget %s (%s) "
                                "reverted from %s to draft_generated — locked "
                                "with no submission snapshot",
                                budget.id,
                                budget.month_key,
                                previous,
                            )
                            self.stdout.write(self.style.WARNING(line))
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"{msg}; would revert to 'draft_generated'."
                                )
                            )
                    continue

                # Live month — compare stored totals to the canonical source.
                expected = _expected_totals(budget)
                if expected is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[{budget.month_key}] unparseable month_key — skipped."
                        )
                    )
                    continue
                exp_program, exp_admin, exp_total = expected
                stored = (
                    int(budget.program_total or 0),
                    int(budget.admin_total or 0),
                    int(budget.total_amount or 0),
                )
                if stored == (exp_program, exp_admin, exp_total):
                    continue
                drifted += 1
                detail = (
                    f"[{budget.month_key}] drift: program "
                    f"{stored[0]} → {exp_program}, admin "
                    f"{stored[1]} → {exp_admin}, total "
                    f"{stored[2]} → {exp_total}"
                )
                if apply_changes:
                    mwp.recompute_program_total(budget)
                    mwp.recompute_totals(budget)
                    repaired += 1
                    logger.info(
                        "repair_monthly_budget_totals: budget %s (%s) totals "
                        "recomputed: %s",
                        budget.id,
                        budget.month_key,
                        detail,
                    )
                    self.stdout.write(f"{detail} — repaired.")
                else:
                    self.stdout.write(f"{detail} — would repair.")

        summary = (
            f"scanned={scanned} drifted={drifted} "
            f"repaired={repaired} reverted={reverted}"
        )
        if not apply_changes:
            summary += "  (dry run — pass --apply to write)"
        self.stdout.write(self.style.SUCCESS(summary))
