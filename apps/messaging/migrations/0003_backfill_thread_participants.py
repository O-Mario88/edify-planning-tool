"""Backfill participant pairs on threads created before thread identity
included participants (threads were keyed on subject alone)."""

from django.db import migrations


def backfill(apps, schema_editor):
    MessageThread = apps.get_model("messaging", "MessageThread")
    Message = apps.get_model("messaging", "Message")

    for thread in MessageThread.objects.filter(participant_a_id__isnull=True):
        first = (
            Message.objects.filter(thread_id=thread.id).order_by("created_at").first()
        )
        if not first:
            continue
        pair = sorted(p for p in (first.sender_id, first.recipient_id) if p)
        if not pair:
            continue
        thread.participant_a_id = pair[0]
        thread.participant_b_id = pair[-1]
        thread.save(update_fields=["participant_a_id", "participant_b_id"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0002_messagethread_participant_a_id_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
