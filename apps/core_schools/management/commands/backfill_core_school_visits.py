"""Record visits already planned at Core Schools as core package work.

The Planning page's Core tab and the Cluster schools table open the same
scheduling drawer as each other, and until `apps.core_schools.visit_routing`
that drawer created a plain ``school_visit`` with no package slot. Visits
planned there are real, funded, on somebody's My Plan -- and invisible on the
Core School Visit page, counted toward no package, and priced as client work.

This converts them: the Activity is retyped ``core_visit``, repointed at the
Core Visit costing, re-priced, and linked to one of the package's visit slots.

DRY RUN BY DEFAULT. Pass --apply to write. Re-pricing rebuilds budget lines
and fund-request drafts, so delivered work is left alone unless you ask for it
with --include-delivered.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

# The visit family. Every purpose the Core Schools drawer offers becomes a
# core visit there, so every one of them is in scope here too.
from apps.partners.purposes import PURPOSE_ACTIVITY_TYPES
from apps.planning.visit_gate import (
    COMPANION_VISIT_PURPOSE,
    CORE_RULE_SCHOOL_TYPES,
    DEAD_STATUSES,
    FOLLOW_UP_VISIT_TYPES,
    NOT_YET_PLANNED_STATUSES,
)

VISIT_TYPES = (
    set(FOLLOW_UP_VISIT_TYPES)
    | set(PURPOSE_ACTIVITY_TYPES.values())
    # A core_visit carrying no slot is in scope too. It keeps this command
    # idempotent -- a row converted by an earlier run is recognised and
    # reported as already linked rather than silently vanishing from the
    # candidate set -- and it picks up a core visit that lost its slot, which
    # System Health counts as drift but nothing repaired.
    | {"core_visit"}
    # Not a visit: the in-school training's own workflow. Trainings are
    # credited by their own machinery.
) - {"in_school_training"}

#: Planned but not yet delivered -- the default scope. These are the rows the
#: report described: work on the calendar that has not been done or paid.
PLANNED_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_pending_schedule",
    "pending_scheduling",
)

SKIP_STATUSES = set(DEAD_STATUSES) | set(NOT_YET_PLANNED_STATUSES)


class Command(BaseCommand):
    help = (
        "Convert visits planned at Core Schools from the Planning or Cluster "
        "pages into core package visits (dry run unless --apply)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without it nothing is modified.",
        )
        parser.add_argument(
            "--fy",
            default=None,
            help="Limit to one fiscal year (default: every open year found).",
        )
        parser.add_argument(
            "--school",
            default=None,
            help="Limit to one school's business id, for a careful first run.",
        )
        parser.add_argument(
            "--include-delivered",
            action="store_true",
            help=(
                "Also convert completed/verified/closed visits. This re-prices "
                "work that may already have been paid -- read the report first."
            ),
        )

    def handle(self, *args, **options):
        from apps.activities.models import Activity
        from apps.activities.services import reprice_activity
        from apps.core_schools.core_planning_services import (
            CorePackageSchedulingService,
        )
        from apps.core_schools.models import CoreActivitySlot
        from apps.core_schools.services import CORE_SLOT_DONE_STATUSES
        from apps.core_schools.visit_routing import (
            CORE_VISIT_TYPE,
            core_plan_for_visit,
            core_visit_catalogue_item,
        )

        apply = options["apply"]
        include_delivered = options["include_delivered"]

        candidates = (
            Activity.objects.filter(
                deleted_at__isnull=True,
                school__school_type__in=CORE_RULE_SCHOOL_TYPES,
                activity_type__in=VISIT_TYPES,
            )
            .exclude(status__in=SKIP_STATUSES)
            .exclude(purpose_type=COMPANION_VISIT_PURPOSE)
            .select_related("school")
            .order_by("school__school_id", "planned_date", "id")
        )
        if options["fy"]:
            candidates = candidates.filter(fy=str(options["fy"]))
        if options["school"]:
            candidates = candidates.filter(school__school_id=options["school"])
        if not include_delivered:
            candidates = candidates.filter(status__in=PLANNED_STATUSES)

        # Work an activity already linked to a slot is already counted.
        linked_activity_ids = set(
            CoreActivitySlot.objects.filter(
                activity_id__in=list(candidates.values_list("id", flat=True))
            ).values_list("activity_id", flat=True)
        )

        converted = 0
        skipped_no_plan: list[str] = []
        already_linked = 0
        failed: list[tuple[str, str]] = []
        touched_plans: dict[str, object] = {}

        for activity in candidates:
            if activity.id in linked_activity_ids:
                already_linked += 1
                continue
            plan = core_plan_for_visit(
                activity.school, scheduled_date=activity.planned_date
            )
            if plan is None:
                skipped_no_plan.append(activity.school.school_id)
                continue

            label = (
                f"{activity.school.school_id} {activity.planned_date or 'undated'} "
                f"{activity.activity_type} [{activity.status}] {activity.id}"
            )
            if not apply:
                self.stdout.write(f"  would convert  {label}")
                converted += 1
                touched_plans[plan.id] = plan
                continue

            try:
                with transaction.atomic():
                    item = core_visit_catalogue_item(on_date=activity.planned_date)
                    slot = CorePackageSchedulingService.reserve_existing_slot(
                        plan, "visit"
                    )
                    activity.activity_type = CORE_VISIT_TYPE
                    activity.catalogue_item = item
                    activity.save(
                        update_fields=[
                            "activity_type",
                            "catalogue_item",
                            "updated_at",
                        ]
                    )
                    # Re-price against the Core Visit costing. Delivered work
                    # keeps the money it already moved unless asked otherwise.
                    if activity.status not in CORE_SLOT_DONE_STATUSES:
                        reprice_activity(activity)
                    CorePackageSchedulingService.commit_schedule(
                        slot,
                        activity_id=activity.id,
                        scheduled_for=activity.planned_date,
                        scheduled_month=str(activity.planned_month or ""),
                        scheduled_week=activity.planned_week,
                        assigned_staff_id=str(activity.responsible_staff_id or ""),
                        partner_id=(
                            str(activity.assigned_partner_id)
                            if activity.assigned_partner_id
                            else None
                        ),
                    )
            except Exception as exc:  # noqa: BLE001 — report, never abort the run
                failed.append((label, str(exc)))
                continue

            self.stdout.write(self.style.SUCCESS(f"  converted      {label}"))
            converted += 1
            touched_plans[plan.id] = plan

        if apply and touched_plans:
            from apps.core_schools.services import resync_plan_completion

            for plan in touched_plans.values():
                resync_plan_completion(plan)

        self.stdout.write("")
        verb = "Converted" if apply else "Would convert"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {converted} core school visit(s).")
        )
        if already_linked:
            self.stdout.write(
                f"{already_linked} already linked to a package slot — left alone."
            )
        if skipped_no_plan:
            unique = sorted(set(skipped_no_plan))
            self.stdout.write(
                self.style.WARNING(
                    f"{len(skipped_no_plan)} visit(s) at {len(unique)} school(s) with "
                    f"no core package for that year — not converted: "
                    f"{', '.join(unique[:10])}" + (" …" if len(unique) > 10 else "")
                )
            )
        for label, error in failed:
            self.stdout.write(self.style.ERROR(f"  FAILED {label}: {error}"))
        if failed:
            self.stdout.write(
                self.style.ERROR(f"{len(failed)} visit(s) could not be converted.")
            )
        if not apply:
            self.stdout.write("")
            self.stdout.write("Dry run — nothing was written. Re-run with --apply.")

        # Over-cap packages are recorded, not refused: the work is already on
        # the calendar. Name them so the split can be corrected deliberately.
        if apply:
            self._report_over_cap(touched_plans.values())

    def _report_over_cap(self, plans) -> None:
        from apps.core_schools.core_planning_services import (
            CorePackageSchedulingService,
        )
        from apps.core_schools.models import CoreActivitySlot

        over = []
        for plan in plans:
            staff_visits = sum(
                1
                for slot in CoreActivitySlot.objects.filter(
                    core_plan=plan, activity_type="visit", owner="staff"
                )
                if CorePackageSchedulingService.is_allocated(slot)
            )
            if staff_visits > 2:
                over.append((plan.school_id, staff_visits))
        if over:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "These packages now hold more than the 2 staff visits the "
                    "split allows. The work was already planned, so it is "
                    "recorded rather than refused — rebalance deliberately:"
                )
            )
            for school_id, count in sorted(over):
                self.stdout.write(f"  {school_id}: {count} staff visits")
