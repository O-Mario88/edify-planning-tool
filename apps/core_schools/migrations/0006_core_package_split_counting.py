"""Bring the Core packages in line with the owner's 2026-09-30 counting rules.

Owner, 2026-09-30:

* donor, content/story, invitation and social visits are NOT package work —
  they have no limit and never take one of the package's four visits;
* Special Project visits and trainings at a Core School DO count toward its
  package.

New work follows both rules as it is saved (apps.core_schools.package_credit,
apps.core_schools.package_split). This brings the work already on the
calendar into line, in two passes:

1. Slots linked to a donor, story, invitation or social visit — the Core
   Schools drawer booked those as a ``core_visit`` holding a V1..V4 slot — are
   given back to the package. The visits themselves are untouched.
2. Live Special Project visits and trainings at Core Schools that fill no slot
   are linked to their package's next open slot, oldest first — as core_schools
   0005 did for every other route.

No work is refused or removed: a package already past a side of the 2 + 2
split keeps what it has and simply takes no more on that side.

Historical models only, and no live service code: the live Activity model
would ask for columns a later migration adds (see activities 0057/0058).
Everything touched is printed to the deploy log. The reverse is a no-op.
`manage.py credit_core_package_work` runs the same repair with live code (dry
run first), and also holds slots for waiting project hand-overs.
"""

from __future__ import annotations

from django.db import migrations
from django.db.models import Q

from apps.core.cuid import deterministic
from apps.core.fy import get_operational_fy

_LEGACY_FY = "2026"

NON_PACKAGE_VISIT_TYPES = (
    "donor_visit",
    "story_gathering_visit",
    "school_invitation",
    "social_visit",
)
NON_PACKAGE_VISIT_PURPOSES = (
    "donor_visit",
    "story_gathering",
    "school_invitation",
    "social_visit",
)
VISIT_TYPES = frozenset(
    {
        "school_visit",
        "follow_up_visit",
        "training_follow_up_visit",
        "coaching_visit",
        "in_school_support",
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
        "partner_ssa_collection",
        "in_school_coaching_visit",
        "core_visit",
    }
)
TRAINING_TYPES = frozenset(
    {"training", "in_school_training", "school_improvement_training", "core_training"}
)
UNCREDITED_STATUSES = (
    "cancelled",
    "rejected",
    "deferred",
    "not_planned",
    "awaiting_owner_approval",
)
COMPANION_VISIT_PURPOSE = "in_school_training_delivery_visit"
TAKEN_STATUSES = frozenset(
    {
        "assigned",
        "scheduled",
        "partner_scheduled",
        "partner scheduled",
        "rescheduled",
        "in_progress",
        "in progress",
        "evidence uploaded",
        "evidence_uploaded",
        "evidence accepted",
        "evidence_accepted",
        "awaiting_ia_verification",
        "submitted_to_pl",
        "ia pending",
        "iapending",
        "completed",
        "closed",
        "ia_verified",
        "iaverified",
        "accountant_confirmed",
        "accountantconfirmed",
        "returned",
        "returned_by_pl",
        "evidence returned",
        "evidence_returned",
        "completion_started",
        "completion started",
        "salesforce_id_required",
        "returned_by_ia",
        "assigned_to_partner",
        "awaiting_owner_approval",
    }
)
DONE_STATUSES = ("completed", "closed", "ia_verified", "accountant_confirmed")
CLOSED_PLAN_STATUSES = (
    "Archived",
    "archived",
    "Cancelled",
    "cancelled",
    "Exited",
    "exited",
)


def _slot_id(school_id: str, letter: str, seq: int, fy: str) -> str:
    if str(fy) == _LEGACY_FY:
        return deterministic("cslot", school_id, f"{letter}{seq}")
    return deterministic("cslot", school_id, str(fy), f"{letter}{seq}")


def _taken(status) -> bool:
    return (status or "").strip().lower() in TAKEN_STATUSES


def _plan_for(CorePlan, school_code: str, fy: str, current_fy: str):
    live = CorePlan.objects.filter(school_id=school_code).exclude(
        status__in=CLOSED_PLAN_STATUSES
    )
    plan = live.filter(fy=fy).first() if fy else None
    if plan is not None:
        return plan
    if fy and fy < current_fy:
        return None
    return live.filter(fy=current_fy).first() or live.order_by("-fy").first()


def _resync(CoreActivitySlot, plan) -> None:
    counts = {
        kind: CoreActivitySlot.objects.filter(
            core_plan=plan, activity_type=kind, status__in=DONE_STATUSES
        ).count()
        for kind in ("visit", "training", "assessment")
    }
    plan.visits_completed = counts["visit"]
    plan.trainings_completed = counts["training"]
    plan.assessment_completed = counts["assessment"]
    plan.save(
        update_fields=[
            "visits_completed",
            "trainings_completed",
            "assessment_completed",
        ]
    )


