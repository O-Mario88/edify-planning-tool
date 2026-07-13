"""Backfill MessageParticipant rows, created_by, and last_reply_at for
threads that predate the multi-participant model."""

from django.db import migrations


def backfill(apps, schema_editor):
    MessageThread = apps.get_model("messaging", "MessageThread")
    Message = apps.get_model("messaging", "Message")
    MessageParticipant = apps.get_model("messaging", "MessageParticipant")

    for thread in MessageThread.objects.all():
        msgs = list(Message.objects.filter(thread_id=thread.id).order_by("created_at"))
        if not msgs:
            continue
        first, last = msgs[0], msgs[-1]
        changed = []
        if not thread.created_by:
            thread.created_by = first.sender_id
            changed.append("created_by")
        if not thread.last_reply_at:
            thread.last_reply_at = last.created_at
            changed.append("last_reply_at")
        if changed:
            thread.save(update_fields=changed)

        user_ids = set()
        for m in msgs:
            if m.sender_id:
                user_ids.add(m.sender_id)
            if m.recipient_id:
                user_ids.add(m.recipient_id)
        for uid in user_ids:
            if not MessageParticipant.objects.filter(
                thread_id=thread.id, user_id=uid
            ).exists():
                MessageParticipant.objects.create(
                    thread_id=thread.id, user_id=uid, recipient_type="to"
                )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        (
            "messaging",
            "0004_messageattachment_messagedraft_messageparticipant_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
