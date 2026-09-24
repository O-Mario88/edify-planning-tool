"""Record the decision already taken on handovers withdrawn before it was.

A withdrawal leaves its handover ``returned_to_staff``, the status a Partner's
own hand-back uses, but it never recorded the decision its disposition made
(reassigned, back to staff planning, support closed). Every reader of an
undecided return (Partner Monitoring's Resolve Exception, Planning's
Responsible column, the To-Dos, ``resolve_returned_assignment``) therefore
treated those rows as still waiting on staff, and resolving one again could
open a second replacement for the same slot.

``withdrawal_service`` records the decision from now on; this writes it for
the rows withdrawn earlier, from each row's own withdrawal record. Holds and
escalations decided nothing and stay open. Only undecided rows are touched,
so a decision staff already recorded is never overwritten.

Reversing leaves the decisions in place: they are true, and removing them
would bring the double-replacement risk back.
"""

from django.db import migrations

# The mapping ``withdrawal_service.DISPOSITION_DECISIONS`` keeps, frozen here
# so the migration means the same thing whatever the code later becomes.
DECISIONS = {
    "reassign_partner": ("reassigned", "Assign to another Partner"),
    "return_to_planning": ("staff_delivery", "Return to CCEO Planning"),
    "schedule_as_staff": ("staff_delivery", "Schedule as staff"),
    "cancel_support": ("support_closed", "Cancel support"),
}


def record_withdrawal_decisions(apps, schema_editor):
    PartnerAssignment = apps.get_model("partners", "PartnerAssignment")
    Withdrawal = apps.get_model("partners", "PartnerAssignmentWithdrawal")

    undecided = PartnerAssignment.objects.filter(
        status="returned_to_staff", resolved_at__isnull=True
    )
    for assignment in undecided.iterator():
        withdrawal = (
            Withdrawal.objects.filter(assignment_id=assignment.id)
            .exclude(effective_at__isnull=True)
            .order_by("-effective_at")
            .first()
        )
        if withdrawal is None or withdrawal.disposition not in DECISIONS:
            continue
        resolution, label = DECISIONS[withdrawal.disposition]
        PartnerAssignment.objects.filter(
            id=assignment.id, resolved_at__isnull=True
        ).update(
            resolution=resolution,
            resolution_note=f"Decided at withdrawal: {label}.",
            resolved_at=withdrawal.effective_at,
            resolved_by=(withdrawal.requested_by or None),
        )


class Migration(migrations.Migration):
    dependencies = [("partners", "0025_partner_region_names")]

    operations = [
        migrations.RunPython(
            record_withdrawal_decisions, reverse_code=migrations.RunPython.noop
        )
    ]