def apply_split_counting(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    CorePlan = apps.get_model("core_schools", "CorePlan")
    CoreActivitySlot = apps.get_model("core_schools", "CoreActivitySlot")
    EvidenceRecord = apps.get_model("evidence", "EvidenceRecord")

    touched = {}

    # 1. Donor, story, invitation and social visits give their slots back.
    outreach = Activity.objects.filter(
        Q(activity_type__in=NON_PACKAGE_VISIT_TYPES)
        | Q(purpose_type__in=NON_PACKAGE_VISIT_PURPOSES)
    ).values("id")
    released = 0
    for slot in CoreActivitySlot.objects.filter(
        activity_id__in=outreach
    ).select_related("core_plan"):
        print(
            f"  core package: released {slot.id} ({slot.school_id} "
            f"{slot.activity_type[0].upper()}{slot.sequence_number}) from "
            f"non-package visit {slot.activity_id}"
        )
        slot.status = "Planned"
        slot.activity_id = None
        slot.owner = "unassigned"
        slot.assigned_staff_id = None
        slot.assigned_partner_id = None
        slot.assigned_partner_name = None
        slot.scheduled_for = None
        slot.scheduled_month = None
        slot.scheduled_week = None
        slot.salesforce_id = None
        slot.evidence_uri = None
        slot.save()
        touched[slot.core_plan_id] = slot.core_plan
        released += 1

    # 2. Special Project visits and trainings that fill no slot.
    current_fy = get_operational_fy()
    linked = CoreActivitySlot.objects.filter(activity_id__isnull=False).values(
        "activity_id"
    )
    work = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            school__school_type="core",
            cluster__isnull=True,
            activity_type__in=VISIT_TYPES | TRAINING_TYPES,
            project_id__isnull=False,
        )
        .exclude(project_id="")
        .exclude(status__in=UNCREDITED_STATUSES)
        .exclude(purpose_type=COMPANION_VISIT_PURPOSE)
        .exclude(purpose_type__in=NON_PACKAGE_VISIT_PURPOSES)
        .exclude(id__in=linked)
        .select_related("school")
        .order_by("school__school_id", "planned_date", "created_at", "id")
    )
    credited = skipped = 0
    for activity in work.iterator():
        kind = "visit" if activity.activity_type in VISIT_TYPES else "training"
        school_code = activity.school.school_id
        plan = _plan_for(CorePlan, school_code, str(activity.fy or ""), current_fy)
        if plan is None:
            skipped += 1
            continue
        slots = list(
            CoreActivitySlot.objects.filter(
                core_plan=plan, activity_type=kind
            ).order_by("sequence_number")
        )
        slot = None
        if activity.delivery_type == "partner" and activity.assigned_partner_id:
            slot = next(
                (
                    s
                    for s in slots
                    if (s.status or "").strip().lower() == "assigned"
                    and s.assigned_partner_id == activity.assigned_partner_id
                    and not s.activity_id
                ),
                None,
            )
        if slot is None:
            slot = next((s for s in slots if not _taken(s.status)), None)
        if slot is None:
            seq = max((s.sequence_number for s in slots), default=0) + 1
            slot, _ = CoreActivitySlot.objects.get_or_create(
                id=_slot_id(plan.school_id, kind[0], seq, plan.fy),
                defaults={
                    "core_plan": plan,
                    "school_id": plan.school_id,
                    "intervention": (plan.interventions or ["christlike_behaviour"])[0],
                    "activity_type": kind,
                    "sequence_number": seq,
                },
            )
        status = activity.status or ""
        slot.activity_id = activity.id
        slot.status = "Scheduled" if status.lower() == "planned" else status
        slot.owner = "partner" if activity.delivery_type == "partner" else "staff"
        slot.assigned_staff_id = activity.responsible_staff_id
        if activity.assigned_partner_id:
            slot.assigned_partner_id = activity.assigned_partner_id
        slot.scheduled_for = (
            activity.scheduled_date.date()
            if activity.scheduled_date
            else activity.planned_date
        )
        slot.scheduled_month = (
            str(activity.planned_month) if activity.planned_month else None
        )
        slot.scheduled_week = activity.planned_week
        if activity.salesforce_activity_id:
            slot.salesforce_id = activity.salesforce_activity_id
        if not slot.evidence_uri:
            slot.evidence_uri = (
                EvidenceRecord.objects.filter(
                    activity_id=activity.id, quarantined=False
                )
                .order_by("-created_at")
                .values_list("uri", flat=True)
                .first()
            )
        slot.save()
        touched[plan.id] = plan
        credited += 1
        print(
            f"  core package: {school_code} project {activity.activity_type} "
            f"[{activity.status}] {activity.id} -> {kind[0].upper()}"
            f"{slot.sequence_number} (FY{plan.fy})"
        )

    for plan in touched.values():
        _resync(CoreActivitySlot, plan)
    if released or credited or skipped:
        print(
            f"  core package: released {released} slot(s) from non-package "
            f"visits; linked {credited} project activit(y/ies); {skipped} with "
            f"no package for their year; {len(touched)} plan(s) recounted."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core_schools", "0005_credit_core_package_work"),
    ]

    operations = [migrations.RunPython(apply_split_counting, migrations.RunPython.noop)]
