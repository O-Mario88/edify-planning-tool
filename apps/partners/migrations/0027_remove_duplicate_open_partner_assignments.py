"""A school is assigned to the same partner only once at a time.

Owner, 2026-09-24: "make sure schools can only be assigned to the partner once
and also added to the same project once. On the live server a user assigned
the same school to the partner many times ... remove the duplicate
assignments."

The only guards were a 15-second double-click window and, on the project
drawer, a match on the exact catalogue item, so repeated handovers of one
school to one partner reached production. This migration removes them; 0028
then adds uniq_open_partner_school_assignment so they cannot come back. The
two are separate migrations because Postgres will not build an index in the
same transaction as deletes that leave deferred foreign-key checks pending on
the table.

WHAT COUNTS AS A DUPLICATE
Handovers still waiting on the partner (status 'assigned' or
'pending_scheduling') for the same school, the same partner and the same Core
slot (NULL and "" folded together) — exactly the index's key. Scheduled and
returned handovers are history and are not touched; Visit 1 and Visit 2 of a
Core package are different slots and are not duplicates of each other.

WHICH ONE STAYS
One row per group is kept: a row carrying history if there is one (a
withdrawal record, a linked activity, reassignment lineage), then one tied to
a project, then the earliest. The rest are deleted, and the partner's open
"schedule this" notifications for them are archived so no To-Do points at a
row that no longer exists. Every removed id is printed to the deploy log.

Rows carrying history are never deleted. If a group holds two of them the
migration stops before changing anything and names them, as 0018 does.

Reverse is a no-op: the deleted duplicates are not recreated.
"""

from __future__ import annotations

from django.db import migrations
from django.db.models import Count, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

OPEN_STATUSES = ("assigned", "pending_scheduling")


def _open_rows(model):
    return (
        model._base_manager.filter(status__in=OPEN_STATUSES, school__isnull=False)
        .annotate(
            slot_support=Coalesce("support_type", Value("")),
            slot_visit=Coalesce("visit_number", Value("")),
            slot_training=Coalesce("training_number", Value("")),
        )
        .order_by()
    )


def remove_duplicate_open_assignments(apps, schema_editor):
    PartnerAssignment = apps.get_model("partners", "PartnerAssignment")
    Withdrawal = apps.get_model("partners", "PartnerAssignmentWithdrawal")
    Notification = apps.get_model("notifications", "Notification")

    key = ("school_id", "partner_id", "slot_support", "slot_visit", "slot_training")
    groups = (
        _open_rows(PartnerAssignment)
        .values(*key)
        .annotate(rows=Count("id"))
        .filter(rows__gt=1)
    )

    to_delete: list[str] = []
    kept: list[tuple[str, list[str]]] = []
    for group in groups:
        rows = list(
            _open_rows(PartnerAssignment)
            .filter(**{k: group[k] for k in key})
            .order_by("created_at", "id")
            .values(
                "id", "project_id", "scheduled_activity_id", "replaces_assignment_id"
            )
        )
        ids = [row["id"] for row in rows]
        with_withdrawal = set(
            Withdrawal.objects.filter(assignment_id__in=ids).values_list(
                "assignment_id", flat=True
            )
        ) | set(
            Withdrawal.objects.filter(replacement_assignment_id__in=ids).values_list(
                "replacement_assignment_id", flat=True
            )
        )
        replaced = set(
            PartnerAssignment.objects.filter(
                replaces_assignment_id__in=ids
            ).values_list("replaces_assignment_id", flat=True)
        )

        def has_history(row):
            return bool(
                row["id"] in with_withdrawal
                or row["id"] in replaced
                or row["scheduled_activity_id"]
                or row["replaces_assignment_id"]
            )

        protected = [row["id"] for row in rows if has_history(row)]
        if len(protected) > 1:
            raise RuntimeError(
                "\nMIGRATION ABORTED — cannot add "
                "uniq_open_partner_school_assignment.\n"
                f"  school_id={group['school_id']!r} partner_id="
                f"{group['partner_id']!r} has {len(protected)} open handovers "
                f"that each carry history and cannot be deleted: {protected!r}.\n"
                "Return or withdraw all but one through the Partner workflow, "
                "then re-run the migration. No change has been applied."
            )
        # Stable sort: history first, then project-linked, then the earliest.
        keeper = sorted(
            rows, key=lambda row: (not has_history(row), row["project_id"] is None)
        )[0]
        removed = [row["id"] for row in rows if row["id"] != keeper["id"]]
        to_delete.extend(removed)
        kept.append((keeper["id"], removed))

    if not to_delete:
        return

    now = timezone.now()
    Notification.objects.filter(
        context_type="partner_assignment",
        context_id__in=to_delete,
        resolved_at__isnull=True,
    ).update(resolved_at=now, status="archived", action_required=False, updated_at=now)
    PartnerAssignment._base_manager.filter(id__in=to_delete).delete()

    print(
        f"\n  Removed {len(to_delete)} duplicate open partner assignment(s) "
        f"across {len(kept)} school/partner pair(s):"
    )
    for keeper_id, removed in kept:
        print(f"    kept {keeper_id}; removed {', '.join(removed)}")


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0057_backfill_cluster_session_invitations"),
        ("activity_catalogue", "0014_mapping_review"),
        ("clusters", "0006_backfill_catchments_and_membership_history"),
        ("notifications", "0005_repoint_dead_workflow_links"),
        ("partners", "0026_record_withdrawal_decisions"),
        ("projects", "0013_project_school_enrollment_history"),
        ("schools", "0022_school_ownership_transfers"),
        ("ssa", "0009_ssa_record_source_and_return"),
    ]

    operations = [
        migrations.RunPython(
            remove_duplicate_open_assignments, migrations.RunPython.noop
        ),
    ]
